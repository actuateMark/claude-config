#!/usr/bin/env python3
"""collect.py — gather observations for dashboard-check signals.

Replaces the LLM-driven Collect step in /dashboard-check. Reads
config/signals.json, dispatches each enabled signal by `source` field,
writes per-source result files under $TEMPDIR/ that render.py merges.

Auth model:
  NR  → nerdgraph via personal API key at ~/.config/newrelic/key,
        account ID at ~/.config/newrelic/account_id
  AWS → boto3 with AWS_PROFILE (default: dashboard-check) which is
        wired to IAM Roles Anywhere via credential_process

Usage:
  collect.py --tempdir <dir> [--aws-profile dashboard-check] [-v]

Outputs:
  $TEMPDIR/nr_results.json   {signal_id: scalar | dict | null}
  $TEMPDIR/cw_results.json   (cw_log + cw_metric merged)
  $TEMPDIR/ce_results.json
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent
CONFIG_DIR = SKILL_DIR / "config"

NR_KEY_PATH = Path.home() / ".config" / "newrelic" / "key"
NR_ACCOUNT_ID_PATH = Path.home() / ".config" / "newrelic" / "account_id"
NR_GRAPHQL_URL = "https://api.newrelic.com/graphql"
NR_TIMEOUT_S = 30

log = logging.getLogger("dashboard-check.collect")


def _read_secret(path: Path) -> str:
    try:
        return path.read_text().strip()
    except OSError as e:
        raise RuntimeError(f"unable to read {path}: {e}")


def _short(v):
    if v is None:
        return "None"
    if isinstance(v, dict):
        keys = list(v.keys())[:3]
        return f"{{{len(v)} keys, e.g. {keys}}}"
    s = str(v)
    return s if len(s) <= 60 else s[:57] + "..."


# --- NR collection --------------------------------------------------------

def call_nerdgraph(nrql: str, account_id: int, api_key: str) -> list[dict]:
    """Execute one NRQL via nerdgraph. Returns the `results` list."""
    body = {
        "query": (
            "{ actor { account(id: " + str(account_id) + ") "
            "{ nrql(query: " + json.dumps(nrql) + ") { results } } } }"
        )
    }
    req = urllib.request.Request(
        NR_GRAPHQL_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"API-Key": api_key, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=NR_TIMEOUT_S) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if "errors" in data and data["errors"]:
        raise RuntimeError(f"nerdgraph errors: {data['errors']}")
    if not data.get("data") or not data["data"].get("actor"):
        raise RuntimeError(f"unexpected nerdgraph shape: {str(data)[:200]}")
    nrql_block = data["data"]["actor"]["account"]["nrql"]
    if nrql_block is None:
        return []
    return nrql_block.get("results") or []


def parse_nr_results(results: list[dict]):
    """Convert nerdgraph results to scalar OR dict shape render.py expects.

    Scalar shape: single row, single non-facet metric → that metric's value.
      [{"count": 100}]            → 100
      [{"average": 42.5}]         → 42.5
    FACET shape: any row has a 'facet' field → {facet_value: metric_value}.
      [{"facet": "x", "count": 10}, {"facet": "y", "count": 20}]
        → {"x": 10, "y": 20}

    NB: nerdgraph echoes the facet column inside each row as well as in the
    `facet` field, so the row may look like
      {"facet": "x", "container_name": "x", "count": 10}
    We pick the metric value by preferring numeric fields, falling back to
    the last non-facet field. The column-echo (which equals the facet) is
    skipped because it isn't numeric.
    """

    def pick_metric(row: dict, facet_value=None):
        # Skip "facet" itself + any field whose value mirrors the facet string
        # (nerdgraph's column echo for FACET queries).
        candidates = []
        for k, v in row.items():
            if k == "facet":
                continue
            if facet_value is not None and v == facet_value:
                continue
            candidates.append((k, v))
        if not candidates:
            return None
        # Prefer numeric values
        for k, v in candidates:
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return v
        # Fallback to the last non-facet field (count tends to be last)
        return candidates[-1][1]

    if not results:
        return None
    if any("facet" in r for r in results):
        out: dict = {}
        for r in results:
            facet = r.get("facet")
            if isinstance(facet, list):
                facet = " / ".join(str(x) for x in facet)
            value = pick_metric(r, facet_value=facet)
            if value is not None:
                out[str(facet)] = value
        return out
    return pick_metric(results[0])


def collect_nr_signals(signals: list[dict]) -> dict:
    api_key = _read_secret(NR_KEY_PATH)
    account_id = int(_read_secret(NR_ACCOUNT_ID_PATH))
    out: dict = {}
    for sig in signals:
        sid = sig["id"]
        nrql = sig.get("nrql")
        if not nrql:
            log.warning("skip %s: no `nrql` field on nr_* signal", sid)
            out[sid] = None
            continue
        try:
            raw = call_nerdgraph(nrql, account_id, api_key)
            value = parse_nr_results(raw)
            out[sid] = value
            log.info("nr  %-40s = %s", sid, _short(value))
        except Exception as e:
            log.error("nr  %-40s FAILED: %s", sid, e)
            out[sid] = None
    return out


# --- AWS collection -------------------------------------------------------
#
# Per-signal dispatchers — keyed by signal id. Each returns the scalar/dict
# value (matching render.py's expectation). When new AWS signals are added
# to the catalog, add a function here and a dispatch entry.

def _boto_session(profile: str):
    import boto3
    return boto3.Session(profile_name=profile)


def cw_log_onboarder_activity_us(profile: str) -> int:
    """`onboarder_activity_us` — count 'get_sites HTTP' over last 1h."""
    s = _boto_session(profile)
    client = s.client("logs", region_name="us-west-2")
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - 3600 * 1000
    paginator = client.get_paginator("filter_log_events")
    pages = paginator.paginate(
        logGroupName="/aws/lambda/immix-autopatrol-onboarding",
        startTime=start_ms,
        endTime=end_ms,
        filterPattern="get_sites HTTP",
    )
    count = 0
    for page in pages:
        count += len(page.get("events", []))
    return count


def cw_metric_onboarder_invocations_us(profile: str) -> float:
    """`onboarder_lambda_invocations_us` — Sum(Invocations) over last 1h."""
    s = _boto_session(profile)
    client = s.client("cloudwatch", region_name="us-west-2")
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=1)
    resp = client.get_metric_statistics(
        Namespace="AWS/Lambda",
        MetricName="Invocations",
        Dimensions=[{"Name": "FunctionName", "Value": "immix-autopatrol-onboarding"}],
        StartTime=start,
        EndTime=end,
        Period=3600,
        Statistics=["Sum"],
    )
    dps = resp.get("Datapoints", [])
    return float(dps[0]["Sum"]) if dps else 0.0


def _cw_metric_lambda_errors(profile: str, region: str, function_name: str) -> float:
    """Sum(Errors) for a Lambda function over the last 1h. Returns 0 if no
    datapoints (i.e. function had zero invocations or zero errors)."""
    s = _boto_session(profile)
    client = s.client("cloudwatch", region_name=region)
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=1)
    resp = client.get_metric_statistics(
        Namespace="AWS/Lambda",
        MetricName="Errors",
        Dimensions=[{"Name": "FunctionName", "Value": function_name}],
        StartTime=start,
        EndTime=end,
        Period=3600,
        Statistics=["Sum"],
    )
    dps = resp.get("Datapoints", [])
    return float(dps[0]["Sum"]) if dps else 0.0


def cw_metric_inference_api_prod_errors_uw2(profile: str) -> float:
    """`inferenceapi_prod_errors_us_west_2` — Sum(Errors) for InferenceAPI-prod
    in us-west-2 over the last 1h. Reactive companion to ecr_pruning_risk_count:
    if ECR-prune monitoring fails for any reason and prod takes down inference,
    THIS signal catches it on the next dashboard tick."""
    return _cw_metric_lambda_errors(profile, "us-west-2", "InferenceAPI-prod")


def cw_metric_inference_api_prod_errors_euw1(profile: str) -> float:
    """`inferenceapi_prod_errors_eu_west_1` — same for the EU region."""
    return _cw_metric_lambda_errors(profile, "eu-west-1", "InferenceAPI-prod")


# --- AutoPatrol cleanup Lambda signals ----------------------------------------
#
# Replaces the bulk of the /autopatrol-cleanup-lambda-check skill's mechanical
# checks. The skill stays around for interpretive bits (DDB drift scan,
# onboarder hotfix code-grep, deploy-workflow integrity) but the per-tick
# health surface is now signal-based and graphs/regresses on the dashboard.

_CLEANUP_LAMBDA = "immix-autopatrol-schedule-cleanup"
_CLEANUP_LOG_GROUP = "/aws/lambda/immix-autopatrol-schedule-cleanup"
_CLEANUP_REGION = "us-west-2"
# Stage SQS — this is what's actually live (prod queue lands at Step F).
_CLEANUP_DLQ_URL = (
    "https://sqs.us-west-2.amazonaws.com/388576304176/"
    "autopatrol_stale_schedule_cleanup_dlq_dev.fifo"
)
_CLEANUP_MAIN_QUEUE_URL = (
    "https://sqs.us-west-2.amazonaws.com/388576304176/"
    "autopatrol_stale_schedule_cleanup_dev.fifo"
)


def _cw_log_filter_count_1h(profile: str, log_group: str, pattern: str) -> int:
    """Count log events matching `pattern` in `log_group` over the trailing 1h."""
    s = _boto_session(profile)
    client = s.client("logs", region_name=_CLEANUP_REGION)
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - 3600 * 1000
    paginator = client.get_paginator("filter_log_events")
    pages = paginator.paginate(
        logGroupName=log_group,
        startTime=start_ms,
        endTime=end_ms,
        filterPattern=pattern,
    )
    count = 0
    for page in pages:
        count += len(page.get("events", []))
    return count


def _sqs_approx_message_count(profile: str, queue_url: str) -> int:
    """ApproximateNumberOfMessages on a queue. 0 if attribute missing."""
    s = _boto_session(profile)
    client = s.client("sqs", region_name=_CLEANUP_REGION)
    resp = client.get_queue_attributes(
        QueueUrl=queue_url,
        AttributeNames=["ApproximateNumberOfMessages"],
    )
    return int(resp.get("Attributes", {}).get("ApproximateNumberOfMessages", 0))


def cw_sqs_cleanup_lambda_dlq_depth(profile: str) -> int:
    """`cleanup_lambda_dlq_depth` — DLQ depth on the cleanup Lambda's SQS
    consumer. Should always be 0; non-zero = 3+ consecutive Lambda failures
    on a message (matches the SKILL.md 'always 0' invariant)."""
    return _sqs_approx_message_count(profile, _CLEANUP_DLQ_URL)


def cw_sqs_cleanup_lambda_main_queue_depth(profile: str) -> int:
    """`cleanup_lambda_main_queue_depth` — backlog on the cleanup Lambda's
    main queue. Healthy = 0..tens during emit bursts. >100 sustained = Lambda
    lagging behind connector emit rate."""
    return _sqs_approx_message_count(profile, _CLEANUP_MAIN_QUEUE_URL)


def cw_log_cleanup_lambda_errors(profile: str) -> int:
    """`cleanup_lambda_errors` — ERROR log lines/h. Should be 0."""
    return _cw_log_filter_count_1h(profile, _CLEANUP_LOG_GROUP, "ERROR")


def cw_log_cleanup_lambda_would_patch_rate(profile: str) -> int:
    """`cleanup_lambda_would_patch_rate` — 'would PATCH' lines/h. Fires only
    when CLEANUP_ENABLED=false OR DRY_RUN=true. Post-2026-04-23 flip should
    be ~0; lingering hits = something running in dark mode."""
    return _cw_log_filter_count_1h(profile, _CLEANUP_LOG_GROUP, "would PATCH")


def cw_log_cleanup_lambda_actual_disable_rate(profile: str) -> int:
    """`cleanup_lambda_actual_disable_rate` — actual PATCH-Active=False fires
    against AutoPatrolSchedule. Manager-visible audit metric. Spike >10/h =
    flap risk."""
    return _cw_log_filter_count_1h(
        profile, _CLEANUP_LOG_GROUP, "disabled admin schedule"
    )


def cw_log_cleanup_lambda_anomaly_reset_rate(profile: str) -> int:
    """`cleanup_lambda_anomaly_reset_rate` — schedules that hit threshold but
    were NOT disabled because Immix says they're Active. Safety-net firing —
    elevated rate = our connector vs Immix mismatch ongoing.

    Filter pattern wrapped in double quotes — CloudWatch's filter-pattern
    grammar treats ':' as a special term separator, so an unquoted literal
    'anomaly: bucket=' raises InvalidParameterException."""
    return _cw_log_filter_count_1h(
        profile, _CLEANUP_LOG_GROUP, '"anomaly: bucket="'
    )


def cw_lambda_cleanup_lambda_event_source_mapping_state(profile: str) -> int:
    """`cleanup_lambda_event_source_mapping_state` — 1 if the SQS event-source
    mapping for the cleanup Lambda is Enabled, 0 otherwise. Step 1 of the
    SKILL.md skill — if this is 0, nothing else matters: the consumer is off."""
    s = _boto_session(profile)
    client = s.client("lambda", region_name=_CLEANUP_REGION)
    resp = client.list_event_source_mappings(FunctionName=_CLEANUP_LAMBDA)
    mappings = resp.get("EventSourceMappings", [])
    if not mappings:
        return 0
    return 1 if mappings[0].get("State") == "Enabled" else 0


def ce_s3_daily_total(profile: str) -> float:
    """`cost_s3_daily_total` — yesterday's S3 UnblendedCost, USD.

    Kept as a standalone for backward compat; new per-service signals share
    the cached `_ce_aggregate_yesterday` call below.
    """
    return _ce_aggregate_yesterday(profile).get("Amazon Simple Storage Service", 0.0)


# --- Cost Explorer: cached per-day aggregate -----------------------------
#
# Every dashboard-check run that touches CE uses these two cached helpers so
# we make at most TWO CE calls per run regardless of how many cost signals
# are wired. CE is metered ($0.01/page) and the API is slow — caching here
# is non-negotiable. Cache key is the UTC date so a single collector
# invocation reuses results across signals; the next hourly run repopulates.

_CE_AGGREGATE_CACHE: dict[str, dict[str, float]] = {}
_CE_S3_BREAKDOWN_CACHE: dict[str, dict[str, float]] = {}


def _ce_aggregate_yesterday(profile: str) -> dict[str, float]:
    """Single CE call grouped by SERVICE, returns {service_name: usd_yesterday}.

    Includes synthetic key `__total__`. Cached for the duration of the
    process by the UTC date.
    """
    today = datetime.now(timezone.utc).date()
    key = today.isoformat()
    if key in _CE_AGGREGATE_CACHE:
        return _CE_AGGREGATE_CACHE[key]
    s = _boto_session(profile)
    client = s.client("ce", region_name="us-east-1")
    end = today
    start = end - timedelta(days=1)
    resp = client.get_cost_and_usage(
        TimePeriod={"Start": str(start), "End": str(end)},
        Granularity="DAILY",
        Metrics=["UnblendedCost"],
        GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
    )
    out: dict[str, float] = {"__total__": 0.0}
    rows = resp.get("ResultsByTime", [])
    if rows:
        for g in rows[0].get("Groups", []):
            svc = g["Keys"][0]
            cost = float(g["Metrics"]["UnblendedCost"]["Amount"])
            if cost < 0.005:
                continue  # rounding noise
            out[svc] = round(cost, 2)
            out["__total__"] += cost
        out["__total__"] = round(out["__total__"], 2)
    _CE_AGGREGATE_CACHE[key] = out
    return out


def _ce_s3_breakdown_yesterday(profile: str) -> dict[str, float]:
    """Single CE call grouped by USAGE_TYPE filtered to S3.
    Returns {classified_category: usd_yesterday} including __total__.

    Classifier mirrors `/cost-check`'s S3 categorization (Tier1/2/3 + Storage
    + DataTransfer + EarlyDelete + Retrieval + Other). Cached by UTC date.
    """
    today = datetime.now(timezone.utc).date()
    key = today.isoformat()
    if key in _CE_S3_BREAKDOWN_CACHE:
        return _CE_S3_BREAKDOWN_CACHE[key]
    s = _boto_session(profile)
    client = s.client("ce", region_name="us-east-1")
    end = today
    start = end - timedelta(days=1)
    resp = client.get_cost_and_usage(
        TimePeriod={"Start": str(start), "End": str(end)},
        Granularity="DAILY",
        Metrics=["UnblendedCost"],
        Filter={
            "Dimensions": {
                "Key": "SERVICE",
                "Values": ["Amazon Simple Storage Service"],
            }
        },
        GroupBy=[{"Type": "DIMENSION", "Key": "USAGE_TYPE"}],
    )

    def classify(ut: str) -> str:
        if "Tier1" in ut: return "tier1_put"
        if "Tier2" in ut: return "tier2_get"
        if "Tier3" in ut: return "tier3_replication"
        if "Tier8" in ut or "Tier9" in ut: return "tier8_9_glacier"
        if "TimedStorage" in ut or ("Storage" in ut and "Requests" not in ut): return "storage_gb_month"
        if "DataTransfer" in ut or "AWS-Out-Bytes" in ut or "AWS-In-Bytes" in ut: return "data_transfer"
        if "EarlyDelete" in ut: return "early_delete"
        if "Retrieval" in ut: return "retrieval"
        return "other"

    out: dict[str, float] = {"__total__": 0.0}
    rows = resp.get("ResultsByTime", [])
    if rows:
        for g in rows[0].get("Groups", []):
            ut = g["Keys"][0]
            cost = float(g["Metrics"]["UnblendedCost"]["Amount"])
            if cost < 0.005:
                continue
            cat = classify(ut)
            out[cat] = out.get(cat, 0.0) + cost
            out["__total__"] += cost
    out = {k: round(v, 2) for k, v in out.items()}
    _CE_S3_BREAKDOWN_CACHE[key] = out
    return out


# --- Per-service cost signal collectors ----------------------------------
#
# All read from the cached aggregate; cost is one CE call total per run.

def ce_total_daily(profile: str) -> float:
    return _ce_aggregate_yesterday(profile)["__total__"]


def ce_top_services_daily(profile: str) -> dict[str, float]:
    """Top-15 services by yesterday's cost, FACET dict for the dashboard."""
    agg = _ce_aggregate_yesterday(profile)
    items = [(k, v) for k, v in agg.items() if k != "__total__"]
    items.sort(key=lambda kv: -kv[1])
    return dict(items[:15])


