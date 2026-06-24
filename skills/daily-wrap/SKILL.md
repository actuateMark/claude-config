---
name: daily-wrap
description: End-of-day companion to /daily-scope. Interviews which items closed, writes daily note with summaries, archives completed workstreams, updates mark-todos. Trigger: '/daily-wrap', 'end of day'.
user-invocable: true
allowed-tools:
  - Read
  - Glob
  - Grep
  - Bash
  - Edit
  - Write
  - TaskList
  - TaskUpdate
  - AskUserQuestion
---

# Daily Wrap

End-of-day ritual. Turns Today's Scope into a permanent archive entry; clears the slate.

**Non-destructive.** Closed items move to that day's daily note; their mark-todos row is removed only after the daily note is written. Rolling-forward convention (CLAUDE.md): mark-todos holds open work only; closed `[x]` sub-items move to the daily note's `## Closed Sub-items`.

## Arguments

- *(none)*: full wrap
- `--preview`: show what would be written; don't write or mutate
- `YYYY-MM-DD`: wrap a specific past date (catch-up)

## Procedure

### Step 1 — Load today's state

Read `## Today's Scope` from `topics/personal-notes/notes/entities/mark-todos.md`. Capture date from heading. Cross-check with `TaskList`. If the arg is a non-today date, confirm.

### Step 1.5 — Scan the broader day

Today's Scope is necessary but not sufficient. Other sessions, ad-hoc investigations, and mid-day KB writes produce closed-worthy work. Budget ≤1 minute.

**A. Recently-modified KB notes** — invoke `/kb-recap`. For each file in the recap not already in the daily note's `## Closed Line Items`: surface in Step 2 interview ("`<note slug>` touched today but not closed — add a bullet?"). Cross-check authored vs sibling-session via `## Active Session Claims` + this session's Edit/Write history. De-prioritize linter-only touches (frontmatter `updated:` bumps without real diff).

**B. Active session claims.** Read `## Active Session Claims`; for each non-CWD claim, ask the user whether that work produced closed items.

**C. Repo activity** (best-effort, fast):
```bash
for repo in /home/mork/work/*/; do
  cd "$repo" 2>/dev/null || continue
  commits=$(git log --since="$TODAY 00:00" --author="$(git config user.name)" --oneline 2>/dev/null)
  [ -n "$commits" ] && echo "== $(basename "$repo") ==" && echo "$commits"
done
```
Surface commits not reflected in closed items. Skip slow scans.

### Step 2 — Interview per line item

For each unchecked line, ask via `AskUserQuestion`:
1. **Status:** Closed / Deferred / Blocked / De-scoped
2. **If closed:** 1-2 sentence summary (PR/ticket links, learnings)

**Question header convention** (≤12 chars, ≤5-word title): `header: "§3 cleanup"`, question leads with title — *"§3 cleanup Lambda stage verification — ..."*. Don't lead with `§N` alone. Same for option labels.

For closed items, follow up: did this close the whole §N workstream? If yes → mark for Step 4 archival.

### Step 2.7 — Sweep `[x]` sub-items out of mark-todos

**Critical step. Prevents mark-todos re-bloat.** Run between Step 2 and Step 3.

1. Find every `- [x]` line inside a §N section (not inside sentinel-managed blocks).
2. Attribution:
   - **Today's wrap (typical):** move bullet verbatim (with nested context + indentation) to today's daily note `## Closed Sub-items`, grouped by `**§N — <title>:**`.
   - **Old `[x]` from a missed wrap (rare):** batch into today's `## Closed Sub-items` with `*(swept YYYY-MM-DD; closed earlier)*`. Don't back-distribute. Surface in wrap report.
3. Remove the `[x]` line from mark-todos; preserve workstream structure.
4. Sub-trees with still-open `[ ]` nested bullets stay put.
5. Whole-workstream archival is Step 4, not here.

Output format in the daily note:

```markdown
## Closed Sub-items

*Granular `[x]` checklist items closed today, swept from `mark-todos.md` on YYYY-MM-DD.*

**§3 — New Lambda — AutoPatrol stale-schedule cleanup:**

- [x] Step E.3 — monitor 24-48h post-flip ... *(verbatim text)*

**§9 — Operational Dashboard (Phase 1b):**

- [x] Replay tests for 7 historical incidents — ... *(verbatim text)*
```

### Step 2.5 — Diagnosis / TODO completeness check

For each closed item that references an external bug or KB concept note: verify the daily-note summary captures **diagnosis**, not just discovery. Verify any follow-up TODOs from the KB note got mirrored into mark-todos §N or a Carry-Over.

