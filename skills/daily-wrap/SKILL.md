---
name: daily-wrap
description: End-of-day companion to /daily-scope. Interviews which items from Today's Scope closed, writes the day's daily note with summaries, archives fully-completed workstream sections, updates mark-todos. Trigger on "daily wrap", "wrap up day", "end of day", "log today", "/daily-wrap".
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

End-of-day ritual. Turns the day's scope into a permanent archive entry and clears the slate for tomorrow.

**Non-destructive by design.** Nothing is ever deleted — completed items move to that day's daily note with a summary; their mark-todos checklist row is removed only after the daily note is written and verified.

## Arguments

Mode flags use `--flag` form; positional args are reserved for primary subjects (dates here).

- No args (typical): run the full wrap ritual
- `--preview`: show what would be written to the daily note, but don't write or modify mark-todos
- `YYYY-MM-DD` (positional): wrap a specific date (use when catching up on a missed wrap)

## Procedure

### Step 1 — Load today's state

Read the `## Today's Scope` section of `/home/mork/Documents/worklog/knowledgebase/topics/personal-notes/notes/entities/mark-todos.md`. Capture the date from the heading. Also list session `TaskList` entries — useful for cross-check but mark-todos is source of truth.

If the Today's Scope date is not today (e.g., user ran `/daily-wrap YYYY-MM-DD` for an older day), confirm they want to wrap that specific date.

### Step 1.5 — Scan the broader day (captures work outside Today's Scope)

Today's Scope is necessary but not sufficient. Other sessions (see `## Active Session Claims`), ad-hoc investigations, and mid-day KB refinements can produce closed-worthy work that never appeared in scope. Before interviewing, collect the full picture:

**A. Recently-modified KB notes** — delegate the mechanical listing to [[skill-kb-recap|/kb-recap]]:

```
/kb-recap
```

That skill returns a categorized markdown list grouped by note type (source / concept / synthesis / entity / summary / reading-list / daily / staging / inbox / other) with new-vs-edited markers. It already excludes `.obsidian/.git/.trash` noise and automated jira-sync/overnight-check outputs.

Once the list is back, do three things with it:

1. **Cross-reference against the daily note's existing `## Closed Line Items`.** For each file in the recap that ISN'T already mentioned → it's a candidate mid-day write that the Task Completion Ritual didn't stub. Surface during Step 2 interview: *"`<note slug>` was touched today but isn't in closed-items — should I add a bullet?"*
2. **Classify authored vs sibling-session.** The skill can't distinguish who wrote what; you must. Cross-check against the `## Active Session Claims` block + your own session's tool-call history (Edit/Write calls to those paths). Files this session wrote → go into the interview as "did you want this as a closed item?"; files sibling-session wrote → covered in Step 1.5.B below.
3. **Spot linter-only touches.** Files with a post-skill-run mtime but no real diff (Obsidian linter bumping `updated:` frontmatter, wikilink-path normalization) should be de-prioritized. When in doubt, `Read` the file and compare against your session's memory.

**B. Active session claims.** Read the `## Active Session Claims` block. For each claim whose CWD is not this session's CWD: its scope describes what another Claude was working on today — ask the user whether that work produced closed items this wrap should record. (This is the only proxy for cross-session activity; we can't read another session's transcript. If the user confirms, they supply the summary.)

**C. Repo activity** (best-effort, fast). For each repo the user has been active in today, surface commits with today's date:

```bash
for repo in /home/mork/work/*/; do
  cd "$repo" 2>/dev/null || continue
  commits=$(git log --since="$TODAY 00:00" --author="$(git config user.name)" --oneline 2>/dev/null)
  [ -n "$commits" ] && echo "== $(basename "$repo") ==" && echo "$commits"
done
```

Surface commits that aren't already reflected in the daily note's closed items or existing `mark-todos` `- [x]` rows. These may be sub-tasks of a larger closed item (keep collapsed) or standalone work that needs its own bullet.

