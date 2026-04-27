# Global Rules

## Session Start Ritual

At the start of any Actuate-context session, before substantive work:

1. **Read `topics/personal-notes/notes/entities/mark-todos.md`** — source of truth for workstreams (§N) and today's scope.
2. **Check `## Active Session Claims`** (between `<!-- BEGIN-SESSION-CLAIMS -->` / `<!-- END-SESSION-CLAIMS -->` sentinels) — see the "Session Claims" section below. Before picking up any tracked work, check for overlap with an active claim. If your planned scope overlaps, warn the user before proceeding. The SessionStart hook prints active claims into the initial context automatically, so this check is usually one read.
3. **Check the `## Today's Scope` section** (between `<!-- BEGIN-TODAY-SCOPE -->` / `<!-- END-TODAY-SCOPE -->` sentinels):
   - Date is today with unchecked items → surface them; ask which to pick up.
   - Date is older than today with unchecked items → a prior day wasn't wrapped. Suggest `/daily-wrap` for that date first, then `/daily-scope` for today.
   - Empty or missing heading → suggest `/daily-scope` to set up the day.
4. **Check frontmatter `updated:`** — if >3 days old, flag discipline slip.
5. **Match the task to a skill** if applicable. Daily/personal workflow skills:
   - `/daily-scope` — morning planning, persists picks to mark-todos + TaskCreate
   - `/daily-wrap` — end-of-day, writes daily note + archives closed workstreams
   - `/todos-audit` — periodic audit (stale, orphans, drift); run weekly
   - `/todos-add` — scaffold a new workstream § with correct format
   - `/claim` / `/release` / `/claims` — session-claims coordination (see below)

This check is ~30 seconds and prevents losing track of prior-session scope. Skip only for trivial one-off questions that don't touch personal work.

## Session Claims (multi-session coordination)

Multiple Claude Code sessions run in parallel. Without coordination, two sessions can duplicate work (both verifying a stage deploy, both editing the same docs). The **session-claims table** inside `mark-todos.md` is the shared coordination state — same file the Session Start Ritual already reads, so no new primitives to track.

**The data:** markdown table between `<!-- BEGIN-SESSION-CLAIMS -->` / `<!-- END-SESSION-CLAIMS -->` in mark-todos. Schema: `| Label | Scope | CWD | Started | Heartbeat |`. Timestamps are UTC ISO-8601 minute-precision (`YYYY-MM-DDTHH:MMZ`). When there are no active claims, a single placeholder row `| *(none claimed)* | | | | |` holds the slot.

**The skills:**
- `/claim <label> <scope>` — register this session. Run at the start of any session that will spend >15 min on a tracked §N workstream item.
- `/release` — remove this session's claim (matches by `$PWD`). Run when the work is done or you're about to `/clear`.
- `/claims` — view the current table; flags overlaps with `$PWD` and stale heartbeats.

**The automation (`~/.claude/hooks/`):**
- **SessionStart hook** (`session-claims-startup.py`) — prunes rows with heartbeat >2h old, then prints active claims to stdout so the starting session sees them in initial context.
- **Stop hook** (`session-claims-heartbeat.py`) — updates the heartbeat of the row whose `CWD` matches current session's `$PWD`. Runs after every Claude turn, no user action needed.

**Rules for Claude within a claimed session:**
1. Before doing tracked work, check the claims table (SessionStart hook output, or re-read). If your planned scope overlaps another session's claim — same CWD or semantically same §N scope — warn the user: "Session `<label>` is already claimed for `<scope>` — continue anyway, or let that session handle it?"
2. When the user asks you to work on a tracked §N item in a non-trivial way and no claim exists for this session, proactively suggest `/claim`.
3. When work wraps (user says "done", runs `/daily-wrap`, or switches scope substantially), proactively suggest `/release`.
4. If you notice a stale claim (heartbeat >30 min and the user has moved on), offer to `/release <label>` on their behalf.

**When NOT to claim:** one-shot questions, read-only exploration, quick edits that finish in <15 min. Claiming overhead isn't worth it for short work.

