#!/usr/bin/env python3
"""Stop-hook: update heartbeat for the claim row matching this session's CWD.

No-op if no block exists or no row matches. Designed to be fast (<100ms) and
safe to run concurrently across multiple Claude Code sessions (uses flock).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from session_claims_common import (  # noqa: E402
    load_and_parse,
    locked_edit,
    now_utc,
    read_claims_block,
    render_block,
    splice_block,
)


def main() -> int:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        payload = {}

    cwd = payload.get("cwd") or os.getcwd()

    parsed = load_and_parse()
    if parsed is None:
        return 0
    _, prefix, rows, suffix = parsed
    if not rows:
        return 0

    updated = False
    for r in rows:
        if r[2] == cwd:
            r[4] = now_utc()
            updated = True

    if not updated:
        return 0

    new_block = render_block(prefix, rows, suffix)
    with locked_edit() as f:
        if f is None:
            return 0
        f.seek(0)
        content = f.read()
        new_content = splice_block(content, new_block)
        if new_content != content:
            f.seek(0)
            f.truncate()
            f.write(new_content)
    return 0


if __name__ == "__main__":
    sys.exit(main())
