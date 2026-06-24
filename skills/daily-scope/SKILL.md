---
name: daily-scope
description: Morning planning ritual — surveys carry-over, branches, mark-todos workstreams, Jira queue. Picks 2-3 items, persists to Today's Scope + TaskCreate. Trigger: '/daily-scope', 'plan my day'.
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

Morning planning ritual. Produces a tracked, persisted, realistic day's scope in ~2 minutes.

**Persistence:** picks go to `## Today's Scope` (between `<!-- BEGIN-TODAY-SCOPE -->` / `<!-- END-TODAY-SCOPE -->`) in [[mark-todos]] AND as session `TaskCreate`. Mark-todos survives session swaps; Tasks are in-session.

**Mark-todos shape:** holds open work only. Closed `[x]` sub-items live in per-date daily notes (swept by `/daily-wrap` Step 2.7). When reading workstream sections (Step 2), expect only `[ ]` per §N. To find historical close-outs: grep daily notes by `topic:` or `workstreams:` frontmatter.

## Arguments

- *(none)*: full ritual
- `--quick`: skip branch/PR survey
- `--dry`: survey + interview, don't persist
- `--skip-repo-scan`: opt out of GH cross-repo scan (default = always run; user pref 2026-04-23)

## Procedure

### Step 0 — Carry-over check (FIRST)

Read `## Today's Scope` from mark-todos. Check the heading date.

- **Today, unchecked items:** prior session scoped work. Surface to user; ask continue / add / rescope. If continuing, restore to `TaskCreate`.
- **Yesterday or earlier, unchecked:** missed wrap. Offer to carry forward, or run `/daily-wrap` first.
- **Today, all checked:** plan done; offer extras or exit.
- **Empty:** normal start, proceed.

Never silently overwrite.

### Step 1 — Survey in-flight work (skip in `--quick`)

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

Read mark-todos. Parse §N sections + the auto-synced Jira queue (between `<!-- BEGIN-AUTOSYNC-JIRA -->`).

### Step 2a — Recent KB syntheses

```bash
find /home/mork/Documents/worklog/knowledgebase/topics -path "*/notes/syntheses/*.md" -mtime -7 2>/dev/null
```

For each: grep mark-todos for the filename/title. Unreferenced ones surface as anomaly prompts in Step 3 (not as primary scope candidates).

### Step 2a.5 — Broken-wikilink digest (kb-todo-scan)

The KB accumulates outbound wikilinks to anchors that don't exist yet — implicit "TO-DO: write this stub." Run [[kb-todo-scan]] and surface the top 5 candidates so the user knows what's stub-worthy without having to run the scanner manually.

```bash
~/bin/kb-todo-scan 2>/dev/null | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(f'broken-wikilink targets in vault: {len(d)}')
print('top 5 by ref_count:')
for t in d[:5]:
    print(f'  {t[\"ref_count\"]:>3}  [{t[\"category\"]:>9}]  {t[\"target\"]}')
"
```

This is **awareness, not action.** Don't auto-research; just surface. If the user wants to draft a stub: `kb-todo-research --target <name>` runs through the LLM shop. Tracked in §24 Phase 2F.

If `~/bin/kb-todo-scan` is missing, skip silently — this step is a Phase 2F enhancement, not core to scoping.

### Step 2b — GitHub repo scan (ALWAYS RUN)

**Cache-first.** Minipc runs `~/bin/morning-prep.sh` Mon-Fri 06:00 ET, pre-computing `/repo-scan` + autopatrol skills:

```bash
curl -fsS http://mork-firebat/logs/morning-prep-latest.summary.json
```

Summary shape: `{date, started_at, finished_at, skills: {<skill>: {started_at, finished_at, exit_code, stdout_path, stderr_path}}}`.

**Use cache if all hold:**
1. `summary.date == today` (America/New_York)
2. `summary.skills["repo-scan"].exit_code == 0`
3. `summary.finished_at` < 8h old

If yes: `curl -fsS http://mork-firebat/logs/repo-scan-<today>.stdout`, fold top-N into Step 5 options. **Don't re-run inline.** Mark "repo-scan: minipc cache, ran HH:MM ET" in Step 4.

If cache stale/missing/failed: run `/repo-scan` inline. Mark "repo-scan: inline (cache miss)" in Step 4.

**Why always-on:** Jira auto-sync only catches Mark's tickets. Cross-repo GH issues (teammate bugs, `good first issue`s, prior `/repo-scan` items) go uncurated otherwise. Use `--skip-repo-scan` only on explicit override.

### Step 2ba — Read minipc observations cache (NR-login saver)

Minipc runs `/dashboard-check` hourly; observations served at `http://mork-firebat/app/api/observations`. Replaces ~21 inline NRQL calls.