## Task Completion Ritual

When you finish a tracked unit of work — a mark-todos line item, a Jira ticket, a workstream sub-task, or anything the user would consider "done" rather than "in flight" — do all four, at the moment of closure (not batched at end-of-day):

1. **Update `mark-todos`** — flip the relevant `- [ ]` to `- [x]` in the matching workstream § and/or Today's Scope. Add a one-line completion hook (PR #, merge commit, wikilink to a KB note) so the closure is traceable later. If the item unblocked something else, remove the `*(blocked by ...)*` marker on the dependent line.
2. **Log to KB per the "After Work: Log to KB" table below** — bug fixes, ADRs, new features, investigations each have their assigned location. The note's filename should be date-prefixed (`2026-04-17_slug.md`) and the mark-todos completion hook should wikilink to it.
3. **Append to today's daily note stub** at `topics/personal-notes/notes/daily/YYYY-MM-DD.md`. If the stub doesn't exist yet, create it using the template in `topics/personal-notes/notes/daily/README.md` — frontmatter, `## Summary` placeholder, empty `## Closed Line Items` / `## Closed Workstreams` / `## Notes / Learnings` sections. Add a bullet under `## Closed Line Items` matching the workstream § (e.g., `**§1 fix 500 error on motion-plus model** — <1-2 sentence what / why / link to KB note>`). Do **not** fill the `## Summary` — that's `/daily-wrap`'s job at EOD; the stub is a running append log through the day.
4. **If the work involved a push/merge**, the Post-Push Audit already covers CI / docs sync / security review — don't duplicate; just make sure you actually ran through it.

Skip only for trivial intra-session work that isn't tracked anywhere (one-off lookups, exploratory reads, aborted attempts). If you're unsure whether something counts — it probably does. Unclosed items in `mark-todos` accrete faster than `/daily-wrap` can reconcile them; the cost of a 30-second update now is much lower than reconstructing provenance a week later.

## Session Budget Management (KB / R&D / planning soft-cap)

KB reads, greps, syntheses, scans, and planning chew through session context fast. When cumulative "meta work" (not actual code changes or execution) approaches **~80% of the session's context budget**, pause and hand the decision back to the user. Prevents plowing through an entire session on R&D with no execution.

**Signals to watch:**
- Many consecutive `Read` / `Grep` / `Glob` / KB skill invocations against `knowledgebase/` or topic docs
- Long synthesis-writing runs (`/kb-ingest`, `/kb-synthesise`, multi-page writes)
- Multiple `/kb-*`, `/todos-audit`, deep-research agent delegations earlier in the session
- A mostly-planning conversation with few file edits to `/home/mork/work/*`

**When the threshold is approached:**
1. Pause current activity.
2. Summarize what's been gathered / decided so far in 3-5 lines.
3. Ask the user: "We've spent roughly 80% of this session on KB / R&D / planning. Do you want to: (a) continue this thread, (b) pivot to execution using the gathered context, or (c) wrap and resume in a fresh session?"
4. Await explicit user confirmation before continuing past the threshold.

Judgment call — there's no hard token counter. Estimate from tool-call volume and topic. When in doubt, pause and ask. If the user has explicitly asked for deep research ("do a full audit", "research this end-to-end"), the soft-cap can be deferred, but still surface the status when you reach it.

## Git Safety

- **Never push to `main` on actuate-libraries** unless the user explicitly asks. Pushes to main trigger CI auto-publish of stable versions to CodeArtifact — an accidental push can publish broken or unvalidated code. Always use feature branches.

## New Relic Query Rules

When executing NRQL queries via the MCP tool, follow these rules to avoid burning context tokens:

1. **Never `SELECT *`** -- always select specific attributes (`message`, `level`, `container_name`)
2. **Aggregate first, drill second** -- start with `count(*)` / `FACET`, only fetch raw rows if you need specific log lines
3. **Always scope** -- include `cluster_name = 'Connector-EKS'` AND `container_name` for connector queries
4. **Tight time windows** -- use `SINCE 1 hour ago` not `SINCE 7 days ago` unless you need the range
5. **Small LIMIT** -- `LIMIT 10` for FACET queries, `LIMIT 5` for raw rows
6. **Use TIMESERIES for trends** instead of raw data points