def _ce_service_daily(svc_name: str):
    """Curry a per-service collector that pulls from the cached aggregate."""
    def fn(profile: str) -> float:
        return _ce_aggregate_yesterday(profile).get(svc_name, 0.0)
    fn.__name__ = f"ce_service_{svc_name.replace(' ', '_').replace('-', '_')}"
    return fn


def ce_s3_breakdown_daily(profile: str) -> dict[str, float]:
    """FACET dict of S3 USAGE_TYPE-classified categories."""
    bd = _ce_s3_breakdown_yesterday(profile)
    return {k: v for k, v in bd.items() if k != "__total__"}


def ce_s3_tier3_daily(profile: str) -> float:
    """Tier3 (replication / lifecycle) — the $44k/yr line item."""
    return _ce_s3_breakdown_yesterday(profile).get("tier3_replication", 0.0)


def ce_s3_storage_daily(profile: str) -> float:
    """S3 storage GB-month component only."""
    return _ce_s3_breakdown_yesterday(profile).get("storage_gb_month", 0.0)


def ce_s3_tier1_daily(profile: str) -> float:
    """S3 PUT request volume cost only."""
    return _ce_s3_breakdown_yesterday(profile).get("tier1_put", 0.0)


AWS_DISPATCH: dict[str, callable] = {
    "onboarder_activity_us": cw_log_onboarder_activity_us,
    "onboarder_lambda_invocations_us": cw_metric_onboarder_invocations_us,
    "inferenceapi_prod_errors_us_west_2": cw_metric_inference_api_prod_errors_uw2,
    "inferenceapi_prod_errors_eu_west_1": cw_metric_inference_api_prod_errors_euw1,
    # AutoPatrol cleanup Lambda — see § "AutoPatrol cleanup Lambda signals"
    "cleanup_lambda_dlq_depth": cw_sqs_cleanup_lambda_dlq_depth,
    "cleanup_lambda_main_queue_depth": cw_sqs_cleanup_lambda_main_queue_depth,
    "cleanup_lambda_errors": cw_log_cleanup_lambda_errors,
    "cleanup_lambda_would_patch_rate": cw_log_cleanup_lambda_would_patch_rate,
    "cleanup_lambda_actual_disable_rate": cw_log_cleanup_lambda_actual_disable_rate,
    "cleanup_lambda_anomaly_reset_rate": cw_log_cleanup_lambda_anomaly_reset_rate,
    "cleanup_lambda_event_source_mapping_state": cw_lambda_cleanup_lambda_event_source_mapping_state,
    # Cost: aggregate + per-service (all share one cached CE call per run).
    "cost_total_daily": ce_total_daily,
    "cost_top_services_daily": ce_top_services_daily,
    "cost_s3_daily_total": ce_s3_daily_total,
    "cost_ec2_compute_daily": _ce_service_daily("Amazon Elastic Compute Cloud - Compute"),
    "cost_ec2_other_daily": _ce_service_daily("EC2 - Other"),
    "cost_dynamodb_daily": _ce_service_daily("Amazon DynamoDB"),
    "cost_ecs_daily": _ce_service_daily("Amazon Elastic Container Service"),
    "cost_rds_daily": _ce_service_daily("Amazon Relational Database Service"),
    "cost_vpc_daily": _ce_service_daily("Amazon Virtual Private Cloud"),
    "cost_aws_config_daily": _ce_service_daily("AWS Config"),
    "cost_cloudwatch_daily": _ce_service_daily("AmazonCloudWatch"),
    "cost_elb_daily": _ce_service_daily("Amazon Elastic Load Balancing"),
    "cost_glue_daily": _ce_service_daily("AWS Glue"),
    "cost_sqs_daily": _ce_service_daily("Amazon Simple Queue Service"),
    "cost_lambda_daily": _ce_service_daily("AWS Lambda"),
    # Cost: S3 sub-categories (one extra cached CE call).
    "cost_s3_breakdown_daily": ce_s3_breakdown_daily,
    "cost_s3_tier3_daily": ce_s3_tier3_daily,
    "cost_s3_storage_daily": ce_s3_storage_daily,
    "cost_s3_tier1_daily": ce_s3_tier1_daily,
}


