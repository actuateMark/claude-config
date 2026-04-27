---
name: release
description: Release this session's claim from the shared session-claims table in mark-todos.md. Run when finishing work or switching scope. Removes the row whose CWD matches current session's CWD (or the row matching an explicit label arg). Trigger on "/release", "release claim", "done with this session".
user-invocable: true
allowed-tools:
  - Read
  - Edit
  - Bash
---

# /release — remove this session's claim

Remove a row from the session-claims table in mark-todos.md.

## When to use

- Finishing a claimed scope (work is done, about to `/clear` or close session)
- Switching scope substantially and re-claiming with a new label
- Cleaning up after a crashed or abandoned session

## Arguments

`/release` — with no args, removes the row whose `CWD` matches `$PWD`.
`/release <label>` — removes the row with the given label (use this if cleaning up a stale claim from another session).

## Procedure

1. **Read mark-todos.md** — locate the `<!-- BEGIN-SESSION-CLAIMS -->` block.

2. **Find the target row:**
   - No arg: match by `CWD == $PWD`
   - Label arg: match by `Label == <arg>`

3. **Remove the row.** If this leaves the table with no data rows, restore the placeholder row `| *(none claimed)* | | | | |`.

4. **Report** — print the removed row's label + scope and confirm the release.

## Edit mechanics

Use `Edit` tool on mark-todos.md:

- `old_string` = the matched row line (include trailing newline context as needed for uniqueness)
- `new_string` = empty (if other rows remain) or the placeholder row (if this was the last)

Path: `/home/mork/Documents/worklog/knowledgebase/topics/personal-notes/notes/entities/mark-todos.md`

If multiple rows match (same CWD has two claims — shouldn't happen but defend against it), prompt the user which to release.

## Edge cases

- **No matching row** — report "no active claim for this CWD" and exit without error.
- **Placeholder-only table** — nothing to remove; exit without error.

## Related

- `/claim` — register a session
- `/claims` — view the current table
