#!/usr/bin/env python3
"""SessionStart-hook: prune stale claim rows, then print active claims to stdout.

stdout is injected as context into the starting session. Claude should treat it
as a reminder: if the new session's planned scope overlaps an active claim,
warn the user before proceeding.
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
    prune_stale,
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

    kept, dropped = prune_stale(rows)
    if dropped:
        new_block = render_block(prefix, kept, suffix)
        with locked_edit() as f:
            if f is not None:
                f.seek(0)
                content = f.read()
                new_content = splice_block(content, new_block)
                if new_content != content:
                    f.seek(0)
                    f.truncate()
                    f.write(new_content)

    # Emit summary
    if not kept:
        print("## Session Claims\n\nNo other sessions are claimed. Use `/claim <label> <scope>` if this session will work on a tracked §N workstream item for >15 min.")
        return 0

    lines = ["## Active Session Claims", ""]
    same_cwd = [r for r in kept if r[2] == cwd]
    other = [r for r in kept if r[2] != cwd]
    if same_cwd:
        lines.append("**Overlapping this CWD — potential duplicate work:**")
        for r in same_cwd:
            lines.append(f"- `{r[0]}` — {r[1]} (started {r[3]}, last heartbeat {r[4]})")
        lines.append("")
    if other:
        lines.append("**Other active sessions:**")
        for r in other:
            lines.append(f"- `{r[0]}` — {r[1]} (cwd `{r[2]}`, heartbeat {r[4]})")
        lines.append("")
    lines.append(
        "Before picking up tracked work: check if your planned scope overlaps. "
        "If it does, warn the user. Use `/claim` to register this session if it will work on a tracked item."
    )
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