# --- minipc-local collection ---------------------------------------------
#
# Signals about the host this collector is running on. Only meaningful when
# collect.py runs on the minipc itself (which it does — invoked by the
# rebuild-blog/run-dashboard-check timers). For laptop dev runs these
# signals will reflect the laptop's own systemd state — fine for testing.

def _run_local(cmd: list[str], timeout: int = 5) -> str:
    """Run a local command, return stdout (or raise)."""
    return subprocess.check_output(cmd, text=True, timeout=timeout, stderr=subprocess.DEVNULL)


def local_failed_user_units() -> int | dict:
    """Count of failed --user systemd units. Returns FACET dict if any are
    failing (so render shows WHICH ones), scalar 0 otherwise."""
    out = _run_local([
        "systemctl", "--user", "list-units", "--state=failed",
        "--no-legend", "--no-pager", "--plain"
    ])
    units = {}
    for line in out.strip().splitlines():
        # Format: <unit> <load> <active> <sub> <description>
        parts = line.split(None, 4)
        if len(parts) >= 1 and parts[0]:
            units[parts[0]] = 1
    return units if units else 0


def local_failed_system_units() -> int | dict:
    """Count of failed system-wide systemd units. Same shape as above."""
    out = _run_local([
        "sudo", "-n", "systemctl", "list-units", "--state=failed",
        "--no-legend", "--no-pager", "--plain"
    ])
    units = {}
    for line in out.strip().splitlines():
        parts = line.split(None, 4)
        if len(parts) >= 1 and parts[0]:
            units[parts[0]] = 1
    return units if units else 0


