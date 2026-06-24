---
name: claims
description: Print the session-claims table from mark-todos.md. Flags overlaps with current CWD; highlights stale heartbeats. Trigger: '/claims', 'show claims'.
user-invocable: true
allowed-tools:
  - Read
  - Bash
---

# /claims — view the session-claims table

Print the BEGIN/END-SESSION-CLAIMS block from mark-todos.md, with annotations on:

- Rows where `CWD == $PWD` (this session overlaps)
- Rows where heartbeat is >30 min old (potentially idle / crashed)
- Rows where heartbeat is >2h old (will be auto-pruned on next SessionStart)

## Procedure

1. Read mark-todos.md and extract the `<!-- BEGIN-SESSION-CLAIMS -->` … `<!-- END-SESSION-CLAIMS -->` block.
2. Get current CWD from `pwd` and current UTC time from `date -u +%Y-%m-%dT%H:%MZ`.
3. For each data row, compute:
   - Age of heartbeat (current time − heartbeat)
   - Whether CWD matches `$PWD`
4. Print the table as-is, then append a short annotations section:
   - ⚠️ Same-CWD overlap: list any rows where CWD matches $PWD
   - 🟡 Stale (>30 min): list rows where heartbeat is >30 min old
   - 🔴 Will be pruned (>2h): list rows scheduled for auto-cleanup

## Output shape

```
Active session claims (from mark-todos.md):

| Label | Scope | CWD | Started | Heartbeat |
|-------|-------|-----|---------|-----------|
| lambda-e2e | §3 §9 cleanup Lambda stage verify | /home/mork/work/autopatrol_onboarder | 2026-04-20T15:03Z | 2026-04-20T15:40Z |
| docs-sweep | §1 v5 per-model docs | /home/mork/work/actuate-inference-api | 2026-04-20T15:20Z | 2026-04-20T15:58Z |

Annotations:
- Current CWD: /home/mork/work (no overlap with any claim)
- No stale rows.
```

## Related

- `/claim` — register this session
- `/release` — remove this session's claim
