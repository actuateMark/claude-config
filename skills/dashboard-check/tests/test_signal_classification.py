"""Tests for /dashboard-check signal classification + regression rules.

Canonical acceptance: the 2026-04-23 onboarder silent-early-return pattern
MUST classify as RED. If this test fails, Phase 1a implementation is broken.
"""
import json
import sys
import tempfile
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

import render  # noqa: E402
import sink  # noqa: E402


ONBOARDER_SIGNAL = {
    "id": "onboarder_activity_us",
    "component": "autopatrol_onboarder",
    "source": "cw_log",
    "regression_rules": ["silent_drop", "activity_marker_antipattern"],
    "pair_with": "onboarder_lambda_invocations_us",
    "thresholds": {"yellow_below": 5, "red_below": 1},
    "enabled": True,
}


def test_onboarder_silent_earlyreturn_is_red():
    """The 2026-04-23 incident: Lambda invocations=12 (normal) but activity=0
    (silent early-return). Must classify RED via Rule 5 (activity-marker anti-pattern)."""
    observations = {
        "onboarder_activity_us": 0,
        "onboarder_lambda_invocations_us": 12,
    }
    prior = {
        "onboarder_activity_us": 11,
        "onboarder_lambda_invocations_us": 12,
    }
    regressions, elevated = render.apply_regression_rules(
        ONBOARDER_SIGNAL, 0, prior["onboarder_activity_us"], observations
    )
    assert "activity_marker_antipattern" in regressions, \
        f"expected activity_marker_antipattern in {regressions}"
    assert elevated == "red", f"expected elevated=red, got {elevated}"


def test_onboarder_healthy_is_green():
    """Normal operation: 12 invocations, 11 activity markers. Should NOT trip any rule."""
    observations = {
        "onboarder_activity_us": 11,
        "onboarder_lambda_invocations_us": 12,
    }
    regressions, elevated = render.apply_regression_rules(
        ONBOARDER_SIGNAL, 11, 11, observations
    )
    assert not regressions, f"expected no regressions, got {regressions}"
    assert elevated is None, f"expected elevated=None, got {elevated}"


def test_onboarder_silent_drop_is_red():
    """Silent drop: prior=20, today=0. Rule 1 (silent_drop) should fire RED."""
    observations = {
        "onboarder_activity_us": 0,
        "onboarder_lambda_invocations_us": 0,  # pair is also 0, so rule 5 shouldn't fire
    }
    regressions, elevated = render.apply_regression_rules(
        ONBOARDER_SIGNAL, 0, 20, observations
    )
    assert "silent_drop" in regressions
    assert elevated == "red"


def test_classify_threshold_red_below():
    signal = {"thresholds": {"yellow_below": 5, "red_below": 1}}
    assert render.classify(signal, 0, None) == "red"
    assert render.classify(signal, 3, None) == "yellow"
    assert render.classify(signal, 12, None) == "green"


def test_classify_threshold_red_above():
    signal = {"thresholds": {"yellow_above": 20, "red_above": 100}}
    assert render.classify(signal, 150, None) == "red"
    assert render.classify(signal, 50, None) == "yellow"
    assert render.classify(signal, 5, None) == "green"


def test_classify_no_thresholds_is_informational():
    signal = {}
    assert render.classify(signal, 42, None) == "informational"


def test_classify_none_value_is_error():
    signal = {"thresholds": {"red_above": 10}}
    assert render.classify(signal, None, None) == "error"


def test_new_pattern_facet_rule():
    """FACET signal with a new key today that wasn't prior should trigger new_pattern."""
    signal = {
        "id": "fleet_new_oom_offender",
        "regression_rules": ["new_pattern"],
        "critical": True,
    }
    today = {"connector-20628": 87, "connector-14170": 25}
    prior = {"connector-14170": 32, "connector-23730": 18}
    regressions, elevated = render.apply_regression_rules(signal, today, prior, {})
    assert any("new_pattern" in r for r in regressions)
    assert elevated == "red"  # critical=True → red


def test_sink_roundtrip(tmp_path, monkeypatch):
    """write_observation() then read_recent() returns the same record shape."""
    test_sink = tmp_path / "observations.jsonl"
    monkeypatch.setattr(sink, "SINK_PATH", test_sink)

    ok = sink.write_observation(
        component="vms-connector",
        signal_id="test_signal",
        value=42,
        status="green",
        source_skill="test-suite",
        notes="roundtrip",
    )
    assert ok

    records = sink.read_recent(since_hours=1)
    assert len(records) == 1
    r = records[0]
    assert r["component"] == "vms-connector"
    assert r["signal_id"] == "test_signal"
    assert r["value"] == 42
    assert r["status"] == "green"
    assert r["source_skill"] == "test-suite"
    assert r["notes"] == "roundtrip"
    assert "timestamp" in r


