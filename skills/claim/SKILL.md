---
name: claim
description: Claim a scope in the shared session-claims table so other concurrent Claude Code sessions see it and avoid duplicate work. Writes a row to the BEGIN/END-SESSION-CLAIMS block in mark-todos.md with label, scope, cwd, start time, and heartbeat. Use at the start of any non-trivial session that will work on a tracked §N workstream item. Trigger on "/claim", "claim scope", "register session".
user-invocable: true
allowed-tools:
  - Read
  - Edit
  - Bash
  - AskUserQuestion
---

# /claim — register this session's scope

Record in the shared session-claims table that this session is working on a specific scope, so other concurrent Claude Code sessions won't pick the same thing up.

## When to use

- Starting a session that will spend >15 min on a tracked §N workstream item
- Working on a long-running deploy / stage verification in parallel with other work
- Whenever duplicate effort across sessions would be bad

Not needed for: trivial one-off lookups, read-only exploration, quick edits.

## Arguments

`/claim <label> <scope text...>`

- **label** — short kebab-case identifier, unique per active session (e.g. `lambda-e2e`, `docs-sweep`, `ebus-integration`)
- **scope** — free-form description referencing the §N workstream (e.g. `§3 §9 cleanup Lambda stage verify + observe`)

If no args: ask the user via AskUserQuestion for label + scope.

## Procedure

1. **Read mark-todos.md** — locate the `<!-- BEGIN-SESSION-CLAIMS -->` block.

2. **Validate label uniqueness** — if a row with this label already exists:
   - If the row's `CWD` matches `$PWD` (same session re-claiming): update its scope and heartbeat, then exit.
   - Otherwise: abort and tell the user "label X is taken by CWD Y; pick a different label or `/release` the other first."

3. **Append row to the table:**

   Schema (5 cols): `| Label | Scope | CWD | Started | Heartbeat |`

   Timestamp format: `YYYY-MM-DDTHH:MMZ` (UTC, minute precision). Use `date -u +%Y-%m-%dT%H:%MZ` via Bash.

   Started and Heartbeat both get `now` on first claim.

   CWD is `$PWD` (from `pwd`).

4. **Drop the placeholder row** — if the only current row is `*(none claimed)*`, replace it with the new data row (don't leave the placeholder alongside real rows).

5. **Report** — print the added row and how many other active claims exist.

## Edit mechanics

Use the `Edit` tool on mark-todos.md. To avoid matching the wrong row:

- For the first real claim (table currently shows placeholder): `old_string` = the placeholder row line, `new_string` = your new data row.
- For subsequent claims: `old_string` = the last existing data row, `new_string` = that row + newline + your new row.

Path: `/home/mork/Documents/worklog/knowledgebase/topics/personal-notes/notes/entities/mark-todos.md`

## Example

Input: `/claim lambda-e2e §3 §9 cleanup Lambda stage verify + observe`

Resulting row:
```
| lambda-e2e | §3 §9 cleanup Lambda stage verify + observe | /home/mork/work/autopatrol_onboarder | 2026-04-20T15:03Z | 2026-04-20T15:03Z |
```

## Related

- `/release` — remove this session's claim when done
- `/claims` — view the current table
- SessionStart hook prunes rows with heartbeat >2h stale
- Stop hook updates heartbeat for the row whose CWD matches current session's CWD
