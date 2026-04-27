"""Sink helper for the operational dashboard.

Append-only JSONL at ~/Documents/worklog/dashboard/sink/observations.jsonl. Any
skill that makes an operational observation should write one record here.

Public surface:
    write_observation(...) -> bool
    read_recent(since_hours, component=None, signal_id=None, source_skill=None) -> list[dict]

Schema is documented in sink/.schema.md alongside the data file.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

SINK_PATH = Path.home() / "Documents" / "worklog" / "dashboard" / "sink" / "observations.jsonl"

VALID_STATUSES = {"green", "yellow", "red", "informational", "error"}


def _ensure_sink_exists() -> None:
    SINK_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not SINK_PATH.exists():
        SINK_PATH.touch()


def write_observation(
    component: str,
    signal_id: str,
    value: Any,
    status: str,
    source_skill: str,
    *,
    unit: str | None = None,
    baseline: float | None = None,
    notes: str | None = None,
    extras: dict | None = None,
    timestamp: datetime | None = None,
) -> bool:
    """Append one observation to the sink.

    Returns True on success, False on validation failure. Never raises.
    """
    if status not in VALID_STATUSES:
        return False
    if not component or not signal_id or not source_skill:
        return False

    ts = timestamp or datetime.now(timezone.utc)
    record: dict[str, Any] = {
        "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_skill": source_skill,
        "component": component,
        "signal_id": signal_id,
        "value": value,
        "status": status,
    }
    if unit is not None:
        record["unit"] = unit
    if baseline is not None:
        record["baseline"] = baseline
    if notes is not None:
        record["notes"] = notes
    if extras is not None:
        record["extras"] = extras

    try:
        _ensure_sink_exists()
        with open(SINK_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return True
    except OSError:
        return False


def read_recent(
    since_hours: float = 24,
    *,
    component: str | None = None,
    signal_id: str | None = None,
    source_skill: str | None = None,
) -> list[dict]:
    """Read observations from the last `since_hours` hours, optionally filtered.

    Malformed lines are skipped silently. Returns newest-last.
    """
    if not SINK_PATH.exists():
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    out: list[dict] = []
    with open(SINK_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            try:
                ts = datetime.strptime(rec["timestamp"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            except (KeyError, ValueError):
                continue
            if ts < cutoff:
                continue
            if component and rec.get("component") != component:
                continue
            if signal_id and rec.get("signal_id") != signal_id:
                continue
            if source_skill and rec.get("source_skill") != source_skill:
                continue
            out.append(rec)
    return out


def read_all() -> Iterable[dict]:
    """Generator over every record in the sink. Skips malformed lines."""
    if not SINK_PATH.exists():
        return
    with open(SINK_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


if __name__ == "__main__":
    # CLI shim: `python3 sink.py write <json_record>` or `python3 sink.py recent <hours>`.
    import sys

    argv = sys.argv[1:]
    if not argv:
        print("usage: sink.py {write '<json>' | recent <hours>}", file=sys.stderr)
        sys.exit(1)
    cmd = argv[0]
    if cmd == "write" and len(argv) >= 2:
        rec = json.loads(argv[1])
        ok = write_observation(
            component=rec["component"],
            signal_id=rec["signal_id"],
            value=rec["value"],
            status=rec["status"],
            source_skill=rec["source_skill"],
            unit=rec.get("unit"),
            baseline=rec.get("baseline"),
            notes=rec.get("notes"),
            extras=rec.get("extras"),
        )
        sys.exit(0 if ok else 1)
    elif cmd == "recent":
        hours = float(argv[1]) if len(argv) >= 2 else 24
        for rec in read_recent(hours):
            print(json.dumps(rec))
        sys.exit(0)
    else:
        print(f"unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)
