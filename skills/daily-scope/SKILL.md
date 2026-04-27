---
name: daily-scope
description: Morning planning ritual. Checks for carry-over from prior day, surveys in-flight branches, reads mark-todos workstreams + auto-synced Jira queue, runs a light audit, interviews to pick 2-3 items for today, persists picks to mark-todos's Today's Scope section AND to in-session TaskCreate. Trigger on "daily scope", "scope today", "plan my day", "what should I work on", "daily standup", "/daily-scope".
user-invocable: true
allowed-tools:
  - Read
  - Glob
  - Grep
  - Bash
  - Edit
  - TaskCreate
  - TaskUpdate
  - AskUserQuestion
---

# Daily Scope

Morning planning ritual. Produces a tracked, persisted, realistic day's scope in ~2 minutes from a cold start.

**Persistence model:** picks are written to the `## Today's Scope` section in [[mark-todos]] (between `<!-- BEGIN-TODAY-SCOPE -->` / `<!-- END-TODAY-SCOPE -->` sentinels) AND created as session `TaskCreate` entries. The mark-todos version survives session swaps — the session Tasks are just for in-session tracking.

## Arguments

Mode flags use `--flag` form; positional args are reserved for primary subjects.

- No args (typical): run the full ritual
- `--quick`: skip the branch/PR survey
- `--dry`: survey + interview but don't write mark-todos or TaskCreate
- `--skip-repo-scan`: opt out of the GitHub cross-repo issue scan (default is **always run**; user preference 2026-04-23)

## Procedure

### Step 0 — Carry-over check (FIRST, before anything else)

Read the `## Today's Scope` section of `/home/mork/Documents/worklog/knowledgebase/topics/personal-notes/notes/entities/mark-todos.md`. Check the date in the heading.

- **Date is today and there are unchecked items:** a prior session in the same day scoped work. Surface those items to the user first. Ask whether to continue them, add more, or rescope entirely. If continuing, restore them as `TaskCreate` entries before moving on.
- **Date is yesterday or earlier with unchecked items:** yesterday's work didn't get wrapped. Offer to carry forward specific items, or run [[skill-daily-wrap|/daily-wrap]] first to close them out. Never silently overwrite.
- **Date is today with all items checked:** today's plan is done; offer to add extras or exit.
- **Section is empty:** normal start-of-day, proceed.

### Step 1 — Survey in-flight work (skip in `--quick` mode)

Run in parallel:

```bash
for d in vms-connector actuate-libraries actuate-inference-api actuate_admin autopatrol_onboarder autopatrol-server camera-ui; do
  if [ -d "/home/mork/work/$d" ]; then
    echo "=== $d ==="
    (cd "/home/mork/work/$d" && git branch --show-current && git status --short | head -5)
  fi
done

for d in vms-connector actuate-libraries actuate-inference-api actuate_admin autopatrol_onboarder; do
  (cd "/home/mork/work/$d" 2>/dev/null && gh pr list --author "@me" --state open --json number,title,headRefName,mergeable,reviewDecision)
done
```

### Step 2 — Read workstreams + Jira queue

Read `topics/personal-notes/notes/entities/mark-todos.md`. Parse workstream sections (§N) and the auto-synced Jira queue (between `<!-- BEGIN-AUTOSYNC-JIRA -->` sentinels).

### Step 2a — Recent KB syntheses not yet workstreamed

List KB synthesis notes written in the last 7 days:

```bash
find /home/mork/Documents/worklog/knowledgebase/topics -path "*/notes/syntheses/*.md" -mtime -7 2>/dev/null
```

For each, grep mark-todos.md for the note's filename or title. Any that aren't referenced are candidates:
- Fresh research/design work that hasn't been promoted to a tracked workstream
- Possibly worth a new workstream ([[skill-todos-add|/todos-add]]) or a Today's Scope item to follow up

Surface these in the anomaly step (Step 3), **not** as primary scope candidates — they're prompts for the interview, not tasks.

