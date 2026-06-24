---
name: standup
description: Standup notes from KB daily notes. Default 'topic' mode produces the three-question standup format (yesterday/today/blockers) in conversational tone; 'detailed' mode produces 3-4 dense bullets with PR#/§N anchors. Read-only. Trigger '/standup', 'standup notes', 'what did I work on'.
user-invocable: true
allowed-tools:
  - Read
  - Bash
  - Glob
---

# /standup — standup notes from KB daily notes

Produce standup notes — by default in the **three-question format** (yesterday / today / blockers) the user actually sends to standup, conversational tone, no internal identifiers. A **detailed** mode produces dense paste-ready bullets with PR#/§N anchors instead, for async writeups.

Synthesizes from `## Summary` + `## Closed Line Items` (+ `## Closed Sub-items`) in KB daily notes at `topics/personal-notes/notes/daily/`, plus mark-todos for today's plan + blockers.

## When to use

- Morning standup prep — what you did, what you're doing, what's blocked
- Coming back from time off — what was I doing before I left?
- Async-update writing — paste-ready bullets, no editing (use `detailed` mode)

Read-only. No edits, no claims, no daily-note writes.

## Invocation

```
/standup                       # topic mode (default), most recent prior daily note
/standup detailed              # dense 3-4 bullets w/ anchors, yesterday only
/standup 2026-05-12            # topic mode for that specific date
/standup yesterday             # today minus 1 day (strict)
/standup 3d                    # last 3 days as one consolidated standup
/standup since 2026-05-09      # range from date through most recent
/standup detailed 3d           # detailed-mode + range
```

`detailed` is a positional flag that may appear anywhere. Everything else is a date selector.

## Procedure

### 1. Resolve target date(s)

Daily notes live at `topics/personal-notes/notes/daily/YYYY-MM-DD.md` (relative to `/home/mork/Documents/worklog/knowledgebase/`).

| Arg | Resolution |
|-----|------------|
| (none) | Most recent file in `daily/` matching `YYYY-MM-DD.md` that is < today |
| `YYYY-MM-DD` | That exact file |
| `yesterday` | `date -d 'yesterday' +%Y-%m-%d` — error if missing |
| `Nd` (e.g. `3d`) | All daily notes in last N days (today excluded) |
| `since YYYY-MM-DD` | All daily notes from that date through most-recent (today excluded) |

Use `Bash` with `ls -1 ~/Documents/worklog/knowledgebase/topics/personal-notes/notes/daily/ | grep -E '^[0-9]{4}-[0-9]{2}-[0-9]{2}\.md$' | sort` to enumerate.

If no daily note matches: print `no daily note found for <criterion>` and stop. Do not invent content.

### 2. Read the daily note(s)

Extract these sections in priority order:

1. **`## Summary`** — one-paragraph wrap. Highest-density signal.
2. **`## Closed Line Items`** — narrative bullets per closed line.
3. **`## Closed Sub-items`** — granular checklist closes grouped by `**§N — title:**`.
4. **`## Notes / Learnings`** — pull only if Summary missing/thin (stub note).

Skip `## Closed Workstreams`, `## PR ... Monitoring`, `## Plan After ...`, and other ad-hoc sections — debugging records, not standup material.

**Also harvest people-interactions** from the narrative — phrases like "talked with X", "synced with Y", "Z asked me to…", "discussed with W". These are first-class topic-mode bullets ("Talked with jess regarding immix race condition") even when not tied to a §N. Pull from `## Summary`, `## Closed Line Items`, and `## Notes / Learnings`.

### 3. Read mark-todos (topic mode only)

Read `topics/personal-notes/notes/entities/mark-todos.md` and extract:

- `<!-- BEGIN-TODAY-SCOPE -->` / `<!-- END-TODAY-SCOPE -->` block — unchecked items become "What are you working on today?" bullets. Skip `- [x]` (already done).
- Any `*(blocked by ...)*` or `**BLOCKED:**` markers in Today's Scope or referenced `§N` sections — become "Is anything standing in your way?" bullets.

If Today's Scope date != today, flag inline: `_(today's scope is stale — dated YYYY-MM-DD)_`.

If no Today's Scope or it's empty, render: `- (no scope set — suggest /daily-scope)`.

If no blockers detected, render: `- nope`.

---

## Mode A: Topic mode (default)

Three-question format matching the user's actual standup style. **Conversational tone, no internal identifiers.**

### Tone rules

- **No PR numbers, no §N workstream refs, no ticket IDs, no metrics.** "Talked about a fix" not "Verified PR #1688 (99.3% drop)".
- **Topic-level language.** "AP and line crossing release", "immix race condition", "postgres access approaches" — name the *thing*, not the artifact.
- **People names allowed and encouraged** when they appeared in the daily note narrative ("Talked with jess…", "discussing with tati"). Use lowercase as the user does.
- **Casual capitalization OK.** Mid-sentence lowercase verbs ("started extending…") match the user's style — don't auto-correct.
- **Verbs include "Started", "Continuing", "Talked with", "Researching", "Discussing"** — not just shipped/verified. Standup is about activity, not just outcomes.
- **No emoji, no status colors.**
- **Strip wikilinks** — `[[2026-05-12_foo]]` → plain text or drop.

### "Yesterday" bullets

3–5 bullets covering the main threads, one short phrase each. Lifted from the daily note `## Summary` + Closed Line Items but **stripped of identifiers and metrics**. Group fine-grained subtasks under a single topic bullet.

