"""Shared helpers for session-claims hook scripts.

The claims table lives inside mark-todos.md between
<!-- BEGIN-SESSION-CLAIMS --> / <!-- END-SESSION-CLAIMS --> sentinels.

Table schema (5 cols): | Label | Scope | CWD | Started | Heartbeat |

Timestamps are ISO-8601 UTC (minute-precision): YYYY-MM-DDTHH:MMZ.
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple

MARK_TODOS = (
    Path.home()
    / "Documents/worklog/knowledgebase/topics/personal-notes/notes/entities/mark-todos.md"
)

BLOCK_RE = re.compile(
    r"(<!-- BEGIN-SESSION-CLAIMS -->)(.*?)(<!-- END-SESSION-CLAIMS -->)",
    re.DOTALL,
)

PLACEHOLDER_LABEL = "*(none claimed)*"
STALE_AFTER = timedelta(hours=2)


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def parse_ts(s: str) -> Optional[datetime]:
    s = s.strip()
    if not s:
        return None
    try:
        # Accept both YYYY-MM-DDTHH:MMZ and with seconds
        for fmt in ("%Y-%m-%dT%H:%MZ", "%Y-%m-%dT%H:%M:%SZ"):
            with contextlib.suppress(ValueError):
                return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
    except Exception:
        return None
    return None


def split_row(line: str) -> Optional[List[str]]:
    """Return list of 5 stripped cell values, or None if not a data row."""
    if "|" not in line:
        return None
    parts = [p.strip() for p in line.split("|")]
    # A valid row has leading and trailing empties from the pipes: ['', a, b, c, d, e, '']
    if len(parts) != 7:
        return None
    if parts[0] != "" or parts[-1] != "":
        return None
    cells = parts[1:-1]
    # Skip header/separator rows
    if cells[0].startswith("-") or cells[0].lower() == "label":
        return None
    return cells


def build_row(label: str, scope: str, cwd: str, started: str, heartbeat: str) -> str:
    return f"| {label} | {scope} | {cwd} | {started} | {heartbeat} |"


def placeholder_row() -> str:
    return f"| {PLACEHOLDER_LABEL} | | | | |"


def read_claims_block(content: str) -> Optional[Tuple[str, int, int]]:
    """Return (block_text, start_idx, end_idx) of the block interior, or None."""
    m = BLOCK_RE.search(content)
    if not m:
        return None
    return m.group(2), m.start(2), m.end(2)


def splice_block(content: str, new_block: str) -> str:
    m = BLOCK_RE.search(content)
    if not m:
        return content
    return content[: m.start(2)] + new_block + content[m.end(2) :]


def parse_rows(block: str) -> Tuple[List[str], List[List[str]], List[str]]:
    """Return (prefix_lines, data_rows, suffix_lines).

    Data rows are list-of-5-cells. Prefix is everything before the first data row
    (header + any prose). Suffix is everything after the last data row.
    """
    lines = block.splitlines()
    prefix: List[str] = []
    rows: List[List[str]] = []
    suffix: List[str] = []
    in_data = False
    for ln in lines:
        cells = split_row(ln)
        if cells is None:
            if in_data:
                suffix.append(ln)
            else:
                prefix.append(ln)
        else:
            if cells[0] == PLACEHOLDER_LABEL:
                # drop placeholder; it's re-added only if rows is empty at render
                in_data = True
                continue
            rows.append(cells)
            in_data = True
    return prefix, rows, suffix


def render_block(prefix: List[str], rows: List[List[str]], suffix: List[str]) -> str:
    out_rows = rows if rows else None
    lines: List[str] = list(prefix)
    if out_rows is None:
        lines.append(placeholder_row())
    else:
        for r in out_rows:
            lines.append(build_row(*r))
    lines.extend(suffix)
    return "\n".join(lines)


def prune_stale(rows: List[List[str]]) -> Tuple[List[List[str]], List[List[str]]]:
    """Return (kept, dropped)."""
    now = datetime.now(timezone.utc)
    kept: List[List[str]] = []
    dropped: List[List[str]] = []
    for r in rows:
        hb = parse_ts(r[4])
        if hb is None or now - hb <= STALE_AFTER:
            kept.append(r)
        else:
            dropped.append(r)
    return kept, dropped


@contextlib.contextmanager
def locked_edit():
    """Open mark-todos for read+write with an exclusive flock."""
    if not MARK_TODOS.exists():
        yield None
        return
    with open(MARK_TODOS, "r+", encoding="utf-8") as f:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        except OSError:
            pass
        yield f
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass


def load_and_parse() -> Optional[Tuple[str, List[str], List[List[str]], List[str]]]:
    """Return (content, prefix, rows, suffix) or None if no block found."""
    if not MARK_TODOS.exists():
        return None
    content = MARK_TODOS.read_text(encoding="utf-8")
    block = read_claims_block(content)
    if not block:
        return None
    prefix, rows, suffix = parse_rows(block[0])
    return content, prefix, rows, suffix
