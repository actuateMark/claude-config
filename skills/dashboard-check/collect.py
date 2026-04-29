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


def ce_s3_daily_total(profile: str) -> float:
    """`cost_s3_daily_total` — yesterday's S3 UnblendedCost, USD."""
    s = _boto_session(profile)
    client = s.client("ce", region_name="us-east-1")  # CE only lives in us-east-1
    end = datetime.now(timezone.utc).date()
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
    )
    rows = resp.get("ResultsByTime", [])
    if not rows:
        return 0.0
    return float(rows[0]["Total"]["UnblendedCost"]["Amount"])


AWS_DISPATCH: dict[str, callable] = {
    "onboarder_activity_us": cw_log_onboarder_activity_us,
    "onboarder_lambda_invocations_us": cw_metric_onboarder_invocations_us,
    "cost_s3_daily_total": ce_s3_daily_total,
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


MINIPC_LOCAL_DISPATCH: dict[str, callable] = {
    "minipc_failed_user_units": local_failed_user_units,
    "minipc_failed_system_units": local_failed_system_units,
    "minipc_unit_starts_24h": local_unit_restart_count_24h,
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


GIT_LOCAL_DISPATCH: dict[str, callable] = {
    "repo_todo_fixme_count": repo_todo_fixme_count,
    "repo_actuate_frames_pin": repo_actuate_frames_pin,
    "repo_actuate_filters_pin": repo_actuate_filters_pin,
    "repo_actuate_pullers_pin": repo_actuate_pullers_pin,
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
    log.info("collecting %d NR + %d AWS + %d local + %d git signals (catalog: %d enabled / %d total)",
             len(nr_signals), len(aws_signals), len(local_signals), len(git_signals),
             len(enabled), len(catalog["signals"]))

    nr_out = collect_nr_signals(nr_signals)
    cw_out, ce_out = collect_aws_signals(aws_signals, args.aws_profile)
    local_out = collect_minipc_local_signals(local_signals)
    git_out = collect_git_local_signals(git_signals)

    (args.tempdir / "nr_results.json").write_text(json.dumps(nr_out, indent=2))
    (args.tempdir / "cw_results.json").write_text(json.dumps(cw_out, indent=2))
    (args.tempdir / "ce_results.json").write_text(json.dumps(ce_out, indent=2))
    (args.tempdir / "local_results.json").write_text(json.dumps(local_out, indent=2))
    (args.tempdir / "git_results.json").write_text(json.dumps(git_out, indent=2))

    all_obs = {**nr_out, **cw_out, **ce_out, **local_out, **git_out}
    n_total = len(all_obs)
    n_failed = sum(1 for v in all_obs.values() if v is None)
    log.info("wrote %d signals to %s (%d failed)", n_total, args.tempdir, n_failed)
    return 0 if n_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