### Step 2b — GitHub repo scan (ALWAYS RUN — user preference 2026-04-23)

**Mandatory step, not optional.** Run the [[skill-repo-scan|/repo-scan]] procedure inline:
- Scans major Actuate repos for high-impact and low-hanging-fruit issues (not just assigned to Mark)
- Surfaces GitHub-only work that Jira auto-sync doesn't capture
- Top 3-5 per category fold into the Step 5 interview as candidate options
- Issues not picked into today's scope get triaged into the per-repo back-catalog files maintained under `topics/repo-backlog/` (see `skill-repo-scan` for catalog-write behavior)

Why always-on: Jira auto-sync only captures tickets assigned to Mark. Cross-repo GitHub issues (bug reports from teammates, `good first issue` candidates, items from `/repo-scan` runs in prior days) go uncurated without this step. User directive 2026-04-23: the scan must never be silently skipped during morning planning.

Only use `--skip-repo-scan` on explicit user override (e.g. the scan is broken, or the user wants a pure-Jira day).

### Step 2ba — Read minipc observations cache (NR-login saver — added 2026-04-27)

The minipc (`mork-firebat`) runs `/dashboard-check` hourly and exposes the
latest signal observations at `http://mork-firebat/app/api/observations`.
This cache replaces what used to be ~21 inline NRQL calls per morning.

Use the `~/bin/observations-snapshot` client — it wraps the GET, formats
the briefing, applies a freshness check, and returns meaningful exit codes:

```bash
~/bin/observations-snapshot --md     # markdown, briefing-ready
~/bin/observations-snapshot          # plain text, full descriptions
~/bin/observations-snapshot --json   # raw passthrough for jq pipelines
```

Exit codes: 0=all green, 1=any yellow, 2=any red, 3=cache unreachable/stale (>65 min).

**If the response is HTTP 200 AND `summary.newest_observation` is < 65 minutes old:**

1. Treat the cache as the **primary source of truth** for the standing
   `/dashboard-check` and NR-overnight checks. The cron has already collected,
   classified, and persisted everything. No need to re-run NRQL inline.
2. Surface RED + YELLOW signals from `signals` directly into the Step 4
   landscape briefing. Use the consumer-friendly shape:
   - `signals[<id>].status` — `green | yellow | red | informational | error`
   - `signals[<id>].value` — scalar or FACET dict
   - `signals[<id>].baseline` — what the dashboard compared against
   - `signals[<id>].age_minutes` — freshness check
   - `signals[<id>].extras.description` — human-readable description
3. Mark the standing Morning Follow-Up items satisfied:
   - **NR overnight health** — pulled from cache; only escalate if status is red AND drilling-down needs detail beyond what `value` and `extras` provide.
   - **`/dashboard-check` standing exec** — already ran on minipc; no local re-run needed.
4. Skip Step 2bb's NR MCP preflight test in this case — we don't need NR
   for the routine. Still preflight AWS / GH if any non-cached follow-up
   needs them.
5. **Drill-down only when warranted.** If a RED signal needs more context
   than the cached value provides (e.g. you want top-N facets at a finer
   granularity than the cached snapshot), THEN authenticate to NR and run
   a targeted NRQL. Don't pre-authenticate "just in case."

**If the cache is stale (≥65 min old), missing, unreachable, or returns 4xx/5xx:**

1. Note `minipc cache stale/unreachable` in the Step 4 landscape (it's a
   data point — the minipc may be down or its cron may be wedged).
2. Fall back to the original flow: Step 2bb runs NR preflight as before;
   Step 2c re-queries NR/AWS inline. Same as the pre-2026-04-27 behavior.

**Why:** Prior to 2026-04-27, every morning routine triggered ~21 separate
NRQL calls inline — slow, brittle (NR MCP would detach mid-fan-out), and
burned NR query budget. The minipc's hourly cron now does the collection
once per hour and serves the result via HTTP; the laptop just reads. User
report 2026-04-27: "TON of endless NR logins" pain → directly fixed by
this step. Architecture: [[2026-04-24_skills-audit-script-candidates]].

