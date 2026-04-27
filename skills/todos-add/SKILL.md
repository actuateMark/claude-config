---
name: todos-add
description: Interactive scaffold for adding a new workstream section to mark-todos. Asks for title, tickets, status, priority, checklist, cross-refs; inserts at the right §N position with format consistent with existing sections. Trigger on "todos add", "add workstream", "add todo", "new workstream", "/todos-add".
user-invocable: true
allowed-tools:
  - Read
  - Edit
  - AskUserQuestion
---

# Todos Add

Adds a new workstream section to [[mark-todos]] with the right format, numbering, and cross-references. Keeps the file's convention from drifting when a workstream is added in-the-moment during a session.

## Arguments

Positional args are reserved for the primary subject (title phrase here).

- No args (typical): interview for all fields
- `"title phrase"` (positional, quoted): e.g., `/todos-add "PyAV upgrade blocker"` — pre-populates the title and skips that question

## Procedure

### Step 1 — Interview

Use `AskUserQuestion` (or a sequence) to collect:

1. **Title** — short, outcome-oriented (e.g., "PyAV upgrade 13.1 → 17.0")
2. **Priority** — current focus / this-week / this-month / backlog
3. **Status** — in progress / not started / blocked / design phase
4. **Tickets** — comma-separated Jira keys if any (or "none — pre-ticket")
5. **Is this gated on another workstream finishing first?** — if yes, which §N

### Step 2 — Pre-populate from context

Before writing, look for:
- **Branches referencing the topic** — `git branch` across working repos; if found, include in the workstream as "Branch: ..." line
- **Existing KB notes** — `grep` for the topic in KB; auto-link in the Related section

### Step 3 — Insert at the right position

Read mark-todos.md. Determine the insertion point based on priority:
- **current focus** → §1 (everything else shifts down by 1)
- **this-week** → after current-focus, before speculative items
- **this-month** / **backlog** → after this-week items

**If renumbering is required** (because everything shifts down), ask the user first — §N numbers may be referenced in external places (Jira comments, PR descriptions). Default to appending at the end if the user is unsure.

### Step 4 — Format the section

Use this template, adapted from existing sections:

```markdown
## N. <Title>

**Priority:** <priority>
**Tickets:** <tickets or "pre-ticket">
**Status:** <status>
<optional: **Blocked by:** §M>

### What's left
<or ### Design surface / ### Subtasks depending on status>

- [ ] First concrete next step
- [ ] ...

### Relevant KB

- [[<linked-note-1>]] — why this is relevant
- [[<linked-note-2>]]

### Related

- Any cross-references to other workstreams or skills
```

### Step 5 — Update cross-references

- Bump mark-todos.md frontmatter `updated:`
- If the new workstream has tickets that were previously orphaned in the Jira queue, no action needed — the next auto-sync will add the `*(tracked in §N)*` annotation automatically (see [[automation-jira-sync]] behavior).

### Step 6 — Confirm

Show the rendered section to the user; offer a last chance to edit before committing the change.

## Rules

- **Never renumber without explicit confirmation.** §N numbers may be externally referenced.
- **Don't skip the KB cross-link search.** Orphaned workstreams (no KB context) are a signal of under-planning.
- **One workstream at a time.** If the user wants to add two, run the skill twice — keeps the interview quality high.
- **Respect the mark-todos section format.** Sub-heading varies by phase: `### What's left` (active work), `### Pre-implementation plan` (design-phase), `### Design surface` (open questions), `### Subtasks` (spec'd). Match what existing sections do for workstreams at the same phase.

## Related

- [[skill-daily-scope]] — daily picker (uses workstreams added here)
- [[skill-todos-audit]] — flags workstreams without tickets / without sub-tasks
- [[skill-daily-wrap]] — owns archival/deletion, not this skill
- [[mark-todos]] — the file this skill writes to
