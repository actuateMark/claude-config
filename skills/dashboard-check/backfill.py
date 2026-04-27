"""Sink backfill tool.

Takes a source result (from NRQL, CloudWatch Metrics, CloudWatch Insights, or
Cost Explorer), normalizes it into (timestamp, value) pairs, classifies each
bucket against the signal's thresholds, and writes sink records with
`source_skill="backfill"` + `extras.backfilled=True`.

Idempotent: before writing, checks the existing sink for a record with the
same (signal_id, timestamp) at minute-precision. Re-running the same backfill
is a no-op.

Usage (reads result JSON on stdin, signal_id as arg):

    # NRQL result from mcp__newrelic__execute_nrql_query
    <nrql-result.json backfill.py --signal <id> --source nrql [--dry-run]

    # CloudWatch Metrics get-metric-statistics output
    aws cloudwatch get-metric-statistics ... | backfill.py --signal <id> --source cw_metric

    # CloudWatch Insights get-query-results output
    aws logs get-query-results ... | backfill.py --signal <id> --source cw_insights

    # Cost Explorer get-cost-and-usage output
    aws ce get-cost-and-usage ... | backfill.py --signal <id> --source ce_daily

Design decisions:
  - Supports 4 source formats to avoid per-signal handler registry; if a new
    format is needed, add an adapter function here.
  - Minute-precision dedupe is coarse enough to catch duplicate runs, fine
    enough not to collapse legitimately-adjacent datapoints.
  - `classify()` is imported from render.py so backfilled rows get the same
    status classification as live ones.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SKILL_DIR))
import sink  # noqa: E402
import render  # noqa: E402


def _existing_keys(signal_id: str) -> set[str]:
    """Return set of 'YYYY-MM-DDTHH:MM' strings already present for this signal."""
    keys: set[str] = set()
    for rec in sink.read_all():
        if rec.get("signal_id") != signal_id:
            continue
        ts = rec.get("timestamp", "")
        if ts:
            # Trim seconds to minute-precision for dedupe
            keys.add(ts[:16])
    return keys


def _classify(signal: dict, value) -> str:
    baseline = None
    return render.classify(signal, value, baseline)


# --- Source adapters: each returns list[(datetime, value)] ---

def adapt_nrql(payload: dict) -> list[tuple[datetime, float]]:
    """Accepts either {results: [{beginTimeSeconds, endTimeSeconds, ...values}, ...]}
    from NRDB.TimeseriesResult, or the raw MCP response wrapping it.
    """
    # NRDB TIMESERIES: payload may have 'timeSeries' or 'results' key, sometimes nested
    rows = None
    for key in ("timeSeries", "results"):
        if isinstance(payload.get(key), list):
            rows = payload[key]
            break
    if rows is None and isinstance(payload.get("data"), dict):
        # MCP response sometimes nests under data.actor.account.nrql.results
        try:
            rows = payload["data"]["actor"]["account"]["nrql"]["results"]
        except (KeyError, TypeError):
            rows = None
    if rows is None:
        raise ValueError("NRQL payload has no recognizable results array")

    out: list[tuple[datetime, float]] = []
    for row in rows:
        ts_s = row.get("beginTimeSeconds") or row.get("timestamp")
        if ts_s is None:
            continue
        # Extract the numeric value — first non-timestamp numeric field
        val = None
        for k, v in row.items():
            if k in ("beginTimeSeconds", "endTimeSeconds", "timestamp", "inspectedCount",
                     "beginTime", "endTime"):
                continue
            if isinstance(v, (int, float)):
                val = v
                break
        if val is None:
            continue
        ts = datetime.fromtimestamp(int(ts_s), tz=timezone.utc)
        out.append((ts, float(val)))
    return out


def adapt_cw_metric(payload: dict) -> list[tuple[datetime, float]]:
    """CloudWatch get-metric-statistics response: {Datapoints: [{Timestamp, Sum|Average|...}]}."""
    dps = payload.get("Datapoints", [])
    out: list[tuple[datetime, float]] = []
    for dp in dps:
        ts = dp.get("Timestamp")
        if not ts:
            continue
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        elif isinstance(ts, (int, float)):
            ts = datetime.fromtimestamp(ts, tz=timezone.utc)
        # Pick first numeric stat (Sum, Average, Maximum, Minimum, SampleCount)
        val = None
        for k in ("Sum", "Average", "Maximum", "Minimum", "SampleCount"):
            if k in dp:
                val = dp[k]
                break
        if val is None:
            continue
        out.append((ts, float(val)))
    out.sort(key=lambda x: x[0])
    return out


def adapt_cw_insights(payload: dict) -> list[tuple[datetime, float]]:
    """CloudWatch Insights get-query-results response: {results: [[{field,value},...]]}.

    Expects the Insights query to have `stats count() by bin(...)` or similar,
    producing a two-field result per row: the bin timestamp and a count.
    """
    results = payload.get("results", [])
    out: list[tuple[datetime, float]] = []
    for row in results:
        ts = None
        val = None
        for cell in row:
            field = cell.get("field", "")
            value = cell.get("value", "")
            if field in ("@timestamp", "bin", "bin_time"):
                try:
                    # "2026-04-23 10:00:00.000" OR ISO
                    ts = datetime.fromisoformat(value.replace(" ", "T"))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
            elif field in ("count", "count()", "cnt"):
                try:
                    val = float(value)
                except (TypeError, ValueError):
                    continue
        if ts is not None and val is not None:
            out.append((ts, val))
    out.sort(key=lambda x: x[0])
    return out


def adapt_ce_daily(payload: dict) -> list[tuple[datetime, float]]:
    """Cost Explorer get-cost-and-usage: {ResultsByTime: [{TimePeriod: {Start, End}, Total/Groups}]}."""
    rows = payload.get("ResultsByTime", [])
    out: list[tuple[datetime, float]] = []
    for row in rows:
        start = row.get("TimePeriod", {}).get("Start")
        if not start:
            continue
        try:
            ts = datetime.fromisoformat(start + "T00:00:00+00:00")
        except ValueError:
            continue
        total = row.get("Total", {})
        val = None
        for metric_name, metric in total.items():
            amt = metric.get("Amount")
            if amt is not None:
                try:
                    val = float(amt)
                    break
                except ValueError:
                    continue
        if val is None:
            continue
        out.append((ts, val))
    out.sort(key=lambda x: x[0])
    return out


SOURCE_ADAPTERS = {
    "nrql": adapt_nrql,
    "cw_metric": adapt_cw_metric,
    "cw_insights": adapt_cw_insights,
    "ce_daily": adapt_ce_daily,
}


def ingest(
    signal_id: str,
    source: str,
    payload: dict,
    *,
    dry_run: bool = False,
) -> dict:
    """Ingest a source payload for a signal. Returns stats dict."""
    signals = {s["id"]: s for s in render.load_signals()}
    signal = signals.get(signal_id)
    if signal is None:
        return {"error": f"signal_id '{signal_id}' not found in catalog"}

    adapter = SOURCE_ADAPTERS.get(source)
    if adapter is None:
        return {"error": f"unknown source '{source}'; choose from {list(SOURCE_ADAPTERS)}"}

    try:
        points = adapter(payload)
    except (KeyError, ValueError, TypeError) as e:
        return {"error": f"adapter failed: {e}"}

    existing = _existing_keys(signal_id)
    component = signal["component"]
    unit = signal.get("unit")
    written = 0
    skipped_dup = 0
    skipped_invalid = 0

    for ts, val in points:
        key = ts.strftime("%Y-%m-%dT%H:%M")
        if key in existing:
            skipped_dup += 1
            continue
        status = _classify(signal, val)
        if status == "error":
            skipped_invalid += 1
            continue
        if dry_run:
            written += 1
            continue
        ok = sink.write_observation(
            component=component,
            signal_id=signal_id,
            value=val,
            status=status,
            source_skill="backfill",
            unit=unit,
            baseline=None,
            notes="backfilled",
            extras={"backfilled": True, "source": source},
            timestamp=ts,
        )
        if ok:
            written += 1
            existing.add(key)

    return {
        "signal_id": signal_id,
        "source": source,
        "points_parsed": len(points),
        "written": written,
        "skipped_duplicate": skipped_dup,
        "skipped_invalid": skipped_invalid,
        "dry_run": dry_run,
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--signal", required=True, help="signal_id in signals.json")
    p.add_argument("--source", required=True, choices=sorted(SOURCE_ADAPTERS))
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--stdin-file", help="Read JSON from this path instead of stdin")
    args = p.parse_args()

    if args.stdin_file:
        raw = Path(args.stdin_file).read_text()
    else:
        raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"invalid JSON: {e}"}), file=sys.stderr)
        return 2

    result = ingest(args.signal, args.source, payload, dry_run=args.dry_run)
    print(json.dumps(result, indent=2))
    return 0 if "error" not in result else 1


if __name__ == "__main__":
    sys.exit(main())
