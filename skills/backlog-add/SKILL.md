---
name: backlog-add
description: Quick-capture an outstanding Jira ticket, GH issue, or ad-hoc item into the appropriate KB backlog doc without going through the full /todos-add ritual. For "I want to track this but not promote to mark-todos yet." Trigger: '/backlog-add', 'add to backlog', 'queue this'.
user-invocable: true
allowed-tools:
  - Read
  - Edit
  - Write
  - Glob
  - Grep
  - Bash
---

# Backlog Add

Lightweight capture-into-backlog flow. Scoped narrower than [[skill-todos-add|/todos-add]]: doesn't create a new mark-todos §N, doesn't survey related context — just appends a tracked entry to the right backlog doc with enough metadata to revive later.

## When to use

- A Jira/GH issue surfaces that isn't ready to triage but shouldn't disappear (e.g. customer-reported bug whose repro isn't clear; an issue assigned to you that's blocked on someone else; a refactor opportunity surfaced during code review).
- A morning fan-out finding that's actionable but lower-priority than today's picks.
- A "we should investigate this" thought during a coding session.
- A peer-mentioned item that needs to land somewhere durable.

**Don't use** for items that should be active scope today — those go via [[skill-todos-add|/todos-add]] or directly into Today's Scope. Don't use for items already archived (write a restoration synthesis if reviving).

## Arguments

- *(none)*: interactive flow
- `<jira-key>` (e.g. `AUTO-568`): pre-fill from Jira via Atlassian MCP
- `<gh-url>` (e.g. `https://github.com/aegissystems/vms-connector/issues/1656`): pre-fill from GH via `gh issue view`
- `--topic <slug>`: skip topic-pick step, route directly into that topic's backlog doc

## Procedure

### Step 1 — Discover registered backlog docs

Read `mark-todos.md` frontmatter for `backlog:` field. Then grep:

```bash
ls /home/mork/Documents/worklog/knowledgebase/topics/*/notes/entities/ | grep -E '(deferred-backlog|-backlog)\.md$'
```

Build list of `{topic, doc-path, last-updated}`. If the requested item is topic-relevant to none of the existing docs, offer to create a new `<topic>-deferred-backlog.md` modeled on [[autopatrol-deferred-backlog]].

### Step 2 — Pull source metadata

If `<jira-key>` provided: fetch via `mcp__atlassian__getJiraIssue`. Extract: summary, status, priority, type, reporter, assignee, last-updated.

If `<gh-url>` provided: `gh issue view <url> --json number,title,body,labels,state,createdAt,updatedAt,assignees`. Extract: title, labels, state, age, assignee.

If neither: interactive — ask user for one-liner title + 1-3 sentence context.

### Step 3 — Pick destination doc

Use `AskUserQuestion` with the candidate backlog docs as options + "create new". Pre-select the doc whose topic best matches the source (heuristic: scan source title/body for topic-tag keywords).

### Step 4 — Compose the entry

Backlog entry shape (matches [[autopatrol-deferred-backlog]] convention):

```markdown
- [Item title](#item-title-anchor) | source-§N or source-ticket | wait | decision-owner | re-open trigger
```

Plus a body section keyed by the same anchor:

```markdown
## Item title

**Status:** Why deferred (1 sentence).

**Why deferred:** what's blocking, who owns, what's the non-trivia.

**Re-open trigger:** specific signal that pulls this back to active scope.

**Open work (when revived):** ...

**Resources:** Jira ticket, GH issue, KB notes, prior commits.
```

### Step 5 — Edit the doc

- Append the index row (if the doc has an Index table).
- Append the body section at end-of-doc.
- Bump frontmatter `updated:`.
- If the entry references KB notes, add a backlink in those notes' `incoming:` lists (best-effort; skip if it would mean editing 5+ unrelated files).

### Step 6 — Confirm

One-line summary: "Added '<title>' to <doc>. Re-open when: <trigger>."

## Rules

- **Never edit `mark-todos.md`** — that's the active surface; `/todos-add` owns it.
- **Never auto-create §N** — if the item deserves active scope, redirect user to `/todos-add` instead.
- **Always include a re-open trigger.** Without one, items rot. If the user can't articulate one, ask: "what would have to be true for you to come back to this?"
- **Don't backlog stuff that's already archived.** Closed-with-decision items live in daily notes / Archive table. Reviving means write a restoration synthesis explaining what changed.
- **Limit one item per invocation.** Bulk-import is a different (future) skill.

## Backlog-doc shape contract

Canonical shape that both this skill (producer) and [[skill-daily-scope|/daily-scope]] Step 2d (consumer) depend on.

**Path:** `topics/<topic>/notes/entities/<topic>-deferred-backlog.md` (or `<topic>-backlog.md`).

**Frontmatter:**

```yaml
---
title: "<Topic Title> Deferred Backlog"
type: entity
topic: <topic>
tags: [<topic>, backlog, deferred, mark, work-plan]
created: YYYY-MM-DD
updated: YYYY-MM-DD
author: kb-bot
---
```

**Required sections (in order):**

1. **Intro paragraph** — defines what this backlog holds (deferred items, decision pending, etc.)
2. **`## Index` table** — required for `/daily-scope` to mechanically parse. Columns: `Item | Source §N | Status | Decision Owner | Decision Trigger`. Item links via anchor to the per-entry section below.
3. **Per-entry sections** (one per row in the Index) with the body shape from Step 4 above. Each MUST include a `**Re-open conditions:**` (or `**Re-open trigger:**`) subheading enumerating concrete triggers.

**Anchors:** GitHub-flavored — lowercased, spaces→hyphens, punctuation stripped. Always cross-check the index links against the section headers when editing.

**Hint to `mark-todos`:** add a `backlog:` field to mark-todos frontmatter pointing to the primary backlog doc; that's `/daily-scope`'s preferred discovery path before falling back to glob.

Without this shape, `/daily-scope` Step 2d's parsing falls back to "list candidates by filename only," and ranking degrades to "ask user."

## Discipline

The `/daily-scope` Step 2d step surfaces backlog candidates when active scope is light. That's the consumer side. This skill is the producer side. Together they prevent two failure modes:

1. **The chat-only graveyard** — items mentioned in conversation that never make it to a tracked surface.
2. **The mark-todos bloat** — items added to mark-todos as §N that never get worked because they were always low-priority.

A healthy backlog turns over: items either get re-promoted (their trigger fired) or get explicitly closed-with-decision (no longer relevant; written into a topic synthesis as historical context).

## Related

- [[skill-daily-scope|/daily-scope]] — consumer of backlog docs (Step 2d)
- [[skill-todos-add|/todos-add]] — the heavier "add a §N" flow
- [[skill-todos-audit|/todos-audit]] — periodic audit; flags overgrown backlogs
- [[autopatrol-deferred-backlog]] — first registered backlog doc (template)
- [[mark-todos]] — frontmatter `backlog:` is the discovery hint
