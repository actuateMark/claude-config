---
name: todos-audit
description: Deeper periodic audit of mark-todos — stale workstreams, orphaned Jira tickets, workstreams without tickets, priority drift, duplicate sections, missing sub-tasks, stale frontmatter. Read-only by default with interactive follow-up to fix. Run weekly or on-demand. Trigger on "todos audit", "audit todos", "review todos", "check workstreams", "/todos-audit".
user-invocable: true
allowed-tools:
  - Read
  - Glob
  - Grep
  - Bash
  - Edit
  - AskUserQuestion
---

# Todos Audit

Periodic health-check for [[mark-todos]]. Answers: is this list telling the truth? Is anything drifting? Is anything missing?

**Read-only by default.** Surfaces findings and offers interactive fixes — never mutates without confirmation.

## Arguments

Mode flags use `--flag` form.

- No args (typical): full audit, all checks
- `--fast`: skip slow checks (ticket cross-reference via Jira MCP)
- `--fix`: after reporting, offer to fix each finding interactively

## Checks

### 1. Stale workstream movement

For each `§N` workstream in mark-todos, check the git log of mark-todos.md via `git blame` (if the KB is a git repo) OR look at the frontmatter `updated:` on any linked concept/synthesis notes. Flag workstreams with no evident activity in >14 days.

### 2. Orphaned Jira tickets

For each ticket in the auto-synced Jira queue (between `<!-- BEGIN-AUTOSYNC-JIRA -->` sentinels), check whether it's mentioned in any workstream's `**Tickets:**` line or an `*(tracked in §N)*` annotation. Flag tickets not mapped to any workstream.

### 3. Workstreams without tickets

Inverse of #2: any `§N` with no `**Tickets:**` entry? Either add the ticket or confirm this workstream is speculative/pre-ticket.

### 4. In-flight branches not mapped

Run the same branch survey as [[skill-daily-scope]] Step 1. Flag any feature branch (not `main`/`stage`/`develop`) that isn't mentioned in any workstream.

### 5. Priority drift

For each mapped ticket, compare the workstream's positioning (§1 = current focus) against Jira priority. Flag if a Highest-priority ticket is in §4 while a Medium-priority is in §1 — may indicate a re-prioritization is due.

### 6. Duplicate / overlapping sections

Grep for sections that reference the same core ticket or repo. Flag for human review (don't auto-merge — may be intentional parallel tracks).

### 7. Missing sub-tasks

For each workstream, check that the `### Subtasks` or equivalent checklist exists and has at least one item. A workstream with no actionable bullets is a signal of incomplete planning.

### 8. Stale frontmatter

- mark-todos.md `updated:` should be within 3 days (discipline)
- Linked concept/synthesis notes with `updated:` >30 days may be stale context

### 9. Archive consistency

Every row in `## Archive` should link to an existing daily note in `topics/personal-notes/notes/daily/`. Flag broken links.

### 10. Today's Scope hygiene

The `## Today's Scope` section's date should be today or yesterday. If older, [[skill-daily-wrap|/daily-wrap]] has been missed — surface this loudly.

## Procedure

1. Run all checks in parallel where possible.
2. Produce a categorized report. Group by severity:
   - **Critical:** broken archive links, missing wrap, stale-sync >7 days
   - **Warning:** stale workstreams, orphaned tickets, branches not mapped
   - **Info:** priority drift, missing sub-tasks, stale linked notes
3. If `--fix` argument: for each finding, offer an interactive fix.
   - "Map AUTO-XYZ to which workstream?" → `AskUserQuestion`
   - "Rename workstream §3?" → `AskUserQuestion`
   - "Archive §2c since its ticket is Done?" → `AskUserQuestion` (hands off to [[skill-daily-wrap|/daily-wrap]] for the archival move)

## Rules

- **Read-only by default.** Even in `--fix` mode, every mutation requires explicit user confirmation.
- **Don't solve what you can't verify.** If a check has false-positive potential (e.g., priority drift), report it as Info, not Warning.
- **Respect the discipline note** in mark-todos.md. The user has stated the conventions — reinforce them, don't override.
- **Limit Jira MCP calls.** Use one bulk query (the existing auto-synced queue), not per-ticket.

## Related

- [[skill-daily-scope]] — runs a light audit inline
- [[skill-daily-wrap]] — owns the archive mutation
- [[skill-todos-add]] — for adding a workstream identified as missing
- [[mark-todos]] — the file this skill audits
- [[automation-jira-sync]] — source of the ticket queue