```bash
~/bin/observations-snapshot --md     # markdown briefing
~/bin/observations-snapshot          # plain text
~/bin/observations-snapshot --json   # raw passthrough
```

Exit codes: 0=green, 1=yellow, 2=red, 3=cache stale/unreachable (>65 min).

**If HTTP 200 AND `summary.newest_observation` < 65 min:**
1. Cache is **primary source** for `/dashboard-check` + NR-overnight checks. Skip inline NRQL.
2. Surface RED + YELLOW from `signals` into Step 4. Shape: `signals[<id>].{status, value, baseline, age_minutes, extras.description}`.
3. Mark standing Morning Follow-Ups satisfied: NR overnight (cache), `/dashboard-check` (cron-ran, no local re-run).
4. Skip Step 2bb's NR preflight; still preflight AWS/GH if non-cached follow-ups need them.
5. **Drill-down only when warranted** — RED needs context beyond cache → then auth NR + targeted NRQL.

**If cache stale (≥65 min) / unreachable / 4xx-5xx:**
1. Note `minipc cache stale/unreachable` in Step 4 (data point — minipc may be down).
2. Fall back: Step 2bb runs NR preflight, Step 2c re-queries inline (pre-2026-04-27 behavior).

### Step 2bb — Preflight check (MANDATORY)

Before Step 2c fan-out, verify every credential the `exec` items need. **Pause and ask user to remediate before proceeding** — never start fan-out with known-broken precondition.

| Capability | Test | On failure |
|---|---|---|
| AWS prod SSO | `AWS_PROFILE=prod aws sts get-caller-identity` (account 388576304176) | `aws sso login --profile prod` |
| AWS dev-EU SSO | `AWS_PROFILE=dev-eu aws sts get-caller-identity` (only if needed) | `aws sso login --profile dev-eu` |
| New Relic MCP | Skip if Step 2ba cache fresh. Otherwise `mcp__newrelic__list_available_new_relic_accounts` returns | restart MCP / re-auth |
| GitHub CLI | `gh auth status` | `gh auth login` |
| Kubefwd MCP (if needed) | `mcp__kubefwd__get_quick_status` | start kubefwd |
| Atlassian MCP (if writes) | `mcp__atlassian__atlassianUserInfo` | re-auth |
| Dashboard sink | `test -w ~/Documents/worklog/dashboard/sink/observations.jsonl && test -r ~/.claude/skills/dashboard-check/config/signals.json` | fix perms or run `/dashboard-check` once |

**Batch remediation requests** — if multiple fail, ask user to fix all together. Only proceed when every required precondition is green. Cannot remediate (offline / external down) → mark dependent fan-out items BLOCKED before running and continue with the rest.

### Step 2c — Morning Follow-Ups fan-out

Read `## Morning Follow-Ups` in mark-todos (between `<!-- BEGIN-MORNING-FOLLOWUPS -->`). Items tagged `exec` / `verify` / `decide`.

Run `exec` + `verify` items now (pre-agreed by prior `/daily-wrap`). Surface `decide` to user in Step 5.

**Cached items (skip inline run if cache fresh):**
- `/dashboard-check` — satisfied by Step 2ba cache.
- `/autopatrol-overnight-check`, `/autopatrol-cleanup-lambda-check` — same morning-prep cache pattern as `/repo-scan`. Check `summary.skills.<name>.exit_code == 0` + `finished_at` < 8h, fetch stdout. **Most token-expensive items in fan-out — never re-run if cache fresh.** Stale → run inline (or delegate via `Agent` `subagent_type: nrql-investigator` for autopatrol-overnight-check).

**Run `/dashboard-check` locally only when:** Step 2ba cache stale/unreachable AND fan-out needs fresh data, OR a verify-item needs minutes-fresh observation (post-deploy gate).

Skill exit codes (0=green, 1=yellow, 2=red) fold into Step 4. Don't block on yellow; surface red as scope candidate.

**Other fan-out tools:**
- NR health → `nrql-investigator` subagent
- GH PR/issue → `gh pr view`, `gh issue view`
- AWS → `aws ...` with right profile
- Cross-session visibility → `/kb-recap`
- Branch/file checks → `git`, `Read`, `Grep`

**For every non-`/dashboard-check` fan-out result**, write a sink observation:
```
python3 -c "import sys; sys.path.insert(0, '/home/mork/.claude/skills/dashboard-check'); from sink import write_observation; write_observation(...)"
```
Use `source_skill="daily-scope.fan-out"`, signal_id matching the check (e.g. `morning_nr_overnight_verdict`, `morning_cleanup_lambda_verdict`), status green/yellow/red, value=key metric, notes=one-liner.

