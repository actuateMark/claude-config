"""Render the operational dashboard from collected observations + signal catalog.

Usage:
  render.py --tempdir <dir> --output-root <dir> --snapshot-date <YYYY-MM-DD>

Reads:
  - config/signals.json + config/baselines.json (in this skill's dir)
  - <tempdir>/cw_results.json, nr_results.json, gh_results.json, ce_results.json,
    local_results.json, git_results.json (any subset; missing files are treated as empty)
  - prior-day snapshot at <output-root>/<prior-date>/data.json (for regression rules)
  - sink observations.jsonl (for the Morning summary section)

Writes:
  - <output-root>/<date>/data.json
  - <output-root>/<date>/index.html
  - <output-root>/<date>/components/<component>.html
  - <output-root>/<date>/regressions.html
  - <output-root>/latest symlink -> <date>
  - one sink record per evaluated signal (via sink.py)

Returns exit code: 0 (all green), 1 (any yellow), 2 (any red).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SKILL_DIR = Path(__file__).resolve().parent
CONFIG_DIR = SKILL_DIR / "config"
RENDER_DIR = SKILL_DIR / "render"
CSS_DIR = SKILL_DIR / "css"

# Lazy imports - jinja2 only needed when rendering
try:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
except ImportError:
    Environment = None  # handled in render step

sys.path.insert(0, str(SKILL_DIR))
import sink  # noqa: E402

STATUS_RANK = {"green": 0, "informational": 0, "yellow": 1, "red": 2, "error": 2}
STATUS_TO_EXIT = {0: 0, 1: 1, 2: 2}


@dataclass
class Evaluation:
    signal_id: str
    component: str
    value: Any
    baseline: float | None
    status: str
    unit: str | None = None
    description: str = ""
    notes: str = ""
    regressions: list[str] = field(default_factory=list)
    thresholds: dict | None = None
    paired_with: str | None = None
    query: str | None = None
    kb_link: str | None = None
    source: str | None = None
    would_have_caught: str | None = None
    # Best-source-at-render-time metadata:
    data_source: str = "live"               # "live" | "sink_recent" | "sink_stale" | "none"
    last_observed_at: str | None = None     # ISO timestamp of the value being rendered
    history: list[dict] = field(default_factory=list)  # trailing sink rows for sparklines
    freshness_hours: float | None = None    # hours since last observation
    # Today vs prior — for drawer diff rendering
    prior_value: Any = None                 # most recent prior-day snapshot's value for this signal


def load_signals() -> list[dict]:
    data = json.loads((CONFIG_DIR / "signals.json").read_text())
    return data["signals"]


def load_baselines() -> dict[str, float]:
    data = json.loads((CONFIG_DIR / "baselines.json").read_text())
    return data["baselines"]


def merge_results(tempdir: Path) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for name in ("cw_results.json", "nr_results.json", "gh_results.json", "ce_results.json", "local_results.json", "git_results.json", "tls_results.json"):
        path = tempdir / name
        if path.exists():
            try:
                merged.update(json.loads(path.read_text()))
            except (OSError, json.JSONDecodeError):
                continue
    return merged


def load_prior_snapshot(output_root: Path, current_date: str) -> dict[str, Any]:
    """Find the most recent prior-day snapshot's data.json for regression comparison."""
    current_dt = datetime.strptime(current_date, "%Y-%m-%d")
    for days_back in range(1, 8):
        candidate_date = (current_dt - timedelta(days=days_back)).strftime("%Y-%m-%d")
        candidate = output_root / candidate_date / "data.json"
        if candidate.exists():
            try:
                return json.loads(candidate.read_text())
            except (OSError, json.JSONDecodeError):
                continue
    return {}


def classify(signal: dict, value: Any, baseline: float | None) -> str:
    """Green/yellow/red per signal's thresholds. Returns 'informational' if no thresholds + no value.

    For FACET dict values (e.g. {repo: count}), apply thresholds to each
    numeric value and return the worst classification across keys. This is
    what makes per-repo code-health regressions surface in the dashboard
    summary line, not only in the leaderboard.
    """
    if value is None:
        return "error"
    thresholds = signal.get("thresholds")
    if not thresholds:
        return "informational"

    if isinstance(value, dict):
        worst = "green"
        any_numeric = False
        for v in value.values():
            try:
                num = float(v)
            except (TypeError, ValueError):
                continue
            any_numeric = True
            sub = _classify_numeric(thresholds, num)
            if STATUS_RANK[sub] > STATUS_RANK[worst]:
                worst = sub
        return worst if any_numeric else "informational"

    try:
        num = float(value)
    except (TypeError, ValueError):
        return "informational"

    return _classify_numeric(thresholds, num)