**NR deep links are broken** -- all `one.newrelic.com` URLs redirect through a state management layer that strips query params. No dynamic per-site deep link format works. Use `onenr.io` short codes (manual) or NerdGraph `staticChartUrl` (programmatic, PNG only). See KB: `topics/new-relic/notes/concepts/nr-programmatic-deep-links.md`.

See KB: `topics/new-relic/notes/concepts/nrql-efficient-query-patterns.md` and `nr-connector-query-cookbook.md` for query templates.

## Repository Management

When a task requires reading or referencing a repo that isn't cloned locally in `/home/mork/work/`, clone it first:
```bash
cd /home/mork/work && gh repo clone aegissystems/{repo}
```
The canonical list of local vs remote repos is in the KB at `topics/actuate-platform/notes/entities/core-repo-suite.md`. After cloning a new repo, update that note to move it from "Clone on Need" to "Local".

## Knowledge Base Integration

The user maintains an Obsidian KB at `/home/mork/Documents/worklog/knowledgebase/` that serves as the team's architectural memory. **Use it proactively.**

### Session Start: Quick KB Scan

At the start of any session involving Actuate codebases, do a **fast index scan** to see what's relevant:

```bash
# Quick topic list
ls /home/mork/Documents/worklog/knowledgebase/topics/

# Check if we have notes on the current working area
grep -rl "SEARCH_TERM" /home/mork/Documents/worklog/knowledgebase/topics/*/_ summary.md --include="*.md" -l
```

If we have relevant KB content:
- **Read it** and use it as context for the conversation
- **Update/enhance it** if the session produces new knowledge
- **Flag stale content** if `updated:` is older than 14 days

If we don't have relevant KB content:
- **Create a note** once we reach a stopping point — fit the conversation's findings into the appropriate topic
- New topic if nothing fits; concept/synthesis note in an existing topic if it does

This scan should be lightweight (30 seconds, not a deep research pass). The goal is awareness, not comprehension.

### New Task Orientation

When the user gives a new task (feature, bug fix, release, investigation, PR review), **assess the operational landscape before diving in:**

1. **Repo state** — branches, current branch, uncommitted changes, recent commits
   ```bash
   git status && git log --oneline -5 && git branch --show-current
   ```

2. **PR state** — open PRs, their mergeable status, CI checks, review state
   ```bash
   gh pr list --state open
   ```

3. **Blockers first** — before anything else, resolve blockers in this order:
   - Merge conflicts (always first — never ask, just fix them)
   - Dev pins that need stabilization (run `/pre-merge-workflow`)
   - Failing CI checks
   - Unaddressed review comments

4. **Jira context** — check tickets related to the task for status, assignment, and any comments with requirements or constraints

5. **KB context** — read the relevant topic `_summary.md` for architecture, team context, and known issues (see KB Lookup below)

6. **Skill chain** — identify which skills apply to this task type:
   - **Library change:** `/library-update` → `/pre-merge-workflow` → `/stage-release` → `/post-deploy-monitor`
   - **Feature/bug fix (no library change):** `/validate-release` → `/stage-release` → `/post-deploy-monitor`
   - **New API endpoint:** `/api-endpoint-development` → `/write-external-docs` → `/validate-release`
   - **Release/deploy:** `/pre-merge-workflow` → `/stage-release` → `/post-deploy-monitor` → `/overnight-logs`
   - **Investigation:** `/log-check` or `/new-relic-log-review` → `/operational-triage`
   - **PR review:** `/validate-release` checklist

This orientation should happen at the start of every non-trivial task. It prevents the pattern of jumping into code only to discover merge conflicts, stale pins, or blocking CI failures 30 minutes in.

### Before Coding: KB Lookup

