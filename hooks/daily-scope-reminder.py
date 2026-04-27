#!/usr/bin/env python3
"""SessionStart hook: remind Mark to run /daily-scope (or /morning) if today hasn't been scoped.

Fires only when all of:
  - Local time is >= 10:30
  - mark-todos.md's ## Today's Scope heading date != today
    (or the block is missing entirely)

Silent once today's scope is set (even if the user hasn't ticked anything off yet).
Companion to daily-wrap-reminder.py.
"""

from __future__ import annotations

import datetime as dt
import re
import sys
from pathlib import Path

MARK_TODOS = (
    Path.home() / "Documents/worklog/knowledgebase/topics/personal-notes/notes/entities/mark-todos.md"
)
BEGIN = "<!-- BEGIN-TODAY-SCOPE -->"
END = "<!-- END-TODAY-SCOPE -->"
HEADING_RE = re.compile(r"^##\s+Today's Scope\s*\((\d{4}-\d{2}-\d{2})\)", re.MULTILINE)
REMINDER_HOUR = 10
REMINDER_MINUTE = 30


def main() -> int:
    now = dt.datetime.now()
    if (now.hour, now.minute) < (REMINDER_HOUR, REMINDER_MINUTE):
        return 0

    today_str = now.strftime("%Y-%m-%d")

    if not MARK_TODOS.exists():
        return 0

    try:
        content = MARK_TODOS.read_text(encoding="utf-8")
    except OSError:
        return 0

    start = content.find(BEGIN)
    end = content.find(END)
    if start == -1 or end == -1:
        # No scope block at all — rare, but worth surfacing
        print(
            f"## Morning Scope Reminder\n\n"
            f"⏰ It's past {REMINDER_HOUR}:{REMINDER_MINUTE:02d} local and `mark-todos.md` has no "
            f"`## Today's Scope` block. Consider running `/morning` or `/daily-scope` to plan the day."
        )
        return 0

    block = content[start:end]
    m = HEADING_RE.search(block)
    if m and m.group(1) == today_str:
        return 0

    scope_date = m.group(1) if m else "missing"
    print(
        f"## Morning Scope Reminder\n\n"
        f"⏰ It's past {REMINDER_HOUR}:{REMINDER_MINUTE:02d} local and today's scope hasn't been "
        f"set yet (mark-todos shows scope date `{scope_date}`, expected `{today_str}`). "
        f"Consider running `/morning` or `/daily-scope` to orient + plan."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