def local_unit_restart_count_24h() -> int:
    """Total times any tracked --user unit has restarted in last 24h.

    Reads journalctl for `Started` or `Failed with result` lines from the
    rebuild/dashboard-check/minipc-app timers — anything more than a couple
    is a sign the unit is flapping.
    """
    cutoff = "24 hours ago"
    units = ["minipc-app.service", "rebuild-blog.service", "rebuild-quartz.service",
             "run-dashboard-check.service", "collect-repos.service"]
    total = 0
    for u in units:
        try:
            out = _run_local(
                ["journalctl", "--user", "-u", u, "--since", cutoff, "--no-pager",
                 "--output=cat", "-q"]
            )
            # Count "Started" lines as a proxy for unit invocations
            total += sum(1 for line in out.splitlines() if "Started" in line or "Starting" in line)
        except subprocess.CalledProcessError:
            continue
    return total


def _billing_reconcile_json_path() -> Path:
    return Path.home() / ".local" / "state" / "minipc-tasks" / "billing" / f"reconciliation-{datetime.now(timezone.utc).strftime('%Y-%m')}.json"


def local_billing_production_unbilled_cams() -> int:
    """Production cameras running billable products but not in usage_monthly.
    Sourced from billing-reconcile-check.service daily JSON sink."""
    p = _billing_reconcile_json_path()
    if not p.exists():
        return 0
    data = json.loads(p.read_text())
    return int(((data.get("unbilled") or {}).get("production_missing_subscription") or {}).get("cameras") or 0)