Common failure: KB concept note has full fix recipe, but daily stub records only the headline → tomorrow's `/daily-scope` never sees the TODOs. If gap found: add bullets to mark-todos and expand the daily-note summary by one sentence + link.

### Step 3 — Write / reconcile the daily note

Daily note path: `topics/personal-notes/notes/daily/YYYY-MM-DD.md`. The Task Completion Ritual appends stubs through the day, so the file may already exist.

**File exists (stub mode) — reconcile, don't overwrite:**
- `## Closed Line Items`: keep existing bullets; add interview-surfaced ones not already there; normalize format.
- `## Closed Sub-items`: pre-existing stays; Step 2.7 may add more.
- `## Summary`: fill the placeholder (auto-summarize closed items or ask user).
- `## Notes / Learnings`: append; don't overwrite.
- `## Closed Workstreams`: populate in Step 4.
- Bump frontmatter `updated:`.

**File doesn't exist:** create from `topics/personal-notes/notes/daily/README.md` template.

**Frontmatter must include:**
- `tags: [daily, wrap]`
- `topics: [...]` — every KB topic touched (cross-reference key for `grep -l "topic: <name>"`).
- `workstreams: ["§N", ...]` — for "when did §3 see action?" queries.

When in doubt, over-tag.

### Step 4 — Archive closed workstreams

For each §N user confirmed complete:
1. Copy full §N text from mark-todos into daily note `## Closed Workstreams`.
2. Remove §N from mark-todos.
3. Add to mark-todos `## Archive` table: `| YYYY-MM-DD | §N Title | [[YYYY-MM-DD]] |`
4. Renumbering remaining §N: **ask first** — may break external references.

### Step 5 — Update mark-todos Today's Scope

- **Closed:** remove the line (archive done in daily note)
- **Deferred:** keep unchecked with `*(deferred to YYYY-MM-DD)*`, or move to `## Carry-Over` below Today's Scope
- **Blocked:** keep unchecked with `*(blocked: <reason>)*`
- **De-scoped:** remove (optional one-liner in daily note Notes)

Bump mark-todos `updated:`.

### Step 5.5 — Persist handoff notes to the KB

For each **deferred** or **blocked** item with non-trivial carry-forward context (what was tried, next steps, gotchas, file paths, tickets), write a durable handoff in the KB. **Don't rely on chat transcript** — that's been lost between sessions before.

**Where (priority order):**
1. Append `## Handoff (YYYY-MM-DD)` to the existing workstream concept/synthesis note.
2. New concept note: `topics/<topic>/notes/concepts/YYYY-MM-DD_handoff-<slug>.md` (`type: concept`, `tags: [handoff]`, link to §N).
3. **Never** only in the daily-note Notes section — daily is a diary, not a discoverable handoff.

**Must contain:** entry point (which file/section to read first), current state (files touched, branches, PRs), 2-4 concrete next steps, gotchas, links (§N, Jira, PRs).

**Wikilink from mark-todos:**
```markdown
- [ ] §N Foo work *(deferred to 2026-04-24; handoff: [[2026-04-23_handoff-foo-sketch-init]])*
```

Skip for trivially-resumable items.

### Step 6 — Update session tasks (best-effort)

`TaskUpdate` matching tasks → `completed` (or `deleted` for de-scoped).

### Step 7 — Confirm

Report: file written, N closed / M deferred / K archived, dangling items for tomorrow.

## Rules

- **Never delete history.** Closed items live in the daily note; only the Today's Scope row leaves.
- **Write the daily note before mutating mark-todos.** Abort on write failure.
- **Renumbering §N requires explicit user confirmation** (external refs).
- **Catch-up mode (`YYYY-MM-DD` arg)** is for missed wraps. Don't infer backwards.
- **Scope is a floor, not a ceiling.** Step 1.5 must run — surface KB deltas, sibling sessions, repo commits. Omissions found later = Step 1.5 was skipped.
- **Diagnosis ≠ discovery.** Daily-note summary for an investigation/bug must reflect root cause, not just the headline.
- **Carry-forward belongs in the KB.** Step 5.5 is non-optional for non-trivial deferred work.
- **Sub-item granularity matters.** Step 2.7 sweeps `[x]` items out. Skipping it is what caused the 2026-04-27 1219-line bloat. If `[x]` appears in tomorrow's `/daily-scope`, Step 2.7 was skipped.
- **Daily-note frontmatter must have `topics:` + `workstreams:`** for grep-based cross-topic queries.

## Related

- [[skill-daily-scope]] — morning counterpart
- [[skill-todos-audit]] — weekly audit
- [[mark-todos]]
- `topics/personal-notes/notes/daily/README.md`