**Persist every fan-out result back to Morning Follow-Ups inline as you get it** — don't batch. Tick `[x]` and append result + `*(set <seed-date>; ran <today>)*`. Example:

```markdown
- [x] **exec**: §3 DDB counter progression — **blocked on creds** (dev-eu profile missing). *(set 2026-04-21; ran 2026-04-22)*
- [x] **verify**: NR overnight health — §2b canaries all PASS; **OOMKills 103/24h elevated**, `connector-14170` 32/day. *(set 2026-04-21; ran 2026-04-22)*
```

If a check can't run (missing creds, timeout, infeasible), still tick `[x]` with "blocked: <why>" rather than leaving `[ ]`. `[ ]` at end-of-morning = deliberately deferred; `/daily-wrap` rolls it over.

### Step 2d — Backlog surface (operational since 2026-05-08)

Frontmatter-discoverable backlog docs hold "decided to wait" tail entries that should resurface when active scope is light and morning fan-out is quiet, OR when the user explicitly asks ("anything in the backlog worth pulling?").

#### Trigger gate (run this check first)

```bash
# (a) Empty/light active picks: count [ ] items in Today's Scope between sentinels
empty_picks=$(awk '/<!-- BEGIN-TODAY-SCOPE -->/,/<!-- END-TODAY-SCOPE -->/' \
    /home/mork/Documents/worklog/knowledgebase/topics/personal-notes/notes/entities/mark-todos.md \
    | grep -cE "^- \[ \]")
# 0 = empty, 1-2 = light, 3+ = full

# (b) Fan-out quiet: observations cache overall != red AND no Highest/In Progress Jira in queue
overall=$(curl -fsS --max-time 5 http://mork-firebat/app/api/observations 2>/dev/null \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['summary']['overall'])" 2>/dev/null)
# overall in {green, yellow, red, error, ""}; treat green/yellow as quiet, red/error as not-quiet
```

**Surface backlog when:** `empty_picks <= 2 AND overall in {green, yellow}` OR user asked. Otherwise skip — don't crowd the interview.

#### Discovery

```bash
# Primary: explicit pointer in mark-todos frontmatter
explicit=$(grep "^backlog:" mark-todos.md | cut -d: -f2- | tr -d ' ')

# Secondary: glob across topics for additional registers
find /home/mork/Documents/worklog/knowledgebase/topics \
    \( -name "*-deferred-backlog.md" -o -name "*-backlog.md" \) 2>/dev/null
```

Combine the two. Today's known docs (extend as new ones land):

- [[autopatrol-deferred-backlog]] — `topics/autopatrol/notes/entities/autopatrol-deferred-backlog.md`
- *(future)* connector-deferred-backlog, fleet-arch-deferred-backlog, etc.

#### Parsing each backlog doc

Backlog docs follow this shape (the contract — see `## Backlog-doc shape contract` in `/backlog-add` SKILL.md for the canonical version):

```markdown
## Index

| Item | Source §N | Status | Decision Owner | Decision Trigger |
|------|-----------|--------|----------------|------------------|
| [Foo work](#foo-work) | §N archived/deferred | Wait | Mark | population growth, customer complaint, etc. |
```

Per-entry sections include a `**Re-open conditions:**` subheading with concrete triggers. Pull the index rows + the per-entry re-open conditions for the candidate set.

#### Ranking by re-open trigger relevance

For each candidate item, judge whether its re-open trigger has plausibly fired since the item was last scoped. Cross-reference against signals the morning has already collected:

| Re-open trigger pattern | Cross-reference signal |
|---|---|
| "population grows materially" / "cohort grows" | recent KB syntheses (Step 2a, last 7d) mentioning the cohort |
| "customer complaint" / "customer-facing" | Jira queue (Highest/High new tickets), Slack mentions if surfaced |
| "new related work landing" / "PR X reaches prod" | active PR list (Step 1), repo-scan output (Step 2b) |
| "RED dashboard signal X fires" | `signals[X].status == 'red'` from Step 2ba observations |
| "after Y dust settles" | check whether Y's tracking item is closed in mark-todos archive table |
| "infra prereq lands" | mark-todos `## Tracked as relevant` carry-forward + Jira queue |

Rank top 2-3 by triggered-or-not + recency of the triggering signal. Items whose triggers haven't moved get **silenced** for this morning — don't surface noise.

If the same backlog entry has been silenced for >30 days without trigger movement, surface it once anyway with a "stale-backlog check" framing — sometimes priorities shift without a clean signal.

#### Surfacing into Step 5

Surface ranked candidates as **additional Step 5 options** (still under the 4-options-per-question cap). Label format: `"§N <topic> — re-open?"` with description = "Backlog item: <one-line>; trigger: <what fired>; full context: [[backlog-doc#anchor]]".