def local_billing_reconcile_residual() -> int:
    """Reconciliation residual — non-zero indicates a counting bug or schema drift."""
    p = _billing_reconcile_json_path()
    if not p.exists():
        return 999
    data = json.loads(p.read_text())
    return int((data.get("reconciliation") or {}).get("residual") or 0)


def local_billing_reconcile_freshness() -> int:
    """Count of reconciliation JSON sinks written in the last 24h. Expected: 1."""
    sink_dir = Path.home() / ".local" / "state" / "minipc-tasks" / "billing"
    if not sink_dir.exists():
        return 0
    cutoff = time.time() - 86400
    return sum(
        1 for f in sink_dir.glob("reconciliation-*.json")
        if f.is_file() and f.stat().st_mtime >= cutoff
    )


MINIPC_LOCAL_DISPATCH: dict[str, callable] = {
    "minipc_failed_user_units": local_failed_user_units,
    "minipc_failed_system_units": local_failed_system_units,
    "minipc_unit_starts_24h": local_unit_restart_count_24h,
    "billing_production_unbilled_cams": local_billing_production_unbilled_cams,
    "billing_reconcile_residual": local_billing_reconcile_residual,
    "billing_reconcile_freshness": local_billing_reconcile_freshness,
}


# --- git-local collection ------------------------------------------------
#
# Per-repo code-health metrics. Iterates the repo list at
# ~/.config/minipc-repo-cron/repos.json (the same one git-fetch-major-repos.sh
# uses) and emits one FACET dict per signal: {repo_name: value}.
#
# Each signal-id maps to a metric function that takes a Path to the repo
# working tree and returns a scalar. The collector handles iteration + the
# missing-repo / missing-config fallthrough.

REPOS_CONFIG_PATH = Path.home() / ".config" / "minipc-repo-cron" / "repos.json"
WORK_ROOT = Path.home() / "work"

# Ensure subprocess can find user-local Python tools (radon, ruff, vulture
# installed via `uv tool install`). The cron entrypoint already exports
# this; redundant set is cheap and protects ad-hoc SSH invocations whose
# non-login shell starts with the bare-bones distro PATH.
_USER_BIN = str(Path.home() / ".local" / "bin")
if _USER_BIN not in os.environ.get("PATH", "").split(os.pathsep):
    os.environ["PATH"] = _USER_BIN + os.pathsep + os.environ.get("PATH", "")


def _load_repos_config() -> list[dict]:
    if not REPOS_CONFIG_PATH.exists():
        return []
    try:
        data = json.loads(REPOS_CONFIG_PATH.read_text())
        return data.get("repos") or []
    except (json.JSONDecodeError, OSError) as e:
        log.error("git: failed to read %s: %s", REPOS_CONFIG_PATH, e)
        return []