**Budget:** this whole step should take ≤1 minute. If a repo scan is slow (huge `.git`), skip it — the goal is catching obvious omissions, not exhaustive audit.

### Step 2 — Interview per line item

For each unchecked line item, ask:
1. **Status:** Closed / deferred to tomorrow / blocked / de-scoped
2. **If closed:** ask for a 1-2 sentence summary (what changed, any PR/ticket links, anything learned)

Use `AskUserQuestion` with 4-status options (Closed, Deferred, Blocked, De-scoped). The free-form summary goes into notes.

**Question headers (user preference, 2026-04-21):** lead each question with a short `header` ≤12 chars that uses a ≤5-word item title (e.g. `header: "§3 cleanup"`, question leads with the title: *"§3 cleanup Lambda stage verification — ..."*). Don't lead with `§N` alone; don't write the full sentence as the header. Same applies to any follow-up option labels — ≤5 words each.

For items with status `Closed`, also ask a follow-up: **did this close a whole workstream (§N)?** If yes, mark the workstream for archival in Step 4.

### Step 2.5 — Diagnosis / TODO completeness cross-check

For each closed line item that references an external issue, bug, or KB concept note — verify that the daily note's summary captures **both** the discovery AND the diagnosis/root cause (not just "found X"). And verify that any follow-up TODOs the KB note records were mirrored into:
- the relevant `§N` section of mark-todos (as open sub-tasks), AND
- the Deferred-to-tomorrow list if they're short-horizon actions

Common failure mode: a mid-day KB concept note is written with a full fix recipe, but the daily-note stub only records the discovery headline and the deferred list rolls forward only §N scope items — so the concrete TODOs from the KB note never surface in tomorrow's `/daily-scope` pool. Catch this here.

If a gap is found, add the missing TODO bullets to mark-todos (either in the §N section or the carry-over) and expand the daily note summary to mention the diagnosis. Don't re-write the whole KB note; a one-sentence diagnosis summary + link is enough.

### Step 3 — Write / reconcile the daily note

The daily note at `topics/personal-notes/notes/daily/YYYY-MM-DD.md` may already exist — the Task Completion Ritual in global CLAUDE.md appends stub entries progressively through the day. Detect whether the file already exists:

- **File exists (stub mode):** *reconcile*, don't overwrite. Merge the interview results into the existing file:
  - `## Closed Line Items`: pre-existing bullets are already the source of truth for items closed mid-day — keep them, only add bullets for items the interview surfaced that weren't already there, and normalize format if needed.
  - `## Summary`: fill in the placeholder now (auto-summarize from closed items or ask user for a one-liner).
  - `## Notes / Learnings`: append anything the user wants to add; don't overwrite existing freeform content.
  - `## Closed Workstreams`: populate in Step 4 if any workstream archival.
  - Bump frontmatter `updated:` to today.
- **File does not exist:** create it fresh using the template from `topics/personal-notes/notes/daily/README.md` with all sections populated from the interview.

Frontmatter per README template (type: concept, topic: personal-notes, tags: [daily, wrap]).

### Step 4 — Archive closed workstreams (if any)

For each workstream §N the user confirmed is complete:
1. Copy the full `§N` section text from mark-todos.md into the daily note under `## Closed Workstreams`
2. Remove the `§N` section from mark-todos.md
3. Add a pointer row to mark-todos's `## Archive` table:
   ```markdown
   | YYYY-MM-DD | §N Title | [[YYYY-MM-DD]] |
   ```
4. Renumber subsequent workstreams if maintaining sequential §N numbering matters — **ask the user first** before renumbering (may break external references).

### Step 5 — Update mark-todos Today's Scope