When starting any implementation task in an Actuate codebase (`/home/mork/work/*`), **run `/kb-lookup` first** (or do a quick manual read of the relevant topic `_summary.md`) to gather context:
- Architecture decisions and ADRs that constrain the design
- Related services and cross-project dependencies
- Who is working on what (avoid conflicts)
- Known issues and risks
- Prior art and patterns already established

This applies to: bug fixes, new features, refactors, investigations, and any non-trivial code change. Skip only for trivial single-line changes.

### End of Session: KB Update

Before the conversation ends, check: did we learn something the KB doesn't already know? If yes, write it. Reference the `engineering-process` topic for lifecycle process notes, or the relevant service topic for technical findings. See the "After Work: Log to KB" table below for what goes where.

### After Planning: Write a Synthesis

When you create an implementation plan (via plan mode or otherwise), **write a synthesis note** to the KB capturing:
- **What** is being built and **why** (the decision, not just the task)
- **Architectural choices** made and alternatives considered
- **Cross-service impacts** identified during planning
- **File:** `topics/{relevant-topic}/notes/syntheses/{date}_{slug}.md`

Use this frontmatter:
```yaml
---
title: "Plan: Description"
type: synthesis
topic: relevant-topic
tags: [plan, relevant-tags]
jira: "TICKET-123"
created: YYYY-MM-DD
updated: YYYY-MM-DD
author: kb-bot
---
```

### After Work: Log to KB

After completing any significant work, **update the KB** with what was learned:

| Work Type | What to Log | Where |
|-----------|-------------|-------|
| **Bug fix** | Root cause, fix approach, what was surprising | `notes/concepts/{date}_bugfix-{slug}.md` in relevant topic |
| **New feature** | Architecture, integration points, config changes | `notes/concepts/` or `notes/syntheses/` |
| **ADR / Design decision** | Decision, context, alternatives, consequences | `notes/syntheses/{date}_adr-{slug}.md` |
| **Skill creation/update** | What the skill does, how to use it, gotchas | `notes/entities/` in `actuate-platform` topic |
| **Investigation / Research** | Findings, conclusions, recommendations | `notes/syntheses/` in relevant topic |
| **Integration work** | API contracts, auth patterns, partner quirks | `notes/concepts/` in relevant integration topic |

Keep notes concise (200-800 words). Always include `author: kb-bot` and `updated:` date. Cross-link with `[[wikilinks]]`.

### Staleness Awareness

If you read a KB note with `updated:` older than 14 days, treat it as potentially stale. Verify critical facts against the current codebase or Confluence before acting on them.

## Post-Push Audit

After every `git push` to a PR or feature branch, perform an automatic audit:

1. **KB & docs sync** — Check whether any KB notes, security checklists, or repo docs need updating based on what was just pushed. Key questions:
   - Did we add/change RBAC patterns? → Update `security-hardening-checklist.md` and `docs/backend/security.md`
   - Did we add/change API endpoints or models? → **Always** run `/write-external-docs` for customer-facing docs. For inference-api v5 specifically: update `docs/api/v5/detect.md`, `models.md`, per-model pages, and README quick start. Verify `ENDPOINT_ROLE_MAPPING` and Swagger examples match.
   - Did we add/change test patterns? → Update `code-review-checklist.md`
   - Did we add/change config fields, integration types, or factory routing? → Update connector CLAUDE.md and KB topic summaries
   - Did we create or update skills? → Register in the CLAUDE.md skills table
   - Did we bump library versions? → Note in KB if the version catalog in `actuate-libraries/_summary.md` is stale
   - Did we learn something new or hit a surprising failure? → Write a KB synthesis or concept note

2. **Security review** — Quick pass on the pushed changes:
   - Are all user inputs bounded? (max_length, max items, size limits)
   - Are error messages generic? (no internal state leakage)
   - Is RBAC checked before validation?
   - Are discovery/list endpoints filtered by the caller's roles?
   - Are 404 hints filtered by the caller's roles?

