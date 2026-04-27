#!/usr/bin/env python3
"""SessionStart hook: remind Mark to run /daily-wrap if past the scheduled time.

Fires only when all of:
  - Local time is >= 17:30 on today's date
  - Today's daily note exists AND its Summary section still reads the pending placeholder
    (i.e. /daily-wrap hasn't been run yet)

Silent otherwise. Prints a reminder block to stdout which gets injected into the
starting session's context.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

DAILY_DIR = Path.home() / "Documents/worklog/knowledgebase/topics/personal-notes/notes/daily"
PENDING_MARKER = "_(pending — filled in at /daily-wrap)_"
REMINDER_HOUR = 17
REMINDER_MINUTE = 30


def main() -> int:
    now = dt.datetime.now()
    if (now.hour, now.minute) < (REMINDER_HOUR, REMINDER_MINUTE):
        return 0

    today_note = DAILY_DIR / f"{now.strftime('%Y-%m-%d')}.md"
    if not today_note.exists():
        print(
            f"## Daily Wrap Reminder\n\n"
            f"⏰ It's past {REMINDER_HOUR}:{REMINDER_MINUTE:02d} local and today's daily note "
            f"(`{today_note.name}`) doesn't exist yet. Consider running `/daily-wrap` to close "
            f"out the day, or `/daily-scope` if you haven't planned yet."
        )
        return 0

    try:
        content = today_note.read_text(encoding="utf-8")
    except OSError:
        return 0

    if PENDING_MARKER in content:
        print(
            f"## Daily Wrap Reminder\n\n"
            f"⏰ It's past {REMINDER_HOUR}:{REMINDER_MINUTE:02d} local and today's daily note "
            f"Summary is still pending. Consider running `/daily-wrap` to close out the day."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