In the `## Today's Scope` section:
- **Closed items:** remove the line (archival is complete in the daily note)
- **Deferred items:** leave unchecked with a `*(deferred to YYYY-MM-DD)*` qualifier, or move to a new `## Carry-Over` section below Today's Scope
- **Blocked items:** leave unchecked, add `*(blocked: <reason>)*` qualifier
- **De-scoped items:** remove (and optionally note in the daily note's Notes section why)

Bump mark-todos frontmatter `updated:` to today.

### Step 5.5 — Persist handoff notes to the KB (carry-forward work)

For each **deferred** or **blocked** item with non-trivial carry-forward context (what was tried, what's next, gotchas, file paths, ticket IDs — anything the next session will need to resume without re-discovering), write a durable handoff note into the KB. Do NOT rely on chat transcript or trailing session prose — that has been lost between sessions before.

**Where it goes (in priority order):**
1. **Existing workstream concept/synthesis note** → append a `## Handoff (YYYY-MM-DD)` section at the bottom. Preferred when the workstream already has a doc.
2. **New concept note** at `topics/<relevant-topic>/notes/concepts/YYYY-MM-DD_handoff-<slug>.md` with frontmatter (`type: concept`, `tags: [handoff]`, link to the §N workstream) — when there's no existing doc to attach to.
3. **Never** only in the daily note's Notes section for a tracked §N item — the daily note is a diary, not a discoverable handoff. The daily note can *link* to the handoff, but the handoff content lives in the workstream topic.

**What the handoff must contain:**
- Entry point: which file / doc / section to read first
- What state the work is in (files touched, branches open, PRs in flight)
- What's next: 2–4 concrete steps
- Gotchas / decisions-pending
- Links: related workstream §N, Jira ticket, PRs

**Link from mark-todos:** on the deferred/blocked line in `## Today's Scope` and in the relevant §N section, add a wikilink to the handoff note so the next session's Session Start ritual surfaces it:

```markdown
- [ ] §N Foo work *(deferred to 2026-04-24; handoff: [[2026-04-23_handoff-foo-sketch-init]])*
```

Skip only for trivially-resumable items (one-line TODOs, obvious mechanical work).

### Step 6 — Update session tasks (best-effort)

For each corresponding session `TaskCreate`, call `TaskUpdate` to mark `completed`. Deleted / de-scoped items → `deleted`. This is cosmetic since the session may end soon, but it's clean.

### Step 7 — Confirm

Summarize:
- File written: `topics/personal-notes/notes/daily/YYYY-MM-DD.md`
- N items closed, M deferred, K workstreams archived
- Any dangling items the user should address tomorrow

## Rules

- **Never delete history.** Closed items live forever in the daily note; only their Today's Scope row is removed.
- **Write the daily note before mutating mark-todos.** If daily-note write fails, abort — don't leave an inconsistent state.
- **Renumbering workstreams requires explicit user confirmation.** §N numbers may be referenced externally (Jira comments, KB notes).
- **Catch-up mode (`YYYY-MM-DD` arg)** is for missed wraps — use when user realizes they didn't wrap yesterday. Don't infer backwards without explicit user ask.
- **Scope is a floor, not a ceiling.** The wrap must capture the day's actual work, not just what was in Today's Scope. Honor Step 1.5 — surface KB-note deltas, other-session claims, and repo commits. Omissions found later (e.g., "you never logged the diagnosis, only the discovery") indicate Step 1.5 was skipped.
- **Diagnosis ≠ discovery.** For closed investigation/bug items that produced a KB concept note with root cause + fix recipe, the daily-note summary must reflect the diagnosis, not just the headline. Follow-up TODOs from the KB note must land in either the `§N` section or the Deferred-to-tomorrow list (Step 2.5).
- **Carry-forward belongs in the KB, not in chat.** Every deferred/blocked item with non-trivial context gets a handoff note persisted to the KB and wikilinked from mark-todos (Step 5.5). A handoff lost between sessions on 2026-04-23 caused the next session to pick up the wrong task; treat this as a hard rule, not a nice-to-have.

## Related

- [[skill-daily-scope]] — morning counterpart
- [[skill-todos-audit]] — weekly deeper audit
- [[mark-todos]] — file this skill mutates
- `topics/personal-notes/notes/daily/README.md` — daily-note convention
