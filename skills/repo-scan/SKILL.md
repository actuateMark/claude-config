---
name: repo-scan
description: Survey open GitHub issues across major Actuate repos. Ranks into high-impact + low-hanging-fruit buckets. Read-only digest. Trigger: '/repo-scan', 'repo scan', 'low hanging fruit'.
user-invocable: true
allowed-tools:
  - Bash
  - Read
  - Grep
  - AskUserQuestion
---

# Repo Scan

Finds high-impact work and low-hanging fruit across Actuate GitHub repos that isn't currently in [[mark-todos]] or assigned to Mark. Complements the Jira-centric auto-sync by surfacing issues that live only on GitHub.

**Read-only.** Produces a digest, never mutates issues or repos.

## Arguments

- No args: all default repos, both categories, top 5 per category, last 30 days
- `--repos <csv>`: override default list (e.g., `--repos vms-connector,actuate-libraries`)
- `--category high|lhf|both` — default `both`
- `--limit <N>` — per-category top-N (default 5)
- `--since <days>` — filter to issues with activity within N days (default 30)
- `--include-assigned` — by default assigned issues are down-ranked; this flag includes them at full weight
- `--refresh` — bypass the daily cache and re-fetch

## Default repo set

Seven repos that account for most of the active engineering work:
- `vms-connector`
- `actuate-libraries`
- `actuate-inference-api`
- `actuate_admin`
- `autopatrol_onboarder`
- `autopatrol-server`
- `camera-ui`

Override with `--repos` for a narrower (or broader) sweep.

## Procedure

### Step 0 — Three-tier preamble (canonical pattern; do not skip)

This skill follows the [[2026-04-30_three-tier-routine-check-pattern|three-tier routine check pattern]]. **Walk the tiers; stop at the first that succeeds.** See `~/.claude/CLAUDE.md` § "Routine Checks: Three-Tier Pattern" for the global rule and [[2026-04-30_morning-prep-scripts-runbook]] for per-script debug playbooks (manual invocation, common errors, where outputs land).

**Tier 1 — Firebat script (canonical)**

```bash
# Read today's pre-computed digest from morning-prep on the Firebat.
DIGEST=$(curl -fsS --max-time 5 "http://mork-firebat/logs/repo-scan-$(date +%F).stdout" 2>/dev/null)
SUMMARY=$(curl -fsS --max-time 5 "http://mork-firebat/logs/morning-prep-latest.summary.json" 2>/dev/null)
# If summary shows repo-scan succeeded today AND digest is non-empty, use it and stop.
```

If the cache is fresh (≤8h) and the summary's `skills["repo-scan"].exit_code == 0`, fold the digest into the caller's flow and exit. **Do not run anything else.** That digest already wrote the KB scan note + per-repo catalogs + 9 dashboard sink signals via Firebat's morning-prep batch.

**Tier 2 — Local laptop script (fallback)**

```bash
if [ -x ~/bin/repo-scan ]; then
  ~/bin/repo-scan "$@"     # honors --repos, --no-kb, --no-sink
  exit $?
fi
```

The script does the full pipeline locally — fetch via `gh issue list` ×7 (open) + ×7 (closed-60d), delegates scoring to `~/.claude/skills/repo-scan/curate.py`, writes the KB scan + per-repo catalogs + dashboard sink. Same Python source as Firebat (canonical at `/home/mork/work/local_network_scripts/files/repo-scan.sh`).

**Tier 3 — LLM skill (last resort + diagnostic)**

If neither Tier 1 nor Tier 2 worked, run the inline LLM-orchestrated flow in Steps 1-7 below. **Additionally, when LLM is the active tier, you have a diagnostic obligation:**

1. Identify why the script failed:
   - `~/bin/repo-scan` not installed → propose installing it (`cp /home/mork/work/local_network_scripts/files/repo-scan.sh ~/bin/repo-scan && chmod 755 ~/bin/repo-scan`)
   - `gh auth status` failed → tell user to `gh auth login`
   - `curate.py` missing or broken → check `~/.claude/skills/repo-scan/curate.py`; if broken, fix and offer to commit the fix
   - Firebat unreachable → note in [[firebat-minipc-access]] follow-ups; was it a tailnet drop or genuine outage?
2. **Patch where mechanical:** if a path bug or regex issue is fixable in the .sh file, edit it now in `/home/mork/work/local_network_scripts/files/repo-scan.sh`, mention the change, suggest a phase-13 redeploy.
3. **Surface to the user** if the failure needs human intervention (creds, IAM, network), with exact remediation commands.
4. **Log the diagnosis** in today's daily note's `## Notes / Learnings` so it doesn't recur silently.

The script is sibling to `~/bin/git-fetch-major-repos.sh` on the Firebat:
- `git-fetch-major-repos` → branches / commits / PRs → `/app/repos/`
- `repo-scan` → issues / scoring / dashboard signals → same `/app/repos/`

