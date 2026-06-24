---
name: recap
description: Snapshot current state — Today's Scope progress, active claims, this session's tasks, items closed today. Read-only. Trigger: '/recap', 'status', 'where are we'.
user-invocable: true
allowed-tools:
  - Read
  - Grep
  - Bash
  - TaskList
---

# /recap — today's status snapshot

Give the user a quick, structured read of where today's tracked work stands. Read-only — no edits, no writes, no claims. Designed to take <10 seconds and fit on one screen.

## When to use

- User asks "where are we?", "status?", "recap", "what's left today?"
- Coming back from lunch / a meeting / another task — need to re-orient
- Before `/daily-wrap` — preview of what the wrap will cover
- Checking on parallel-session progress without switching to those sessions

## Procedure

1. **Determine today's date** via `date +%Y-%m-%d`. Call this `TODAY`.

2. **Read mark-todos.md:**
   - Extract the `<!-- BEGIN-TODAY-SCOPE -->` / `<!-- END-TODAY-SCOPE -->` block
   - Extract the `<!-- BEGIN-SESSION-CLAIMS -->` / `<!-- END-SESSION-CLAIMS -->` block

3. **Parse Today's Scope:**
   - Get the `## Today's Scope (YYYY-MM-DD)` date from the heading
   - Count `- [x]` (closed) vs `- [ ]` (open) items
   - Flag "stale scope" if the date in the heading != `TODAY`

4. **Parse Session Claims:**
   - List all data rows from the table (skip placeholder)
   - Flag rows where `CWD` matches current `$PWD` (this session)
   - Flag rows where heartbeat age >30 min (potentially idle)
   - Flag rows where heartbeat age >2h (will be auto-pruned)

5. **Read daily note stub** at `topics/personal-notes/notes/daily/TODAY.md` (may not exist):
   - If exists: pull `## Closed Line Items` bullets
   - If missing: note "no daily note stub yet today"

6. **Read in-session task list** via `TaskList` — count by status (pending, in_progress, completed, deleted).

7. **Compose output** — single markdown block, sections in this order:
   - **Today's Scope** — date, progress summary (e.g., "3 of 7 closed"), unchecked items as bullets, note if stale
   - **Active Session Claims** — mini table of label / scope / heartbeat-age, highlight overlap/stale
   - **This Session** — in_progress + pending task subjects, completed count
   - **Closed Today** — bullets from daily note `## Closed Line Items`, or "(none logged yet)"

## Output template

```
# Recap — YYYY-MM-DD

## Today's Scope (Scope date: YYYY-MM-DD) — N/M closed

**Open:**
- …
- …

(Show `(stale — scope date is DATE, not today — suggest /daily-scope)` if scope date != today.)

## Active Session Claims

| Label | Scope (truncated) | Heartbeat age |
|-------|-------------------|---------------|
| lambda-e2e | §3 §9 cleanup Lambda stage E2E | 2m (fresh) |
| stage-regression | §2a §3 overnight regression | 8m (fresh) |
| scope-and-claims | §1 v5 doc sweep (this session) | now |

⚠️ Overlap with this CWD: `scope-and-claims` — expected (this session).
🟡 Stale (>30 min): (none) / list if any
🔴 Will be pruned (>2h): (none) / list if any

## This Session

- In-progress: N task(s) — list
- Pending: N task(s) — list
- Completed: N
- Deleted: N

## Closed Today

- `§1 v5 per-model doc pages sweep` — link to daily note entry
- `§1 SAHI leak fix` — PR #NN
- (or "(none logged yet)")
```

## Rules

- **Never edit.** This skill is read-only. No updating mark-todos, no writing daily notes, no claim changes.
- **No prose beyond section content.** Headers and tables do the work.
- **Truncate long scope strings** to ~60 chars in tables.
- **Absolute timestamps** convert to relative ("4m ago", "2h ago") in the claims table.
- **If a sentinel block is missing**, print a one-line note under the relevant heading and move on — don't fail.

## Related

- `/daily-scope` — sets Today's Scope (this skill only reads it)
- `/daily-wrap` — EOD archival (this skill is its companion preview)
- `/claim` / `/release` / `/claims` — session-claims management
- `mark-todos.md` — the source of truth for everything this skill reads