**Don't auto-promote.** Backlog→active is always a Step 5 option, never a side-effect. If the user picks one:
1. Confirm by asking which §N home (new, restored from archive, or fold into existing).
2. Move the entry block from the backlog doc into mark-todos as an active §N with today's date.
3. Update the backlog doc's index row with `Status: PROMOTED YYYY-MM-DD → §N` so the entry's history is preserved.

#### Backlog-doc shape contract (for new backlog docs)

When creating a new backlog doc (via `/backlog-add` or manually), it must:

- Live at `topics/<topic>/notes/entities/<topic>-deferred-backlog.md` (or `-backlog.md`)
- Have frontmatter `type: entity`, `tags: [..., backlog, deferred]`, `topic: <topic>`
- Include an `## Index` table with at minimum: Item / Source §N / Status / Decision Trigger
- Have per-entry sections with `**Re-open conditions:**` subheading enumerating concrete triggers

Without this shape, Step 2d's parsing falls back to "list candidates by filename only" and ranking degrades to "ask user."

### Step 3 — Light audit

Flag:
- Feature branches not referenced in any §N (orphan)
- Uncommitted changes on `main` / `stage` / `develop`
- High/Highest priority tickets (Ready-to-Deploy, In-Progress) not in any §N
- Jira auto-sync `Last synced:` not today/yesterday → [[automation-jira-sync]] broken
- mark-todos `updated:` >3 days
- Recent KB syntheses (Step 2a) without a workstream

For deeper audit: suggest `/todos-audit`.

### Step 4 — Present the landscape

One concise message (~300 words). Active branches → workstreams, Ready-to-Deploy priority-sorted, In-Progress, **fan-out highlights** (surprises, flags, blocked-execs), Step 3 anomalies. Fan-out front-and-center — often reshapes Step 5 options.

### Step 5 — Interview for today's scope

**Mandatory.** Use `AskUserQuestion` with `multiSelect: true` and the 4 most likely picks. **Hard limit 4 options per question** (validation blocks `>4`).

**Option-label format:** lead with short title (≤5 words), action-oriented. NOT a §N reference, NOT a full sentence. Detail goes in `description`. Example:

```
label: "Merge #58 + close §1"
description: "Merge PR #58 (SAHI leak strip); retroactively tick §1 audit/validate-release rows on overnight green NR; archive to today's daily note"
```

NOT: `label: "§1 run /validate-release against merged PRs..."`.

Same rule for Step 6 scope-block lines: bold title, then detail.

**Workarounds:**
- Free-form notes: invite extras via option notes; parse and create separate `TaskCreate`s.
- Chained questions: if >4 candidates deserve surfacing, use a second `AskUserQuestion` ("Anything from this batch?").

### Step 6 — Persist picks to mark-todos

Edit `## Today's Scope` between sentinels:

```markdown
## Today's Scope (YYYY-MM-DD)

Picked via [[skill-daily-scope|/daily-scope]]. Line items close via [[skill-daily-wrap|/daily-wrap]] at EOD.

- [ ] **Short title (≤5 words)** — §N cross-ref + outcome detail + links *(status qualifier if any)*
- [ ] ...

**Descoped from today:** (optional)
```

Bump frontmatter `updated:`.

### Step 7 — Persist picks to session Tasks

`TaskCreate` for each pick + free-form addition:
- `subject`: same wording as the markdown line
- `description`: what "done" looks like + branch/ticket context
- `activeForm`: present continuous
- `addBlocks` / `addBlockedBy` if user described dependencies

### Step 8 — Confirm

Summarize agreed scope in 3-5 lines. Mark first task `in_progress` only when user says "let's start" — don't auto-start.

## Rules

- **Never delete** in mark-todos. This skill edits only `## Today's Scope` + frontmatter `updated:`.
- **Don't prescribe.** User picks; skill surfaces and tracks.
- **Realistic scope = 2-3 items.** More → gently ask to defer.
- **Persist first, then session-track.** If persistence fails, no orphan `TaskCreate`s.
- **Carry-over (Step 0) is non-negotiable.** Overwriting yesterday's unfinished work is the worst failure mode.
- **Fan-out results are persisted, not ephemeral.** Every Morning Follow-Up `exec`/`verify`/`decide` MUST be `[x]`'d with a one-liner. Findings dying in chat is the failure mode.

## Related

- [[skill-daily-wrap]] — EOD companion
- [[skill-todos-audit]] — deeper periodic audit
- [[skill-todos-add]] — add a new §N
- [[skill-repo-scan]] — GH cross-repo scan
- [[mark-todos]]
- [[automation-jira-sync]]