Both are pure-Python, both feed the per-repo cards and the code-health leaderboard.

---

### Step 1 — Fetch (LLM-fallback only)

For each repo, in parallel:

```bash
gh issue list --repo aegissystems/<repo> \
  --state open \
  --limit 50 \
  --json number,title,labels,assignees,reactionGroups,comments,createdAt,updatedAt,author,url,body
```

**Cache** to `~/.cache/repo-scan/<YYYY-MM-DD>.json` to avoid re-fetching within the same day. Bypass with `--refresh`.

### Step 2 — Rank

Compute two scores per issue. Both use the labels array and metadata.

**High-impact score:**
| Signal | Weight |
|--------|--------|
| Label matches `/^(p[01]\|critical\|high\|priority\|urgent)/i` | +5 |
| Label matches `/^(bug\|production\|prod-issue\|incident\|regression)/i` | +3 |
| Label matches `/^(security\|sev[012])/i` | +4 |
| Reaction count (capped) | +1 per reaction, max +5 |
| Comment count (capped) | +1 per 2 comments, max +4 |
| Updated within 7 days | +2 |
| Updated within 30 days (but not 7) | +1 |
| Has assignee (someone's on it) | -2 (unless `--include-assigned`) |
| Linked to a PR (in title or body with `#NNN`) | +2 |

**Low-hanging fruit score:**
| Signal | Weight |
|--------|--------|
| Label matches `/^(good-first-issue\|help-wanted\|chore\|docs?\|documentation\|refactor\|test\|cleanup)/i` | +5 |
| Body length >100 chars with checkboxes or "Steps:" pattern | +2 |
| No assignee | +2 |
| Title length <80 chars (suggests tight scope) | +1 |
| Updated within 60 days | +1 |
| Label matches `/^(epic\|complex\|needs-design\|spike)/i` | -5 |
| Body is empty or <30 chars | -2 |

### Step 3 — Select

For each category, pick the top `--limit` issues by score (default 5). Skip issues with score ≤ 0. This `--limit` applies to both the on-screen digest AND the KB scan note — they show the same set.

### Step 4 — Persist digest to KB (primary output)

Write the scan to `topics/repo-backlog/notes/scans/<YYYY-MM-DD>_scan.md`. This is the **durable output** — the KB tracks scans over time, direct GitHub links live here forever.

File template:

```markdown
---
title: "Repo Scan: YYYY-MM-DD"
type: concept
topic: repo-backlog
tags: [scan, opportunities, github]
created: YYYY-MM-DD
updated: YYYY-MM-DD
author: kb-bot
---

# Repo Scan — YYYY-MM-DD

Auto-generated by [[skill-repo-scan|/repo-scan]]. Snapshot at scan time — re-run for fresh data.

**Repos surveyed:** <csv of repo names>
**Time window:** updated within last N days
**Total issues surveyed:** <count>
**Cache:** `~/.cache/repo-scan/YYYY-MM-DD.json`
**Args:** `<the args this scan was called with, if any>`

## 🔥 High Impact

| Repo | # | Title | Labels | Assignee | Score |
|------|--:|-------|--------|----------|------:|
| vms-connector | 1234 | [RTSP leak under N cameras](https://github.com/aegissystems/vms-connector/issues/1234) | `critical`, `bug`, `production` | — | 12 |
| …   | … | …     | …      | …        |   …   |

## 🧹 Low-Hanging Fruit

| Repo | # | Title | Labels | Assignee | Score |
|------|--:|-------|--------|----------|------:|
| camera-ui | 89 | [Typo in README](https://github.com/aegissystems/camera-ui/issues/89) | `docs`, `good-first-issue` | — | 8 |
| …   | … | …     | …      | …        |   …   |

## Picked Up

*(Items promoted to [[mark-todos]] or otherwise acted on. Add rows manually or via [[skill-todos-add|/todos-add]] when promoting a scan item.)*

| Issue | Promoted to | Date |
|-------|-------------|------|
| *(none yet)* | | |

## Related

- [[skill-repo-scan]] — the skill that wrote this
- [[repo-backlog/_summary|repo-backlog topic]]
- [[mark-todos]] — destination for picked items
```

**Key formatting rules:**
- **Title column is a direct markdown link** to the issue URL — one click opens it in GitHub
- **Include the same items as the on-screen digest** — top `--limit` per bucket (default 5), score > 0
- **Sort each bucket by score descending**, ties broken by most-recent-update
- **If the same date's scan file exists, overwrite** (current day is always the latest snapshot). Past days are immutable.

Also update the topic's `_summary.md` "Scans" list to include a new bullet:
```markdown
- [[YYYY-MM-DD_scan|YYYY-MM-DD]] — N high-impact, M LHF across K repos
```

### Step 4b — Refresh per-repo catalog files

Per-repo catalogs at `topics/repo-backlog/notes/concepts/<repo>.md` contain the **full** open-issue inventory for each repo, with an auto-refresh block that this step overwrites and a hand-maintained `## Curated notes` section that must be **preserved**.

Run the companion script:

```bash
python3 ~/.claude/skills/repo-scan/curate.py
```

This script:
1. Reads `/tmp/repo-scan-<repo>.json` (populated by Step 1).
2. Scores each issue (same heuristics as Step 2).
3. Writes the dated scan note (same as Step 4a — safe to run both; overwrites each other idempotently).
4. For each repo with open issues, writes `notes/concepts/<repo>.md`:
   - **Preserves** existing `## Curated notes` section (between the heading and `<!-- BEGIN-AUTO-REFRESH repo-scan -->`).
   - **Regenerates** the auto-refresh block: High-impact top 10, LHF top 10, Codebase-scan follow-up candidates (>180d idle), Label distribution, Full inventory in a `<details>` fold.
   - **Regenerates** frontmatter with full issue-number lists (`high_impact_issue_numbers`, `lhf_issue_numbers`, `stale_issue_numbers`, `full_issue_numbers`) so truncated items stay queryable via Obsidian Bases.

**Curated notes preservation:** the script splices on two sentinels — `## Curated notes` heading and `<!-- BEGIN-AUTO-REFRESH repo-scan -->`. Do not rename or remove these. Hand-written content between them survives across re-runs.

**Stale section framing:** the "Codebase-scan follow-up candidates" section (>180d idle) is **not** a bulk-close list. Each stale ticket needs per-case review — walk `git log`, comment with commit refs if addressed, or bump with "still valid as of <date>." The section title and intro reflect this.

### Step 5 — Present the digest to the user

After persisting, show the user a **terse summary**:
- File written: `topics/repo-backlog/notes/scans/<YYYY-MM-DD>_scan.md`
- Top 3 high-impact + top 3 LHF (1 line each, direct URL)
- Total issues surveyed, timestamp

Keep on-screen output short — the KB file is the complete record.

### Step 6 — Optional handoff

If called via `/daily-scope --with-repo-scan`: return the structured digest (not the formatted markdown) to the caller, which folds it into the scope interview as additional options. The KB file is **still written** — scan persistence is not optional.

### Step 7 — Optional drill

After persisting + presenting the digest, ask: "Want to see the body of any issue?" via `AskUserQuestion` listing top 4 titles. If the user picks one, fetch that issue's body and show it. Otherwise exit.

**Drill output goes to the user, not the KB** — the bodies are in GitHub already, no need to duplicate in the scan note.

## Caveats & rules

- **Respect rate limits.** `gh` uses `GITHUB_TOKEN`; 500 × 7 = 3500 issues max per scan, well under the 5K/hour limit. Cache means typical re-runs cost zero. Use `--limit 500` in Step 1's `gh issue list` for repos known to have >50 open (vms-connector currently ~100).
- **Down-rank assigned issues by default.** The goal is to find work that isn't already owned. `--include-assigned` restores full weight when the user wants a full landscape view.
- **Never auto-assign or auto-comment.** This skill reads only.
- **Don't infer issue priority from title keywords alone.** Labels and reactions are signal; title alone is noise (too many false positives from e.g. "Critical path: button color").
- **Flag cross-referenced issues.** If an issue references another (`#NNN`) or a Jira ticket (`ENG-123`), surface that — it's context for ranking.
- **Curated notes are sacred.** Step 4b's `curate.py` preserves hand-written content in each per-repo catalog. If you edit the script, verify the sentinel-splicing logic still works before running in the KB.
- **Stale ≠ close.** Issues >180d idle are for codebase-scan follow-up, not bulk closure. Keep that framing in any output or summary you produce.

## Refresh cadence

Current setting: **daily** (via `/daily-scope` auto-invocation, per user preference 2026-04-23). Per-repo catalogs are overwritten every morning; Curated notes are preserved.

**Review 2026-04-30** — decide if daily is the right cadence or switch to weekly. Criteria to decide on:
- Is the auto-refresh churn noisy in git diffs?
- Are users actually consulting the per-repo files daily, or only on repo-backlog dives?
- Does the daily overwrite ever collide with someone mid-editing the Curated notes?

If daily is too noisy, switch to weekly by adding a date gate in curate.py (e.g., `if NOW.weekday() != 0: skip_concepts()`), keeping the dated scan daily.

## Related

- [[repo-backlog/_summary|repo-backlog topic]] — where scan notes are persisted
- [[skill-daily-scope]] — invokes this skill via `--with-repo-scan`
- [[skill-todos-add]] — for promoting a scan item to a workstream
- [[mark-todos]] — where picked issues eventually get added as workstream items or Today's Scope
- [[automation-jira-sync]] — the Jira-centric counterpart (mark-todos auto-sync only covers tickets assigned to Mark; this skill covers GitHub issues regardless of assignee)
