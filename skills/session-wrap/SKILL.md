---
name: session-wrap
description: Lightweight end-of-session log to today's daily note WITHOUT closing the day (companion to /daily-wrap). Trigger: '/session-wrap', 'session wrap', 'log this session'.
user-invocable: true
allowed-tools:
  - Read
  - Glob
  - Grep
  - Bash
  - Edit
  - Write
  - AskUserQuestion
---

# Session Wrap

Append the session's findings to today's daily note. Strictly additive — never reconciles, never sweeps, never archives. Made for the case where a heavy build/debug/design session produced too much to lose to chat history but the day still has hours of work ahead.

**This is NOT `/daily-wrap`.** Differences:

| Aspect | `/daily-wrap` (EOD) | `/session-wrap` (this skill) |
|---|---|---|
| When | End of day, once | After any non-trivial session, repeat OK |
| `## Summary` | Writes it | Leaves it empty for /daily-wrap |
| Sweeps `[x]` from mark-todos | Yes (Step 2.7) | No — leave for /daily-wrap |
| Archives closed §N workstreams | Yes | No |
| `topics:` / `workstreams:` frontmatter | Final reconciliation | Additive only — append, never remove |
| Interactive interview | Yes (extensive) | Lightweight — works from session conversation context |
| Touches mark-todos | Yes | No, except when an item explicitly closed |

If you're tempted to use this AT EOD, use `/daily-wrap` instead — that's its purpose. Use `/session-wrap` for **mid-day** archival of session findings.

## Arguments

- No args (typical): wrap the current session
- `--preview`: show what would be written, but don't write
- `YYYY-MM-DD` (positional): wrap into a specific date's daily note (rare; use when catching up after switching machines)

## Procedure

### Step 1 — Locate or create today's daily note

Resolve today's daily-note path via the Obsidian CLI (faster than guessing the path + Glob):

```bash
~/.local/bin/obsidian daily:path 2>/dev/null
```

Fallback if the CLI probe fails: `/home/mork/Documents/worklog/knowledgebase/topics/personal-notes/notes/daily/YYYY-MM-DD.md` (today's date — UTC-ish, use the date the user is operating in).

If the file exists, fetch contents via `~/.local/bin/obsidian daily:read` (or `Read` on the resolved path) to understand current state. If it doesn't, create the stub from the template in `topics/personal-notes/notes/daily/README.md`:

```yaml
---
title: "Daily: YYYY-MM-DD"
type: concept
topic: personal-notes
tags: [daily, wrap]
topics: []
workstreams: []
created: YYYY-MM-DD
updated: YYYY-MM-DD
author: kb-bot
---

# Daily: YYYY-MM-DD

## Summary

*(filled by /daily-wrap at EOD)*

## Closed Line Items

## Closed Sub-items

## Closed Workstreams

## Notes / Learnings
```

Set `created:` to today only on first creation. `updated:` is set/refreshed on every wrap.

### Step 2 — Identify session contributions

Walk the conversation and classify what happened. Lightweight categorization:

1. **Did anything close?** A §N workstream item, a Today's-Scope pick, a tracked TODO. If yes → bullet for `## Closed Line Items` (per-§N-section format: `**§N short-title** — what / why / link`). If unsure, ask the user once.

2. **What was built / debugged / designed / researched?** Almost everything in a build session goes here. One bullet per substantive thread:
   - **Build** — what was built, where it lives (path), what it does in one sentence
   - **Debug** — root cause + fix, in plain language
   - **Design decision** — what we picked, what we ruled out, why
   - **Investigation finding** — what we now know that we didn't before
   - **Tooling / infrastructure change** — script created, cron scheduled, KB convention added

   These go under `## Notes / Learnings` as bullets. Group related findings under a `### <topic-or-area>` sub-heading if there are multiple.

3. **What topics did the session touch?** Map to KB topic slugs (e.g., `vms-connector`, `obsidian`, `infrastructure`). This feeds the additive frontmatter update in Step 4.

4. **Did this session move any §N workstream forward (without closing it)?** Note as a bullet under `## Notes / Learnings` mentioning §N — but DO NOT mark the workstream closed or sweep its sub-items. That's `/daily-wrap`'s job.

### Step 3 — Append additively

For each section the session contributes to, **find the existing heading and append below the last item**. Never overwrite. Never reorder. Never add `## Summary` content.

If a section heading is missing in the existing daily note (e.g., user manually edited and removed `## Closed Sub-items`), do NOT add it back — that's a deliberate signal. Stop and flag in the user-facing report.

### Step 4 — Update frontmatter additively

Read the current `topics:` and `workstreams:` arrays. Merge in new values from this session, dedup, sort. Update `updated:` to today.

**Critical:** never REMOVE entries from these arrays during a session-wrap. Only add. Removal is for /daily-wrap reconciliation at EOD.

If the session touched a topic that's not yet a real KB topic (no `topics/<slug>/_summary.md`), use the closest existing topic + flag it in the user-facing report. Don't invent topic slugs.

### Step 5 — Final user-facing report

Print a concise summary:

```
session-wrap: appended to topics/personal-notes/notes/daily/YYYY-MM-DD.md

## Notes / Learnings — added 4 bullets:
- "KB-tooling infrastructure session — context-efficient retrieval"
- "Driver build — relink.py 4-pass implementation"
- ...

## Closed Line Items — added 0 bullets

frontmatter:
- topics: + [obsidian, engineering-process]   (now: [..., obsidian, engineering-process])
- workstreams: unchanged
- updated: 2026-05-01
```

If `--preview`, show the same report but don't write.

## Rules

- **Never touch `## Summary`.** That's `/daily-wrap`'s job at EOD. If `## Summary` already has content (someone wrote it), leave it alone.
- **Never sweep `[x]` items from mark-todos.** That's `/daily-wrap` Step 2.7.
- **Never archive whole §N workstreams.** That's `/daily-wrap` Step 4-5.
- **Never remove from `topics:` or `workstreams:` arrays.** Additive only.
- **Append, don't reorder.** New bullets go at the end of the existing list under each heading.
- **Be honest about scope.** Don't claim a §N item closed if it just got moved forward.
- **Repeated within the same day is fine.** Multiple session-wraps in one day each append; the daily-wrap at EOD reconciles.

## When NOT to use this

- It's actually EOD → use `/daily-wrap` instead
- The session was trivial (one-off lookup, single-line edit, exploratory read with no findings) → don't bother; chat history is enough
- The session ended with a closed §N workstream or completed Today's-Scope picks → the Task Completion Ritual already stubbed those; `/session-wrap` would be redundant unless there are also Notes / Learnings

## Related

- [[skill-daily-wrap|/daily-wrap]] — the EOD reconciler this skill complements
- [[skill-daily-scope|/daily-scope]] — the morning planning ritual
- [[mark-todos]] — read but never modified by this skill
- `topics/personal-notes/notes/daily/README.md` — daily-note convention reference
