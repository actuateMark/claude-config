"""Tests for git_local collector dispatchers.

Currently focused on the onboarder healthcheck-hotfix dispatcher: a
permanent regression check on the 2026-04-23 silent-early-return incident.
"""
import sys
import tempfile
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

from collect import autopatrol_onboarder_healthcheck_hotfix  # noqa: E402


HOTFIX_IN_EFFECT = '''\
def main():
    res = autopatroller.get_healthcheck()
    if res is None or res.status_code not in [200, 201]:
        logging.warning(
            f"AutoPatrol healthcheck returned {res}. Continuing — "
            "contract/site/schedule endpoints are the real signal."
        )
    else:
        logging.info("AutoPatrol API health check passed")
'''

HOTFIX_REVERTED = '''\
def main():
    res = autopatroller.get_healthcheck()
    if res is None or res.status_code not in [200, 201]:
        logging.warning("AutoPatrol healthcheck failed")
        return
    else:
        logging.info("AutoPatrol API health check passed")
'''

NO_WARNING = '''\
def main():
    res = autopatroller.get_healthcheck()
    if res is None or res.status_code not in [200, 201]:
        logging.error("AutoPatrol healthcheck failed")
        raise RuntimeError("dead")
'''

NO_CALL = '''\
def main():
    logging.info("doing things, no healthcheck")
'''


def _write(repo: Path, body: str) -> Path:
    (repo / "lambda_function.py").write_text(body)
    return repo


def test_hotfix_in_effect_returns_1():
    with tempfile.TemporaryDirectory() as td:
        repo = _write(Path(td), HOTFIX_IN_EFFECT)
        assert autopatrol_onboarder_healthcheck_hotfix(repo) == 1


def test_hotfix_reverted_returns_0():
    with tempfile.TemporaryDirectory() as td:
        repo = _write(Path(td), HOTFIX_REVERTED)
        assert autopatrol_onboarder_healthcheck_hotfix(repo) == 0


def test_no_warning_returns_0():
    with tempfile.TemporaryDirectory() as td:
        repo = _write(Path(td), NO_WARNING)
        assert autopatrol_onboarder_healthcheck_hotfix(repo) == 0


def test_no_call_returns_0():
    with tempfile.TemporaryDirectory() as td:
        repo = _write(Path(td), NO_CALL)
        assert autopatrol_onboarder_healthcheck_hotfix(repo) == 0


def test_missing_file_returns_none():
    with tempfile.TemporaryDirectory() as td:
        assert autopatrol_onboarder_healthcheck_hotfix(Path(td)) is None