### Step 2bb — Preflight check (MANDATORY — user preference 2026-04-23)

Before running the Step 2c fan-out, verify every credential / connection the `exec` items will need. **Pause and ask the user to remediate before proceeding** — do NOT start the fan-out with a known-broken precondition. User directive: "we do NOT want failed tasks we could mitigate by following a simple checklist."

Parse the `Morning Follow-Ups` block first, classify required capabilities, then test each one:

| Capability | Test | Failure mode |
|---|---|---|
| AWS prod SSO | `AWS_PROFILE=prod aws sts get-caller-identity 2>&1` — succeeds with account 388576304176 | Expired SSO token → user runs `aws sso login --profile prod` |
| AWS dev-EU SSO | `AWS_PROFILE=dev-eu aws sts get-caller-identity 2>&1` (only if a fan-out item targets dev-EU) | Expired → user runs `aws sso login --profile dev-eu` |
| New Relic MCP | (skip if Step 2ba cache is fresh — the minipc already authenticated and ran the queries). Test inline only if cache is stale OR a follow-up requires drill-down NR detail not in the cache: `mcp__newrelic__list_available_new_relic_accounts` returns without error | MCP detached / auth expired → user restarts MCP or re-auths |
| GitHub CLI | `gh auth status` reports active user | Token expired → user runs `gh auth login` |
| Kubefwd MCP (if K8s checks required) | `mcp__kubefwd__get_quick_status` returns | MCP not connected → user starts kubefwd |
| Atlassian MCP (if Jira writes) | `mcp__atlassian__atlassianUserInfo` returns | Not authenticated → user re-auths |
| Dashboard sink writable | `test -w ~/Documents/worklog/dashboard/sink/observations.jsonl && test -r ~/.claude/skills/dashboard-check/config/signals.json` | Sink missing/unwritable → user fixes permissions or re-runs `/dashboard-check` once to create it |

**Ask for remediation up-front, batched.** Inspect all items at once and if more than one precondition fails, ask the user to fix them together (e.g., "AWS prod SSO expired and NR MCP is detached — please `aws sso login --profile prod` and reconnect the NR server, then I'll continue"). Only after every required precondition is green do you move to Step 2c.

If a precondition cannot be remediated (e.g., user is offline, external service down), mark the dependent fan-out items as BLOCKED *before running them* and continue with the rest. This is better than running and failing.

**Why:** Prior runs (e.g., 2026-04-23) wasted time by running the fan-out first, hitting expired SSO mid-flow, and then having to re-run after remediation. A 10-second preflight prevents the double-work loop.

### Step 2c — Morning Follow-Ups fan-out

Read the `## Morning Follow-Ups` section in mark-todos (between `<!-- BEGIN-MORNING-FOLLOWUPS -->` / `<!-- END-MORNING-FOLLOWUPS -->`). Items are tagged `exec` / `verify` / `decide`.