def test_sink_rejects_invalid_status(tmp_path, monkeypatch):
    test_sink = tmp_path / "observations.jsonl"
    monkeypatch.setattr(sink, "SINK_PATH", test_sink)
    ok = sink.write_observation(
        component="x", signal_id="y", value=1,
        status="INVALID", source_skill="z",
    )
    assert not ok


# -----------------------------------------------------------------------------
# Historical incident replay tests (added 2026-04-24, Phase 1b)
#
# Each test encodes a specific past incident with real observed values and
# asserts the dashboard would have classified it correctly. Failures here mean
# a signal's threshold / rule no longer catches what it's documented to catch.
# -----------------------------------------------------------------------------


FLEET_OOMKILLS_SIGNAL = {
    "id": "fleet_oomkills_24h",
    "component": "vms-connector",
    "source": "nr_k8s_container_sample",
    "regression_rules": ["baseline_drift"],
    "thresholds": {"yellow_above": 200, "red_above": 350},
    "enabled": True,
}


def test_replay_2026_04_23_oom_surge_is_red():
    """2026-04-23: OOMKills spiked to 423/24h (4x baseline ~103).
    Threshold red_above=350 → must classify RED via static threshold."""
    assert render.classify(FLEET_OOMKILLS_SIGNAL, 423, baseline=103) == "red", \
        "2026-04-23 OOM surge of 423/24h should be RED against red_above=350"
    # And a normal day should stay GREEN.
    assert render.classify(FLEET_OOMKILLS_SIGNAL, 110, baseline=103) == "green"


FLEET_NEW_OOM_OFFENDER_SIGNAL = {
    "id": "fleet_new_oom_offender",
    "component": "vms-connector",
    "source": "nr_k8s_container_sample",
    "regression_rules": ["new_pattern"],
    # no `critical` flag → new_pattern bumps to yellow, not red
    "enabled": True,
}


def test_replay_2026_04_23_connector_20628_emergence_is_yellow():
    """2026-04-23: connector-20628 showed up in the top-10 OOMers at 87 events,
    not in the prior-day top-N. new_pattern rule should fire yellow (signal is
    not marked critical)."""
    today = {
        "connector-20628": 87,   # NEW
        "connector-14170": 45,
        "connector-23730": 38,
    }
    prior = {
        "connector-14170": 32,
        "connector-23730": 18,
        "connector-12686": 10,
    }
    regressions, elevated = render.apply_regression_rules(
        FLEET_NEW_OOM_OFFENDER_SIGNAL, today, prior, {}
    )
    assert any("new_pattern" in r for r in regressions), \
        f"expected new_pattern in {regressions}"
    assert any("connector-20628" in r for r in regressions), \
        f"expected connector-20628 in {regressions}"
    assert elevated == "yellow", f"expected yellow (non-critical), got {elevated}"


NONETYPE_UNPACK_SIGNAL = {
    "id": "nonetype_unpack_top_facet",
    "component": "vms-connector",
    "source": "nr_log",
    "regression_rules": ["new_pattern"],
    "enabled": True,
}


def test_replay_2026_04_23_nonetype_platform_shift_is_yellow():
    """2026-04-23: NoneType exception source shifted from per-connector pods
    to platform services (smtp-frame-receiver, create-detection-window) —
    a meaningful architectural shift that new_pattern should surface."""
    today = {
        "smtp-frame-receiver": 3800,       # NEW dominant
        "create-detection-window": 2200,   # NEW dominant
    }
    prior = {
        "connector-14170": 800,
        "connector-23730": 420,
    }
    regressions, elevated = render.apply_regression_rules(
        NONETYPE_UNPACK_SIGNAL, today, prior, {}
    )
    assert any("new_pattern" in r for r in regressions)
    assert elevated == "yellow"


STREAMID_GUID_SIGNAL = {
    "id": "streamid_guid_rejection_stage",
    "component": "vms-connector",
    "source": "nr_log",
    "regression_rules": [],
    "thresholds": {"yellow_above": 0, "red_above": 5},
    "enabled": True,
}