def repo_todo_fixme_count(repo_path: Path) -> int:
    """Count of TODO + FIXME occurrences across the repo working tree.

    Uses ripgrep's --count-matches so a single line with "TODO TODO" counts as
    2. Word-boundary anchors avoid matching TODOLIST or FIXMENT. Restricted to
    the working tree only — `--no-ignore-vcs` is intentionally NOT set, so
    .gitignore is respected.
    """
    try:
        out = subprocess.check_output(
            [
                "rg", "--count-matches", "--no-messages",
                r"\b(TODO|FIXME)\b",
                str(repo_path),
            ],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
    except subprocess.CalledProcessError as e:
        # rg exits 1 when no matches found — treat as zero.
        if e.returncode == 1:
            return 0
        raise
    total = 0
    for line in out.splitlines():
        if not line:
            continue
        # Format: <path>:<count>
        _, _, c = line.rpartition(":")
        try:
            total += int(c)
        except ValueError:
            continue
    return total


def _parse_pyproject_pin(repo_path: Path, package: str) -> str | None:
    """Extract the version-spec for `package` from pyproject.toml.

    Recognizes the common shapes:
      - PEP 621 list:  "actuate-frames==2.0.0",
      - Poetry/uv:     actuate-frames = "^2.0.0"
      - Range / extras: "actuate-frames>=2.0.0,<3"
    Returns the spec part (e.g. "==2.0.0", "~=2.0.0", ">=2.0.0,<3"), or
    None if the package isn't pinned. Workspace declarations
    (`actuate-frames = { workspace = true }`) intentionally return None —
    the workspace member doesn't pin a version.
    """
    p = repo_path / "pyproject.toml"
    if not p.exists():
        return None
    try:
        text = p.read_text()
    except OSError:
        return None
    # PEP 621 / uv list-of-strings form: "<pkg><spec>"
    pat_list = re.compile(
        rf'["\']{re.escape(package)}\s*([=<>~!][^"\',\s]+(?:\s*,\s*[=<>~!][^"\',\s]+)*)'
    )
    m = pat_list.search(text)
    if m:
        return m.group(1).strip()
    # Poetry/uv key=value: actuate-frames = "^2.0.0"
    pat_kv = re.compile(
        rf'^\s*{re.escape(package)}\s*=\s*"([^"]+)"\s*$',
        re.MULTILINE,
    )
    m = pat_kv.search(text)
    if m and "workspace" not in m.group(1):
        return m.group(1).strip()
    return None


def _parse_requirements_pin(repo_path: Path, package: str) -> str | None:
    """Extract the version-spec for `package` from requirements.txt / .in."""
    pat = re.compile(
        rf'^\s*{re.escape(package)}\s*([=<>~!][^\s#]+(?:\s*,\s*[=<>~!][^\s#]+)*)'
    )
    for fn in ("requirements.txt", "requirements.in"):
        p = repo_path / fn
        if not p.exists():
            continue
        try:
            for line in p.read_text().splitlines():
                line = line.split("#", 1)[0].strip()
                if not line:
                    continue
                m = pat.match(line)
                if m:
                    return m.group(1).strip()
        except OSError:
            continue
    return None


def _extract_actuate_pin(repo_path: Path, package: str) -> str | None:
    return (
        _parse_pyproject_pin(repo_path, package)
        or _parse_requirements_pin(repo_path, package)
    )


def repo_actuate_frames_pin(repo_path: Path) -> str | None:
    return _extract_actuate_pin(repo_path, "actuate-frames")


def repo_actuate_filters_pin(repo_path: Path) -> str | None:
    return _extract_actuate_pin(repo_path, "actuate-filters")


def repo_actuate_pullers_pin(repo_path: Path) -> str | None:
    return _extract_actuate_pin(repo_path, "actuate-pullers")


def repo_radon_cc_hotspots(repo_path: Path) -> int:
    """Count of cyclomatic-complexity hotspots (grade C+, CCN >= 11) per repo.

    `radon cc -n C` filters to grade C and worse. JSON shape is
    {filename: [block_dict, ...]}; summing inner list lengths gives the total.
    Returns 0 on tool error so a single bad signal doesn't poison the run.
    """
    proc = subprocess.run(
        ["radon", "cc", str(repo_path), "-n", "C", "-s", "--no-assert", "--json"],
        capture_output=True, text=True, timeout=120,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return 0
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return 0
    return sum(
        len(blocks) for blocks in data.values()
        if isinstance(blocks, list)
    )


def repo_ruff_unused_imports(repo_path: Path) -> int:
    """Count of F401 (unused import) violations per repo.

    `--exit-zero` means ruff returns 0 even when violations exist, so we can
    parse the JSON output cleanly. `--no-cache` because the per-repo cache
    state would skew counts when a tree is fetched fresh each hour.
    """
    proc = subprocess.run(
        [
            "ruff", "check", str(repo_path),
            "--select", "F401",
            "--output-format", "json",
            "--no-cache",
            "--exit-zero",
        ],
        capture_output=True, text=True, timeout=120,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return 0
    try:
        return len(json.loads(proc.stdout))
    except json.JSONDecodeError:
        return 0


def repo_vulture_dead_code(repo_path: Path) -> int:
    """Count of high-confidence vulture findings (likely-unused symbols).

    `--min-confidence 80` drops Django framework false-positives (Meta
    classes, model field declarations, migration ops, apps.py, enum
    members) which dominate the default 60%-confidence output:

      repo                    conf60  conf80   FPs cut
      actuate_admin            3308     41    98%
      actuate_monitoring_api    499      6    98%
      actuate-inference-api      57      2    96%
      actuate-libraries         801     45    94%
      vms-connector             191     34    82%

    The 80%-confidence bucket is a meaningfully ranked actionable
    surface; default 60% is signal-drowning noise on Django-shaped repos.

    vulture exit codes: 0=no findings, 1=findings, 2=usage error,
    3=findings + errors. Treat 0/1/3 as success; one line per finding.
    """
    proc = subprocess.run(
        ["vulture", str(repo_path), "--min-confidence", "80"],
        capture_output=True, text=True, timeout=120,
    )
    if proc.returncode not in (0, 1, 3):
        return 0
    return sum(1 for line in proc.stdout.splitlines() if line.strip())


def _resolve_github_slug(repo_path: Path) -> str | None:
    """Extract `org/repo` from the repo's git config remote.origin.url.
    Handles both SSH (git@github.com:org/repo) and HTTPS forms."""
    cfg = subprocess.run(
        ["git", "-C", str(repo_path), "config", "--get", "remote.origin.url"],
        capture_output=True, text=True, timeout=5,
    )
    if cfg.returncode != 0 or not cfg.stdout.strip():
        return None
    m = re.search(r"github\.com[:/]([^/]+/[^/.]+?)(?:\.git)?$", cfg.stdout.strip())
    return m.group(1) if m else None


def repo_stale_branches_count(repo_path: Path) -> int:
    """Count of remote branches with no commit in the last 60 days.

    Uses local git refs (no API call) — `git for-each-ref refs/remotes/origin/`
    listing each branch's last committer timestamp. The HEAD symbolic ref is
    skipped. Branches younger than 60d don't count regardless of activity.
    """
    proc = subprocess.run(
        [
            "git", "-C", str(repo_path), "for-each-ref",
            "refs/remotes/origin/",
            "--format=%(refname:short) %(committerdate:unix)",
        ],
        capture_output=True, text=True, timeout=30,
    )
    if proc.returncode != 0:
        return 0
    cutoff = int(time.time()) - 60 * 86400
    stale = 0
    for line in proc.stdout.splitlines():
        parts = line.rsplit(" ", 1)
        if len(parts) != 2:
            continue
        ref, ts = parts
        # Skip the symbolic HEAD pointer (e.g. origin/HEAD -> origin/main)
        if ref.endswith("/HEAD"):
            continue
        try:
            if int(ts) < cutoff:
                stale += 1
        except ValueError:
            continue
    return stale


def repo_open_prs_p50_age_days(repo_path: Path) -> float | None:
    """Median age (days) across currently-open PRs.

    Returns None when the repo has no open PRs — drops from the FACET dict so
    'clean' repos don't dilute the meaningful values. Pairs with
    `repo_mtm_days_p50` (merged latency) for a flow picture: high MTM + high
    open-PR-age = review bottleneck; high MTM + low open-PR-age = recent
    spike, possibly noise.
    """
    slug = _resolve_github_slug(repo_path)
    if slug is None:
        return None
    proc = subprocess.run(
        [
            "gh", "pr", "list", "--state", "open", "--limit", "50",
            "--json", "createdAt", "-R", slug,
        ],
        capture_output=True, text=True, timeout=30,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        prs = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    if not prs:
        return None
    now = datetime.now(timezone.utc)
    ages = sorted(
        (now - datetime.fromisoformat(p["createdAt"].replace("Z", "+00:00"))).total_seconds() / 86400
        for p in prs if p.get("createdAt")
    )
    if not ages:
        return None
    n = len(ages)
    median = ages[n // 2] if n % 2 else (ages[n // 2 - 1] + ages[n // 2]) / 2
    return round(median, 2)


def repo_mtm_days_p50(repo_path: Path) -> float | None:
    """Median days-to-merge across the most recent 50 merged PRs for this repo.

    Resolves the GitHub slug from the repo's git config (origin URL), then
    calls `gh pr list --state merged --limit 50 --json ...`. Skips silently
    if gh isn't auth'd or the repo has no merged PRs. Cost: 1 API call per
    repo per collect run; well under the 5000/h authenticated rate limit.
    """
    # Resolve slug from origin URL — handles both SSH (git@github.com:org/repo)
    # and HTTPS (https://github.com/org/repo[.git]) forms.
    slug = _resolve_github_slug(repo_path)
    if slug is None:
        return None
    proc = subprocess.run(
        [
            "gh", "pr", "list", "--state", "merged", "--limit", "50",
            "--json", "mergedAt,createdAt", "-R", slug,
        ],
        capture_output=True, text=True, timeout=30,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        prs = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    deltas_days = []
    for p in prs:
        merged = p.get("mergedAt")
        created = p.get("createdAt")
        if not (merged and created):
            continue
        m_dt = datetime.fromisoformat(merged.replace("Z", "+00:00"))
        c_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
        deltas_days.append((m_dt - c_dt).total_seconds() / 86400)
    if not deltas_days:
        return None
    deltas_days.sort()
    n = len(deltas_days)
    median = deltas_days[n // 2] if n % 2 else (deltas_days[n // 2 - 1] + deltas_days[n // 2]) / 2
    return round(median, 2)


def repo_ci_failure_rate_pct(repo_path: Path) -> float | None:
    """% of recent CI workflow runs ending in failure (last 50 runs).

    Conclusions counted as `fail`: failure, timed_out, startup_failure.
    Counted as `ok`: success. Skipped, cancelled, neutral, action_required,
    and in-progress (null) runs are excluded from the denominator —
    they're not signal. Returns None when there aren't enough CI runs to
    classify (denominator zero), so repos with no CI drop from the FACET.

    Day-1 distribution (2026-04-29) clustered as: most repos 0-15%,
    actuate_ailink at 38% as the obvious broken-CI outlier. Threshold
    yellow=10 catches the chronic mid-tier; red=25 catches actively
    broken pipelines.
    """
    slug = _resolve_github_slug(repo_path)
    if slug is None:
        return None
    proc = subprocess.run(
        ["gh", "run", "list", "--limit", "50", "--json", "conclusion", "-R", slug],
        capture_output=True, text=True, timeout=30,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        runs = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    fail_terms = {"failure", "timed_out", "startup_failure"}
    ok_terms = {"success"}
    considered = [r for r in runs if r.get("conclusion") in fail_terms | ok_terms]
    if not considered:
        return None
    fails = sum(1 for r in considered if r.get("conclusion") in fail_terms)
    return round(fails / len(considered) * 100, 1)


def autopatrol_onboarder_healthcheck_hotfix(repo_path: Path) -> int | None:
    """Boolean — is the 2026-04-23 healthcheck hotfix still in effect?

    Reverting it (a `return` in the failure branch of `get_healthcheck()`)
    recreates the silent early-return incident. Returns 1 if the failure
    branch logs a warning AND has no `return`, 0 otherwise. Returns None
    only if the source file is missing.
    """
    src = repo_path / "lambda_function.py"
    if not src.exists():
        return None
    lines = src.read_text().splitlines()
    call_idx = next(
        (i for i, line in enumerate(lines) if "get_healthcheck()" in line),
        None,
    )
    if call_idx is None:
        return 0
    if_idx = call_idx + 1
    if if_idx >= len(lines) or "if " not in lines[if_idx]:
        return 0
    if_indent = len(lines[if_idx]) - len(lines[if_idx].lstrip())
    body: list[str] = []
    for j in range(if_idx + 1, len(lines)):
        stripped = lines[j].lstrip()
        if not stripped:
            continue
        if len(lines[j]) - len(stripped) <= if_indent:
            break
        body.append(lines[j])
    block = "\n".join(body)
    has_warning = "logging.warning(" in block or "log.warning(" in block
    has_return = bool(re.search(r"^\s+return\b", block, re.M))
    return 1 if (has_warning and not has_return) else 0


GIT_LOCAL_DISPATCH: dict[str, callable] = {
    "repo_todo_fixme_count": repo_todo_fixme_count,
    "repo_actuate_frames_pin": repo_actuate_frames_pin,
    "repo_actuate_filters_pin": repo_actuate_filters_pin,
    "repo_actuate_pullers_pin": repo_actuate_pullers_pin,
    "repo_radon_cc_hotspots": repo_radon_cc_hotspots,
    "repo_ruff_unused_imports": repo_ruff_unused_imports,
    "repo_vulture_dead_code": repo_vulture_dead_code,
    "repo_mtm_days_p50": repo_mtm_days_p50,
    "repo_stale_branches_count": repo_stale_branches_count,
    "repo_open_prs_p50_age_days": repo_open_prs_p50_age_days,
    "repo_ci_failure_rate_pct": repo_ci_failure_rate_pct,
    "onboarder_healthcheck_hotfix_in_effect": autopatrol_onboarder_healthcheck_hotfix,
}


def collect_git_local_signals(signals: list[dict]) -> dict:
    """Run each git_local signal across the configured repo set.

    Each signal returns a FACET dict {repo_name: value}. Missing repos on
    disk are skipped silently (the cron timer keeps the clones in sync; a
    transient gap shouldn't fail the signal). If repos.json is missing
    entirely (laptop dev path), all git_local signals are skipped with a
    warning.
    """
    repos = _load_repos_config()
    out: dict = {}
    if not repos:
        for sig in signals:
            sid = sig["id"]
            log.warning("skip %s: %s missing or empty (not on minipc?)",
                        sid, REPOS_CONFIG_PATH)
            out[sid] = None
        return out

    for sig in signals:
        sid = sig["id"]
        fn = GIT_LOCAL_DISPATCH.get(sid)
        if fn is None:
            log.warning("skip %s: no git_local dispatcher", sid)
            out[sid] = None
            continue
        repo_filter = sig.get("repos") or ["all"]
        targets = repos if repo_filter == ["all"] else [
            r for r in repos if r["name"] in repo_filter
        ]
        facet: dict = {}
        for r in targets:
            name = r["name"]
            path = WORK_ROOT / name
            if not path.exists():
                log.debug("git: skip %s/%s (no working tree)", sid, name)
                continue
            try:
                value = fn(path)
            except Exception as e:
                log.error("git %-40s %s FAILED: %s", sid, name, e)
                facet[name] = None
                continue
            # None means "not applicable to this repo" (e.g. package not pinned).
            # Drop the entry so the FACET dict only shows repos with real data.
            if value is None:
                continue
            facet[name] = value
        out[sid] = facet
        log.info("git %-40s = %s", sid, _short(facet))
    return out


# --- tls-cert collection -------------------------------------------------
#
# External-endpoint TLS cert expiry. Each signal's `hosts: [...]` field
# lists fully-qualified DNS names; the collector connects to each on port
# 443, parses the cert, and emits a FACET dict {host: days_until_expiry}.
# Pure stdlib — no new deps.

def _tls_cert_days_until_expiry(host: str, port: int = 443, timeout: int = 10) -> int | None:
    import ssl
    import socket
    ctx = ssl.create_default_context()
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                cert = ssock.getpeercert()
    except (socket.gaierror, socket.timeout, ConnectionRefusedError, ssl.SSLError, OSError):
        return None
    if not cert or "notAfter" not in cert:
        return None
    # Cert format: "Aug 18 23:59:59 2026 GMT"
    try:
        not_after = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return (not_after - datetime.now(timezone.utc)).days


def collect_tls_cert_signals(signals: list[dict]) -> dict:
    out: dict = {}
    for sig in signals:
        sid = sig["id"]
        hosts = sig.get("hosts") or []
        if not hosts:
            log.warning("skip %s: no `hosts` list", sid)
            out[sid] = None
            continue
        facet: dict = {}
        for host in hosts:
            days = _tls_cert_days_until_expiry(host)
            if days is None:
                log.error("tls %s: failed to fetch cert", host)
                facet[host] = None
                continue
            facet[host] = days
        out[sid] = facet
        log.info("tls %-40s = %s", sid, _short(facet))
    return out


def collect_minipc_local_signals(signals: list[dict]) -> dict:
    out: dict = {}
    for sig in signals:
        sid = sig["id"]
        fn = MINIPC_LOCAL_DISPATCH.get(sid)
        if fn is None:
            log.warning("skip %s: no minipc_local dispatcher", sid)
            continue
        try:
            value = fn()
            log.info("loc %-40s = %s", sid, _short(value))
        except Exception as e:
            log.error("loc %-40s FAILED: %s", sid, e)
            value = None
        out[sid] = value
    return out


def collect_aws_signals(signals: list[dict], profile: str) -> tuple[dict, dict]:
    """Returns (cw_results, ce_results). cw_results combines cw_log + cw_metric."""
    cw: dict = {}
    ce: dict = {}
    for sig in signals:
        sid = sig["id"]
        src = sig["source"]
        fn = AWS_DISPATCH.get(sid)
        if fn is None:
            log.warning("skip %s: no AWS dispatcher for source=%s", sid, src)
            continue
        try:
            value = fn(profile)
            log.info("aws %-40s = %s", sid, _short(value))
        except Exception as e:
            log.error("aws %-40s FAILED: %s", sid, e)
            value = None
        if src == "ce_daily":
            ce[sid] = value
        else:
            cw[sid] = value
    return cw, ce


# --- main -----------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tempdir", required=True, type=Path)
    ap.add_argument("--aws-profile", default=os.environ.get("AWS_PROFILE", "dashboard-check"))
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="[%(asctime)s] %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    args.tempdir.mkdir(parents=True, exist_ok=True)

    catalog = json.loads((CONFIG_DIR / "signals.json").read_text())
    enabled = [s for s in catalog["signals"] if s.get("enabled")]
    nr_signals = [s for s in enabled if s["source"].startswith("nr_")]
    aws_signals = [s for s in enabled if s["source"].startswith(("cw_", "ce_"))]
    local_signals = [s for s in enabled if s["source"] == "minipc_local"]
    git_signals = [s for s in enabled if s["source"] == "git_local"]
    tls_signals = [s for s in enabled if s["source"] == "tls_cert"]
    log.info("collecting %d NR + %d AWS + %d local + %d git + %d tls signals (catalog: %d enabled / %d total)",
             len(nr_signals), len(aws_signals), len(local_signals), len(git_signals), len(tls_signals),
             len(enabled), len(catalog["signals"]))

    nr_out = collect_nr_signals(nr_signals)
    cw_out, ce_out = collect_aws_signals(aws_signals, args.aws_profile)
    local_out = collect_minipc_local_signals(local_signals)
    git_out = collect_git_local_signals(git_signals)
    tls_out = collect_tls_cert_signals(tls_signals)

    (args.tempdir / "nr_results.json").write_text(json.dumps(nr_out, indent=2))
    (args.tempdir / "cw_results.json").write_text(json.dumps(cw_out, indent=2))
    (args.tempdir / "ce_results.json").write_text(json.dumps(ce_out, indent=2))
    (args.tempdir / "local_results.json").write_text(json.dumps(local_out, indent=2))
    (args.tempdir / "git_results.json").write_text(json.dumps(git_out, indent=2))
    (args.tempdir / "tls_results.json").write_text(json.dumps(tls_out, indent=2))

    all_obs = {**nr_out, **cw_out, **ce_out, **local_out, **git_out, **tls_out}
    n_total = len(all_obs)
    n_failed = sum(1 for v in all_obs.values() if v is None)
    log.info("wrote %d signals to %s (%d failed)", n_total, args.tempdir, n_failed)
    return 0 if n_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