**Run the `exec` + `verify` items during this step** (don't wait for user approval — these are pre-agreed checks that the prior `/daily-wrap` seeded specifically to be consumed here). Surface `decide` items to the user in the Step 5 interview so their outcomes can shape scope.

**`/dashboard-check` is satisfied by the minipc cache (Step 2ba) under normal conditions.** The minipc runs `/dashboard-check` hourly and serves the result at `http://mork-firebat/app/api/observations`. The standing exec item is "checked" when Step 2ba surfaced fresh cached data — no need to re-run inline. Fold the cache's `summary.overall` (green/yellow/red) into the Step 4 landscape; surface RED signals as potential scope items.

**Run `/dashboard-check` locally only when:**
- Step 2ba reported the cache is stale (≥65 min) OR unreachable, AND the fan-out can't proceed without fresh data, OR
- A specific verify-item needs an immediately-fresh observation (e.g., post-deploy gate within minutes of merging).

The skill's exit code (0=green, 1=yellow, 2=red) should fold into the Step 4 landscape — any non-zero exit gets a flagged line in the landscape presentation. Don't block on yellow; surface red as a potential scope item for the day.

Typical fan-out tools:
- `/dashboard-check` — mandatory standing exec (see above). Writes sink rows tagged `source_skill="dashboard-check"`.
- NR health check → delegate to `nrql-investigator` subagent (KB / [[agent-nrql-investigator]])
- GH PR / issue status → `gh pr view`, `gh issue view`
- AWS queries (DDB, SQS, etc.) → `aws ...` with appropriate profile
- Cross-session visibility → `/kb-recap` for the prior-day-to-today window
- Branch / file-state checks → `git` commands or `Read`/`Grep`

**For every non-dashboard-check fan-out result**, also write a sink observation via `python3 -c "import sys; sys.path.insert(0, '/home/mork/.claude/skills/dashboard-check'); from sink import write_observation; write_observation(...)"`. Use `source_skill="daily-scope.fan-out"`, pick a signal_id that matches the check (e.g., `morning_nr_overnight_verdict`, `morning_cleanup_lambda_verdict`), status green/yellow/red matching the verdict, value = the key metric, notes = one-line summary. Per-check sink writes let the dashboard's Morning-summary pane aggregate cross-session signal over time.

**Persist every fan-out result back to the Morning Follow-Ups block, inline, as you get it** — tick `[x]` and append a one-line result to the item. Don't batch; do it immediately after each check returns, so partial state survives if the session crashes. Example:

```markdown
- [x] **exec**: §3 DDB counter progression — **blocked on creds** (dev-eu profile missing, dev SSO expired); needs cleanup-lambda-session eyes. *(set 2026-04-21; ran 2026-04-22)*
- [x] **verify**: NR overnight health — §2b canaries all PASS (alert delivered steady, silent drop 0); **OOMKills 103/24h elevated**, `connector-14170` 32/day chronic; NoneType 3x up. *(set 2026-04-21; ran 2026-04-22)*
- [x] **verify**: Immix GH channels — GH#1656, GH#1658 both silent since 2026-04-20. Standing watch. *(set 2026-04-21; ran 2026-04-22)*
```

Tagging convention: append `*(set <seed-date>; ran <today>)*` so the provenance trail is durable — which day seeded the check, which day it ran.

If a check cannot be run (missing creds, external timeout, infeasible), still tick `[x]` with a "blocked" result + why, rather than leaving `[ ]`. A `[ ]` at end-of-morning means "deliberately deferred or not attempted" and `/daily-wrap` will roll it over; a blocked-but-run item is closed with a known reason.

### Step 3 — Light audit (inline anomaly surface)

Flag any of these:
- **Feature branches not referenced in any workstream** — possible orphan
- **Uncommitted changes on `main`/`stage`/`develop`** — suspicious
- **High or Highest priority Jira tickets (Ready to Deploy or In Progress) not mentioned in any workstream**
- **Jira auto-sync "Last synced:" is not today or yesterday** — [[automation-jira-sync]] may be broken
- **mark-todos frontmatter `updated:` is older than 3 days** — discipline reminder
- **Recent KB syntheses (from Step 2a) not linked to any workstream** — fresh research without a follow-up home

For deeper audit (duplicates, priority drift, workstream-without-tickets, etc.), suggest [[skill-todos-audit|/todos-audit]] — don't try to cover that ground here.

### Step 4 — Present the landscape

One concise message. Active branches mapped to workstreams, Ready-to-Deploy tickets priority-sorted, In-Progress, **fresh findings from the Step 2c fan-out**, and the audit flags from Step 3. Keep under ~300 words. Fan-out highlights (surprises, flags, blocked-exec items) should be front-and-center here since they often reshape the interview options.

### Step 5 — Interview for today's scope

**Interview is mandatory, not optional.** User preference (2026-04-21): morning planning must always be driven by `AskUserQuestion`, not by a passive list the user replies to freeform. This is the default flow; don't skip even when the picks "look obvious."

Use `AskUserQuestion` with `multiSelect: true` and the 4 most likely picks. **Hard limit is 4 options per question.**

**Option-label format (user preference, 2026-04-21):** lead each option with a short descriptive title (≤5 words) — *not* a `§N` reference, *not* a full sentence. The §N reference and full detail belong in the `description` field, not the `label`. Example:

```
label: "Merge #58 + close §1"         ← ≤5 words, action-oriented
description: "Merge PR #58 (SAHI leak strip) in actuate-inference-api; retroactively tick the §1 audit/validate-release rows on basis of overnight green NR; archive to today's daily note"
```

NOT:

```
label: "§1 run /validate-release against merged PRs #56 / #57 then close"  ← too long, §N-led
```

Same rule applies to scope-block `- [ ]` lines in Step 6: lead with bold title, then detail.

Workarounds (use both):
- **Free-form notes:** invite extras via notes attached to any option. Parse notes after the answer returns and create separate `TaskCreate`s for each additional item.
- **Chained questions:** if more than 4 candidates clearly deserve surfacing, use a *second* `AskUserQuestion` after the first. Frame it as "Anything from this batch?" — additive, not redundant.

Never cram >4 options into one question — the validation blocks it (`too_big: maximum 4`) and costs a round trip.

### Step 6 — Persist picks to mark-todos

Edit the `## Today's Scope` section between the `<!-- BEGIN-TODAY-SCOPE -->` / `<!-- END-TODAY-SCOPE -->` sentinels. Format:

```markdown
## Today's Scope (YYYY-MM-DD)

Picked via [[skill-daily-scope|/daily-scope]]. Line items close via [[skill-daily-wrap|/daily-wrap]] at end-of-day — closed items get a summary in the daily note, not deleted here.

- [ ] **Short title (≤5 words)** — §N cross-ref + outcome detail + links *(status qualifier if any)*
- [ ] ...

**Descoped from today:** (optional, if items were considered and dropped)
```

Bold short title leads the line; §N + full context comes after the em-dash.

Also bump the frontmatter `updated:` field to today.

### Step 7 — Persist picks to session Tasks

For each picked item AND each free-form addition, call `TaskCreate`:
- `subject`: same wording as the markdown line item (workstream § prefix + concrete outcome)
- `description`: what "done" looks like + branch/ticket context
- `activeForm`: present continuous
- Use `addBlocks` / `addBlockedBy` if the user described dependencies between picks

### Step 8 — Confirm

Summarize the agreed scope back in 3-5 lines. Mark the first task `in_progress` only when the user says "let's start on X" — don't auto-start.

## Rules

- **Never delete** anything in mark-todos. This skill only edits the `## Today's Scope` section and frontmatter `updated:`.
- **Don't prescribe.** The user picks scope; the skill surfaces and tracks.
- **Realistic scope is 2-3 items.** If the user picks more, gently ask if something should defer.
- **Persist first, then session-track.** If persistence fails, don't create orphaned `TaskCreate`s.
- **Carry-over is Step 0 and non-negotiable** — losing yesterday's unfinished work by overwriting Today's Scope is the worst failure mode.
- **Fan-out results are persisted, not ephemeral** (user preference 2026-04-22): every Morning Follow-Ups `exec` / `verify` / `decide` item that's run during this skill MUST be `[x]`'d with a one-line result appended inline. Don't let findings die in chat; the follow-up block is the durable trace. `/daily-wrap` relies on it to produce the day's summary.

## Related

- [[skill-daily-wrap]] — end-of-day companion
- [[skill-todos-audit]] — deeper periodic audit
- [[skill-todos-add]] — add a new workstream §
- [[skill-repo-scan]] — optional GitHub cross-repo scan (via `--with-repo-scan`)
- [[mark-todos]] — the file this skill writes to
- [[automation-jira-sync]] — the daily job that keeps the Jira queue fresh