def test_replay_2026_04_20_streamid_null_is_yellow():
    """2026-04-20: streamId-null bug on :stage produced the first non-zero
    Guid-rejection hits on stage. Any nonzero count must flip yellow; >5 red.
    Canonical expectation: even a single rejection is a stage regression."""
    # Even 1 hit flips yellow
    assert render.classify(STREAMID_GUID_SIGNAL, 1, None) == "yellow"
    # 5 is still yellow (threshold is strict >)
    assert render.classify(STREAMID_GUID_SIGNAL, 5, None) == "yellow"
    # 6 trips red
    assert render.classify(STREAMID_GUID_SIGNAL, 6, None) == "red"
    # 0 stays green — this is prod-stage normal
    assert render.classify(STREAMID_GUID_SIGNAL, 0, None) == "green"


FLEET_ERROR_TOP15_SIGNAL = {
    "id": "fleet_error_top15",
    "component": "vms-connector",
    "source": "nr_log",
    "regression_rules": ["new_pattern", "baseline_drift"],
    "critical": True,
    "enabled": True,
}


def test_replay_2026_04_17_connector_deploy_11k_outlier_is_red():
    """2026-04-17: connector-deploy appeared in top-15 errors with ~11K hits,
    displacing the usual per-connector offenders. fleet_error_top15 is
    critical=True so new_pattern bumps to RED."""
    today = {
        "connector-deploy": 11000,          # NEW — deploy controller thrash
        "connector-14170": 8000,
        "create-detection-window": 3000,
    }
    prior = {
        "connector-14170": 7500,
        "connector-23730": 4200,
        "connector-29016": 2100,
    }
    regressions, elevated = render.apply_regression_rules(
        FLEET_ERROR_TOP15_SIGNAL, today, prior, {}
    )
    assert any("new_pattern" in r for r in regressions)
    assert any("connector-deploy" in r for r in regressions)
    assert elevated == "red", "critical=True signal should escalate to red"


QUEUE_EVALINK_ERRORS_SIGNAL = {
    "id": "queue_evalink_errors_12h",
    "component": "alert-pipeline",
    "source": "nr_log",
    "regression_rules": [],
    # Recalibrated 2026-04-24 against 7d real data (median ~650, max ~1178).
    # Pre-recalibration the threshold was 20/100 and the signal fired chronically.
    "thresholds": {"yellow_above": 1200, "red_above": 1800},
    "enabled": True,
}


def test_replay_2026_04_20_evalink_540_is_green_after_recal():
    """2026-04-20: 540 errors/12h on queue-evalink-consumer. Pre-recalibration
    this was "27× threshold breach" against yellow=20. Post-recalibration
    (2026-04-24) this value is BELOW the 7d median ~650 and is GREEN. The test
    documents the intentional recalibration — 540 by itself is not abnormal;
    a future spike to >1800 would catch a real incident via red_above."""
    assert render.classify(QUEUE_EVALINK_ERRORS_SIGNAL, 540, baseline=650) == "green"
    # But a real spike still catches
    assert render.classify(QUEUE_EVALINK_ERRORS_SIGNAL, 2000, baseline=650) == "red"
    assert render.classify(QUEUE_EVALINK_ERRORS_SIGNAL, 1400, baseline=650) == "yellow"


def test_replay_2026_04_20_ssl_cert_verify_is_pending():
    """2026-04-20: dev.powerplus.com SSL cert-verify failure fleet-wide (3870
    WebSocket attempts, 100% failing). NO dedicated signal exists yet — the
    fleet_error_top15 signal catches it only if the container names appear in
    top-15. Placeholder: when `ssl_cert_verify_failures_12h` ships per
    2026-04-20_dev-powerplus-ssl-cert-verify-failure synthesis, replace this
    assertion with the real fixture.

    For now, assert that fleet_error_top15 at least surfaces the offending
    container (connector-23202-chm-cronjob) via new_pattern."""
    today = {
        "connector-23202-chm-cronjob": 3870,  # SSL-failing cronjob, not in prior
        "connector-14170": 1200,
    }
    prior = {
        "connector-14170": 1100,
        "connector-23730": 800,
    }
    regressions, elevated = render.apply_regression_rules(
        FLEET_ERROR_TOP15_SIGNAL, today, prior, {}
    )
    assert any("new_pattern" in r for r in regressions)
    assert any("chm-cronjob" in r for r in regressions)
    assert elevated == "red"