3. **CI monitoring** — Watch the CI checks relevant to the repo:
   - Tests passing?
   - Docker / ECR build succeeding? (for connector: ARM64 + x86 matrix)
   - Terraform plan showing expected changes? (for infra repos)
   - Library CI: if pushing to `actuate-libraries` main, verify Publish Stable workflow triggered. If it didn't (GITHUB_TOKEN issue), flag it.
   - uv.lock diff check passing? (for connector PRs)

4. **Deployment chain awareness** — If the push lands on a deployment branch, proactively trigger the next skill in the release chain:
   - Push to **feature branch PR**: suggest `/validate-release` if not yet run
   - Push that **merges to stage**: trigger `/post-deploy-monitor` to start NR health checks
   - Push that **merges to rearchitecture**: trigger `/post-deploy-monitor` and schedule `/overnight-logs` for next morning
   - Push to **actuate-libraries main**: verify stable publish, then remind about bumping connector pins via `/pre-merge-workflow`

This should happen automatically after every push — not only when the user asks.

## Subagent Routing

Custom subagents live at `~/.claude/agents/` and are cataloged in the KB at `topics/engineering-process/notes/entities/agents-catalog.md`. **Prefer delegating to a specialized subagent over doing the work in the parent context** when one matches — they protect the main context from large result dumps and bake in team conventions.

| Task | Subagent | Via Agent tool |
|------|----------|----------------|
| Any NR / NRQL query or log investigation | `nrql-investigator` | `subagent_type: nrql-investigator` |
| Reviewing a PR in `/home/mork/work/*` | `actuate-pr-reviewer` | `subagent_type: actuate-pr-reviewer` |
| Writing a new KB note (concept / synthesis / entity) | `kb-scribe` | `subagent_type: kb-scribe` |
| "Where does X happen in the connector?" / library lookup | `connector-pipeline-expert` | `subagent_type: connector-pipeline-expert` |
| Monitoring a release through CI / deploy / post-deploy health | `release-chain-watcher` | `subagent_type: release-chain-watcher` (often `run_in_background: true`) |
| Jira landscape, workstream status, assignee mapping | `jira-landscape` | `subagent_type: jira-landscape` |

**Exceptions (keep in parent):**
- Trivial one-shot MCP calls (single `get_entity`, single ticket fetch) — agent overhead isn't worth it
- Tasks requiring writes the agent doesn't have (most agents are read-only by design)
- When the skill already covers the flow end-to-end (e.g., `/validate-release`, `/stage-release`) — use the skill; it may internally delegate to an agent

See [[agents-catalog]] in the KB for full per-agent detail, anti-patterns, and the relationship between skills and agents. Update that catalog (and the corresponding `agent-<name>.md` entity) whenever a new agent is added or an existing agent's behavior changes.

## Skill Post-Run Review

After any skill (`/skill-name`) finishes executing, perform a self-review before returning to the user:

1. **Check for errors**: Scan the tool call results from the skill run for failures — failed commands, HTTP errors, file-not-found, permission denied, unexpected output, empty results where content was expected.
2. **Verify outcomes**: Confirm the skill achieved its stated goal. For example:
   - If the skill created files, verify they exist and are non-empty.
   - If the skill ran a sync or deploy, check the final status (workflow passed, pages created, etc.).
   - If the skill ran tests, confirm they passed.
3. **Identify skill-level bugs**: Distinguish between:
   - **Environmental issues** (expired credentials, network errors, missing dependencies) — report to the user, do not modify the skill.
   - **Skill bugs** (wrong file paths, bad assumptions about project structure, incorrect commands, missing steps, outdated instructions) — fix the skill automatically.
4. **Auto-fix skill bugs**: If the error was caused by the skill's own instructions or templates (e.g., a hardcoded path that doesn't exist, a missing step, an incorrect API call pattern), update the skill's `SKILL.md` file to fix the issue so it doesn't recur. Commit the fix with a message like `fix(skill): description of what was wrong`.
5. **Report**: Briefly tell the user what the skill did, whether it succeeded, and if any skill fixes were applied.