### "Today" bullets

Pulled from mark-todos `## Today's Scope` unchecked items. Same tone-stripping: drop §N markers, drop ticket IDs, render as topic-level activity ("Continuing instrumentation changes and testing them"). 2–5 bullets.

### "Blockers" bullets

- Real blockers from `*(blocked by ...)*` markers → one line each, plain language.
- None detected → single bullet: `- nope`.

### Output template

```
What did you accomplish yesterday?
- <topic-level bullet>
- <topic-level bullet>
- <topic-level bullet>
- <topic-level bullet>

What are you working on today?
- <topic-level bullet>
- <topic-level bullet>
- <topic-level bullet>

Is anything standing in your way?
- nope
```

No date header, no preamble, no trailer. Paste-ready into a standup channel.

### Topic-mode example

**Input:** `topics/personal-notes/notes/daily/2026-05-12.md` (PR #1688 verification, instrumentation v1, §29 deploy lane, etc.) + today's mark-todos scope.

**Output:**

```
What did you accomplish yesterday?
- Verified the patrol-alert fix landed on rearch and saw the expected error-rate drop
- Shipped actuate-instrumentation v1 on a feature branch — held back from push pending verification experiments
- Scoped out the internal-test deploy lane in admin — design plus stub endpoints
- Cleared a nvidia suspend-hook drift and a couple stale crash popups after a reboot

What are you working on today?
- Continuing instrumentation verification experiments against the connector
- Pinging stakeholders on the deploy-lane endpoint design
- Scoping the gmail tier-1 digest workstream

Is anything standing in your way?
- nope
```

---

## Mode B: Detailed mode (`/standup detailed`)

Dense paste-ready 3–4 bullets covering yesterday only. Anchored with identifiers for async writeups and self-reference.

### Tone rules

- **Exactly 3–4 bullets.** Not 2, not 5.
- **One sentence per bullet.** Subordinate clauses OK; semicolons OK; no second period.
- **Past tense.** "Shipped X", "Verified Y", "Scoped Z" — not "Working on" / "Will ship".
- **Concrete outcomes.** "PR #1688 verified live (99.3% error drop)" not "spent time on PR #1688 verification".
- **Preserve identifiers** — PR #s, §N workstreams, library names, ticket IDs. Drop noise (timestamps, log counts, commit hashes). One anchor number per bullet max if it carries weight.
- **No editorializing** ("successfully", "smoothly"). No emoji, no status colors.
- **Strip wikilinks.**

### Synthesis approach

1. Read the Summary paragraph. Identify 3–5 distinct threads.
2. Cross-reference Closed Line Items to confirm threads landed real outcomes.
3. Collapse closely-related items into one bullet.
4. Drop pure-operational threads unless they were the day's spine.
5. If Summary missing (stub note), build from Closed Line Items alone.

### Range mode (`Nd` or `since`)

Same 3–4 bullets, summarizing *across* the range. Cluster by workstream/topic, pick highest-impact moment per cluster. Standup is not a changelog — drop overflow.

### Output template

```
# Standup — <date or range>

- <bullet 1>
- <bullet 2>
- <bullet 3>
- <bullet 4>   ← (optional 4th)
```

If the daily note was a stub (no `## Summary`), append: `_(source: stub daily note — Summary not yet written by /daily-wrap)_`.

### Detailed-mode example

```
# Standup — 2026-05-12

- Verified PR #1688 fix live and effective — `raise_patrol_alert failed` dropped 988/hr → 7/hr (-99.3%), all 4 target DW pods on the new image, residual events expected (one cronjob with no fallback candidate).
- Shipped `actuate-instrumentation` v1 on `feature/actuate-instrumentation-v1` (timing/memory/sampling modules, 30 tests passing) — branch unpushed pending three verification experiments against connector workload.
- Scoped §29 internal-test deploy lane — design synthesis covering existing primitives (`Customer.deployment_phase=CUSTOM` + `get_image_tag()` + `reboot_connector`) plus 4 admin-API stub files; endpoint bodies blocked on stakeholder pings.
- Patched soak-script verdict-as-exit-code footgun (Tier-1 monitor was flagging RED via systemd exit 2, not argparse) and recovered cleanly from NVIDIA suspend-hook + brltty SIGTRAP popups via post-reboot checklist.
```

---

## Rules / pitfalls (both modes)

- **Never edit the daily note or mark-todos.** Read-only.
- **Don't invent.** If Summary mentions a thing but Closed Line Items don't confirm it landed, report it as scoped/in-progress (topic mode: "Started researching…"; detailed mode: "Scoped…"), not shipped.
- **Don't include today's work in the "yesterday" section.** Standup yesterday-bullets are about completed/in-progress activity on the target date, not today.
- **Don't drop modes silently.** If `detailed` is requested, never fall through to topic format (and vice versa).
- **For range mode in topic format**, fold all dates into the single yesterday-section; today/blockers still reflect *current* mark-todos state, not range state.

## Related

- `/daily-wrap` — writes the `## Summary` this skill reads
- `/daily-scope` — sets Today's Scope (this skill reads it for "today" bullets)
- `/recap` — today's-status snapshot (read-only sibling)
- `topics/personal-notes/notes/daily/README.md` — daily-note convention