def _classify_numeric(thresholds: dict, num: float) -> str:
    if "red_above" in thresholds and num > thresholds["red_above"]:
        return "red"
    if "yellow_above" in thresholds and num > thresholds["yellow_above"]:
        return "yellow"
    if "red_below" in thresholds and num < thresholds["red_below"]:
        return "red"
    if "yellow_below" in thresholds and num < thresholds["yellow_below"]:
        return "yellow"
    return "green"


def apply_regression_rules(
    signal: dict, value: Any, prior_value: Any, observations: dict[str, Any]
) -> tuple[list[str], str | None]:
    """Returns (regressions_triggered, elevated_status) — elevated_status is the
    highest-severity status implied by any regression rule; caller merges with
    the base classification.
    """
    rules = signal.get("regression_rules", [])
    triggered: list[str] = []
    elevated: str | None = None

    def bump(to: str) -> None:
        nonlocal elevated
        if elevated is None or STATUS_RANK[to] > STATUS_RANK[elevated]:
            elevated = to

    # Rule 1: silent drop
    if "silent_drop" in rules:
        try:
            v = float(value)
            p = float(prior_value)
            if p > 1 and v < 0.1 * p:
                triggered.append("silent_drop")
                bump("red")
        except (TypeError, ValueError):
            pass

    # Rule 5: activity-marker anti-pattern (paired signals)
    if "activity_marker_antipattern" in rules and signal.get("pair_with"):
        pair_id = signal["pair_with"]
        pair_val = observations.get(pair_id)
        try:
            act = float(value)
            inv = float(pair_val)
            if inv > 10 and act < 0.1 * inv:
                triggered.append("activity_marker_antipattern")
                bump("red")
        except (TypeError, ValueError):
            pass

    # Rule 2: new pattern in top-N facet. Require BOTH today and prior to be dicts —
    # otherwise a first-ever facet render (when prior is scalar / missing) would flag
    # every key as "new" and produce a false-positive yellow/red.
    if "new_pattern" in rules and isinstance(value, dict) and isinstance(prior_value, dict):
        today_keys = set(value.keys())
        prior_keys = set(prior_value.keys())
        new_keys = today_keys - prior_keys
        if new_keys:
            triggered.append(f"new_pattern:{','.join(sorted(new_keys))}")
            bump("red" if signal.get("critical") else "yellow")

    return triggered, elevated


def _latest_sink_observation(signal_id: str, window_hours: float) -> tuple[dict | None, list[dict]]:
    """Return (latest_row, trailing_window) for a signal from the sink.

    latest_row: the most recent non-current-run sink entry for this signal (any age),
                or None if the sink has nothing for this signal.
    trailing_window: all sink rows for this signal in the last `window_hours` hours,
                     oldest-first. Used by sparklines and trend context.
    """
    all_rows = sink.read_recent(since_hours=window_hours, signal_id=signal_id)
    trailing = [r for r in all_rows if r.get("source_skill") != "dashboard-check"]
    trailing.sort(key=lambda r: r.get("timestamp", ""))

    # For the "latest" entry, look across the full sink (no window), not just trailing,
    # so we can still classify a signal as sink_stale rather than none. Include
    # dashboard-check rows: they are this skill's own prior-run history, which is
    # exactly what we want for graceful-failure fallback. write_sink_records runs
    # AFTER evaluate_signals, so there is no current-run row to skip here.
    latest_any: dict | None = None
    for r in sink.read_all():
        if r.get("signal_id") != signal_id:
            continue
        # Skip rows where the prior write itself was a failure marker; we want
        # to fall back to the last known-good value, not a previous error state.
        if r.get("value") is None or r.get("status") == "error":
            continue
        ts = r.get("timestamp", "")
        if latest_any is None or ts > latest_any.get("timestamp", ""):
            latest_any = r
    return latest_any, trailing


