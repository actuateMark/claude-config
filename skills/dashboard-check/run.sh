#!/usr/bin/env bash
# Entry wrapper for /dashboard-check skill. Ensures the scoped venv exists,
# installs jinja2 if missing, then dispatches to the requested sub-command.
#
# Usage:
#   run.sh render --tempdir <dir> --output-root <dir> --snapshot-date <YYYY-MM-DD>
#   run.sh sink-write '<json-record>'
#   run.sh sink-recent <hours>
#   run.sh test
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SKILL_DIR/.venv"
PYTHON=${DASHBOARD_PY:-python3}

# Force public PyPI regardless of the user's CodeArtifact-pinned env/config
# (only used in the fallback path below).
PUBLIC_PYPI="https://pypi.org/simple/"

# Prefer the already-available Python if it has jinja2. Only fall back to a
# scoped venv if not. Keeps the skill fast to start + insulated from CA auth.
resolve_python() {
  # We need both jinja2 (render) and boto3 (collect) on a single interpreter.
  REQUIRED_IMPORTS="jinja2, boto3"
  # 1) system python3 with all required deps → use it
  if "$PYTHON" -c "import $REQUIRED_IMPORTS" 2>/dev/null; then
    SKILL_PY="$PYTHON"
    return 0
  fi
  # 2) existing venv with all required deps
  if [ -x "$VENV_DIR/bin/python" ] && "$VENV_DIR/bin/python" -c "import $REQUIRED_IMPORTS" 2>/dev/null; then
    SKILL_PY="$VENV_DIR/bin/python"
    return 0
  fi
  # 3) create/refresh venv from requirements.txt against public PyPI
  echo "[dashboard-check] resolving venv at $VENV_DIR (need: $REQUIRED_IMPORTS)" >&2
  if command -v uv >/dev/null 2>&1; then
    [ -d "$VENV_DIR" ] || uv venv "$VENV_DIR" --quiet
    env -u UV_INDEX -u UV_EXTRA_INDEX_URL -u PIP_INDEX_URL -u PIP_EXTRA_INDEX_URL UV_CONFIG_FILE=/dev/null uv pip install --quiet --python "$VENV_DIR/bin/python" --default-index "$PUBLIC_PYPI" -r "$SKILL_DIR/requirements.txt"
  else
    [ -d "$VENV_DIR" ] || "$PYTHON" -m venv "$VENV_DIR"
    env -u PIP_INDEX_URL -u PIP_EXTRA_INDEX_URL PIP_CONFIG_FILE=/dev/null "$VENV_DIR/bin/python" -m pip install --quiet --index-url "$PUBLIC_PYPI" -r "$SKILL_DIR/requirements.txt"
  fi
  SKILL_PY="$VENV_DIR/bin/python"
}

cmd=${1:-help}
shift || true

case "$cmd" in
  collect)
    resolve_python
    exec "$SKILL_PY" "$SKILL_DIR/collect.py" "$@"
    ;;
  render)
    resolve_python
    exec "$SKILL_PY" "$SKILL_DIR/render.py" "$@"
    ;;
  sink-write)
    # sink.py uses only stdlib; no deps
    exec "$PYTHON" "$SKILL_DIR/sink.py" write "$@"
    ;;
  sink-recent)
    exec "$PYTHON" "$SKILL_DIR/sink.py" recent "$@"
    ;;
  test)
    resolve_python
    if ! "$SKILL_PY" -c "import pytest" 2>/dev/null; then
      # pytest is a dev-only dep; use `pip --user` with clean env to dodge CodeArtifact.
      env -u PIP_INDEX_URL -u PIP_EXTRA_INDEX_URL PIP_CONFIG_FILE=/dev/null \
        "$SKILL_PY" -m pip install --quiet --user --index-url "$PUBLIC_PYPI" pytest \
        --break-system-packages 2>/dev/null \
        || env -u PIP_INDEX_URL -u PIP_EXTRA_INDEX_URL PIP_CONFIG_FILE=/dev/null \
           "$SKILL_PY" -m pip install --quiet --user --index-url "$PUBLIC_PYPI" pytest
    fi
    exec "$SKILL_PY" -m pytest "$SKILL_DIR/tests" "$@"
    ;;
  help|--help|-h|"")
    cat <<'EOF'
/dashboard-check skill runner

Subcommands:
  collect --tempdir <dir> [--aws-profile <name>] [-v]
    Run the de-LLM collect step: NR via nerdgraph, AWS via boto3.
    Writes nr_results.json, cw_results.json, ce_results.json.

  render --tempdir <dir> --output-root <dir> --snapshot-date <YYYY-MM-DD>
    Run the full render pipeline against a directory of collected results.

  sink-write '<json-record>'
    Append an observation to the shared sink JSONL.

  sink-recent <hours>
    Print recent sink observations (newest-last).

  test
    Run the skill's pytest suite.
EOF
    ;;
  *)
    echo "unknown subcommand: $cmd" >&2
    exit 64
    ;;
esac