def _freshness_hours(ts_iso: str | None) -> float | None:
    if not ts_iso:
        return None
    try:
        ts = datetime.strptime(ts_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None
    return (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0


def evaluate_signals(
    signals: list[dict],
    baselines: dict[str, float],
    observations: dict[str, Any],
    prior_observations: dict[str, Any],
) -> list[Evaluation]:
    """Evaluate every enabled signal using best-source-at-render-time.

    Priority order per signal:
      1. Live observation from current run's tempdir → data_source='live'
      2. Sink entry within freshness window (window_hours × 2 by default) → 'sink_recent'
      3. Sink entry exists but older than window → 'sink_stale' (status=informational)
      4. Nothing → 'none' (status=error)

    Trailing sink history (window_hours × 7 days-worth, capped) is attached to `history`
    regardless of data_source, so sparklines read uniformly.
    """
    out = []
    for sig in signals:
        if not sig.get("enabled", False):
            continue
        sid = sig["id"]
        live_value = observations.get(sid)
        baseline = baselines.get(sid)
        window_h = float(sig.get("window_hours") or 1)
        freshness_threshold_h = float(sig.get("freshness_threshold_hours") or window_h * 2)
        # Always attach a 7-day trailing window for context/history rendering.
        _, trailing_7d = _latest_sink_observation(sid, window_hours=24 * 7)

        if live_value is not None:
            value = live_value
            data_source = "live"
            last_obs_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            freshness = 0.0
            status = classify(sig, value, baseline)
            notes = ""
        else:
            latest_sink, _ = _latest_sink_observation(sid, window_hours=24 * 365)  # any age
            if latest_sink is None:
                value = None
                data_source = "none"
                last_obs_at = None
                freshness = None
                status = "error"
                notes = "no observation collected; no sink history"
            else:
                value = latest_sink.get("value")
                last_obs_at = latest_sink.get("timestamp")
                freshness = _freshness_hours(last_obs_at)
                if freshness is not None and freshness <= freshness_threshold_h:
                    data_source = "sink_recent"
                    status = classify(sig, value, baseline)
                    notes = f"from sink ({freshness:.1f}h old)"
                else:
                    data_source = "sink_stale"
                    status = "informational"
                    notes = f"stale (from sink, {freshness:.1f}h old; threshold {freshness_threshold_h:.0f}h)"

        prior_value = prior_observations.get(sid)
        regressions, elevated = apply_regression_rules(sig, value, prior_value, observations)
        if elevated and STATUS_RANK[elevated] > STATUS_RANK[status]:
            status = elevated

        ev = Evaluation(
            signal_id=sid,
            component=sig["component"],
            value=value,
            baseline=baseline,
            status=status,
            unit=sig.get("unit"),
            description=sig.get("description", ""),
            notes=notes,
            regressions=regressions,
            thresholds=sig.get("thresholds"),
            paired_with=sig.get("pair_with"),
            query=sig.get("query"),
            kb_link=sig.get("kb_link"),
            source=sig.get("source"),
            would_have_caught=sig.get("would_have_caught"),
            data_source=data_source,
            last_observed_at=last_obs_at,
            history=trailing_7d,
            freshness_hours=freshness,
            prior_value=prior_value,
        )
        out.append(ev)
    return out


def write_sink_records(evaluations: list[Evaluation]) -> None:
    for ev in evaluations:
        sink.write_observation(
            component=ev.component,
            signal_id=ev.signal_id,
            value=ev.value,
            status=ev.status,
            source_skill="dashboard-check",
            unit=ev.unit,
            baseline=ev.baseline,
            notes=ev.notes or (", ".join(ev.regressions) if ev.regressions else None),
            extras={"description": ev.description} if ev.description else None,
        )


def overall_status(evaluations: list[Evaluation]) -> str:
    if not evaluations:
        return "informational"
    worst_rank = max(STATUS_RANK.get(ev.status, 0) for ev in evaluations)
    for status, rank in STATUS_RANK.items():
        if rank == worst_rank:
            return status
    return "informational"


def build_trend_data(evaluations: list[Evaluation], window_hours: float = 24 * 7) -> list[dict]:
    """For each evaluation with >=3 numeric data points in the trailing window,
    produce a dict of pre-computed SVG chart data the template renders inline.

    Reads the sink directly (including dashboard-check's own rows) so every cron
    tick contributes a data point. This is intentionally different from
    Evaluation.history — sparklines exclude dashboard-check rows to avoid
    self-tailing, but trend charts WANT every tick.

    Skips facet-dict signals — those already have a tabular breakdown drawer.
    """
    W, H = 480, 140
    L, R, T, B = 40, 10, 10, 26
    plot_w = W - L - R
    plot_h = H - T - B

    # Pull all rows in the window once; bucket by signal_id for O(N) walks.
    all_recent = sink.read_recent(since_hours=window_hours)
    by_sig: dict[str, list[dict]] = {}
    for r in all_recent:
        sid = r.get("signal_id")
        if sid:
            by_sig.setdefault(sid, []).append(r)

    out: list[dict] = []
    for ev in evaluations:
        if isinstance(ev.value, dict):
            continue
        points: list[tuple[float, float]] = []
        for r in by_sig.get(ev.signal_id, []):
            v = r.get("value")
            if not isinstance(v, (int, float)):
                continue
            ts = r.get("timestamp")
            if not ts:
                continue
            try:
                t = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
            except (ValueError, TypeError):
                continue
            points.append((t, float(v)))
        # Append today's live value as the rightmost point if it's not already
        # in the sink batch (the current run writes AFTER trend rendering, so
        # we add it explicitly here).
        if isinstance(ev.value, (int, float)) and ev.last_observed_at:
            try:
                t_now = datetime.strptime(ev.last_observed_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
                points.append((t_now, float(ev.value)))
            except (ValueError, TypeError):
                pass
        # Dedupe identical timestamps (last write wins) and sort
        seen: dict[float, float] = {}
        for tx, vy in points:
            seen[tx] = vy
        points = sorted(seen.items())
        if len(points) < 3:
            continue

        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        xmin, xmax = min(xs), max(xs)
        ymin_data, ymax_data = min(ys), max(ys)
        ymin, ymax = ymin_data, ymax_data

        thr = ev.thresholds or {}
        guide_specs: list[tuple[str, float, str]] = []
        for key in ("yellow_above", "red_above", "yellow_below", "red_below"):
            v = thr.get(key)
            if v is None:
                continue
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            color = "yellow" if "yellow" in key else "red"
            guide_specs.append((key, fv, color))
            ymin = min(ymin, fv)
            ymax = max(ymax, fv)
        if ymax == ymin:
            ymax = ymin + 1
        pad = (ymax - ymin) * 0.08
        ymin -= pad
        ymax += pad
        x_extent = max(xmax - xmin, 1)
        y_extent = ymax - ymin

        def to_svg(t: float, v: float) -> tuple[float, float]:
            x = L + (t - xmin) / x_extent * plot_w
            y = T + (1 - (v - ymin) / y_extent) * plot_h
            return x, y

        path_pts = [to_svg(t, v) for t, v in points]
        path_d = " ".join(
            f"{'M' if i == 0 else 'L'} {x:.2f} {y:.2f}"
            for i, (x, y) in enumerate(path_pts)
        )
        plotted = [
            {"x": x, "y": y, "value": v, "ts": datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")}
            for ((x, y), (t, v)) in zip(path_pts, points)
        ]

        guides: list[dict] = []
        for key, val, color in guide_specs:
            y_svg = T + (1 - (val - ymin) / y_extent) * plot_h
            guides.append({"label": key, "value": val, "color": color, "y": y_svg})

        out.append({
            "signal_id": ev.signal_id,
            "component": ev.component,
            "status": ev.status,
            "unit": ev.unit,
            "current_value": ev.value,
            "n_points": len(points),
            "path_d": path_d,
            "points": plotted,
            "guides": guides,
            "ymin": ymin,
            "ymax": ymax,
            "ymin_label": f"{ymin_data:g}",
            "ymax_label": f"{ymax_data:g}",
            "xmin_label": datetime.fromtimestamp(xmin, tz=timezone.utc).strftime("%m-%d %H:%M"),
            "xmax_label": datetime.fromtimestamp(xmax, tz=timezone.utc).strftime("%m-%d %H:%M"),
            "viewbox": f"0 0 {W} {H}",
            "plot_box": {"L": L, "R": R, "T": T, "B": B, "W": W, "H": H},
            "y_axis_x": L,
            "x_axis_y": T + plot_h,
            "x_axis_x_end": L + plot_w,
        })
    out.sort(key=lambda d: (STATUS_RANK.get(d["status"], 0) * -1, d["component"], d["signal_id"]))
    return out


def render_html(
    output_dir: Path,
    evaluations: list[Evaluation],
    snapshot_date: str,
    overall: str,
    morning_summary: list[dict],
) -> None:
    if Environment is None:
        raise RuntimeError("jinja2 is not installed; run run.sh which sets up the venv")

    env = Environment(
        loader=FileSystemLoader(str(RENDER_DIR)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )

    css = (CSS_DIR / "dashboard.css").read_text() if (CSS_DIR / "dashboard.css").exists() else ""

    # Group evaluations by component
    by_component: dict[str, list[Evaluation]] = {}
    for ev in evaluations:
        by_component.setdefault(ev.component, []).append(ev)

    any_regressions = [ev for ev in evaluations if ev.regressions]

    trends = build_trend_data(evaluations)
    trends_by_component: dict[str, list[dict]] = {}
    for t in trends:
        trends_by_component.setdefault(t["component"], []).append(t)
    trend_skipped = sorted(
        ev.signal_id for ev in evaluations
        if ev.signal_id not in {t["signal_id"] for t in trends}
        and not isinstance(ev.value, dict)
    )

    snapshot_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Index page
    index_html = env.get_template("index.html.j2").render(
        snapshot_date=snapshot_date,
        snapshot_time=snapshot_time,
        overall=overall,
        by_component=by_component,
        regressions=any_regressions,
        morning_summary=morning_summary,
        css=css,
    )
    (output_dir / "index.html").write_text(index_html)

    # Per-component pages
    (output_dir / "components").mkdir(parents=True, exist_ok=True)
    for component, evs in by_component.items():
        comp_html = env.get_template("component.html.j2").render(
            component=component,
            evaluations=evs,
            snapshot_date=snapshot_date,
            regressions_count=len(any_regressions),
            css=css,
        )
        (output_dir / "components" / f"{component}.html").write_text(comp_html)

    # Regressions page
    reg_html = env.get_template("regressions.html.j2").render(
        regressions=any_regressions,
        snapshot_date=snapshot_date,
        css=css,
    )
    (output_dir / "regressions.html").write_text(reg_html)

    # Trends page
    trends_html = env.get_template("trends.html.j2").render(
        snapshot_date=snapshot_date,
        snapshot_time=snapshot_time,
        overall=overall,
        trends_by_component=trends_by_component,
        trend_skipped=trend_skipped,
        regressions_count=len(any_regressions),
        css=css,
    )
    (output_dir / "trends.html").write_text(trends_html)


def update_latest_symlink(output_root: Path, snapshot_date: str) -> None:
    latest = output_root / "latest"
    if latest.is_symlink() or latest.exists():
        latest.unlink()
    latest.symlink_to(snapshot_date)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tempdir", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--snapshot-date", required=True)
    args = parser.parse_args()

    signals = load_signals()
    baselines = load_baselines()
    observations = merge_results(args.tempdir)
    prior = load_prior_snapshot(args.output_root, args.snapshot_date)
    prior_obs = prior.get("observations", {})

    evaluations = evaluate_signals(signals, baselines, observations, prior_obs)
    overall = overall_status(evaluations)

    output_dir = args.output_root / args.snapshot_date
    output_dir.mkdir(parents=True, exist_ok=True)

    # Write data.json first (machine-readable persistence)
    data_json = {
        "snapshot_date": args.snapshot_date,
        "snapshot_time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "overall": overall,
        "observations": observations,
        "evaluations": [asdict(ev) for ev in evaluations],
    }
    (output_dir / "data.json").write_text(json.dumps(data_json, indent=2, default=str))

    # Append sink records for each evaluation
    write_sink_records(evaluations)

    # Pull morning-summary sink entries (last 24h, ex-dashboard-check)
    morning_summary = [
        rec for rec in sink.read_recent(since_hours=24)
        if rec.get("source_skill") != "dashboard-check"
    ]

    # Render
    render_html(output_dir, evaluations, args.snapshot_date, overall, morning_summary)
    update_latest_symlink(args.output_root, args.snapshot_date)

    # Console summary
    reds = [ev for ev in evaluations if ev.status == "red"]
    yellows = [ev for ev in evaluations if ev.status == "yellow"]
    greens = [ev for ev in evaluations if ev.status == "green"]
    errors = [ev for ev in evaluations if ev.status == "error"]
    print(f"dashboard overall: {overall.upper()}")
    print(f"  green={len(greens)} yellow={len(yellows)} red={len(reds)} error={len(errors)}")
    for ev in reds:
        print(f"  RED {ev.signal_id} value={ev.value} baseline={ev.baseline} regressions={ev.regressions}")
    for ev in yellows:
        print(f"  YEL {ev.signal_id} value={ev.value} baseline={ev.baseline}")
    print(f"html: {output_dir}/index.html")

    return STATUS_TO_EXIT[STATUS_RANK[overall]]


if __name__ == "__main__":
    sys.exit(main())
