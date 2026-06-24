# Global Rules

## Session Start Ritual

At the start of any Actuate-context session, before substantive work:

1. **Read `topics/personal-notes/notes/entities/mark-todos.md`** — source of truth for workstreams (§N) and today's scope.
2. **Check `## Active Session Claims`** (between `<!-- BEGIN-SESSION-CLAIMS -->` / `<!-- END-SESSION-CLAIMS -->` sentinels). If your planned scope overlaps an active claim, warn the user. SessionStart hook prints active claims into initial context automatically.
3. **Check `## Today's Scope`** (between `<!-- BEGIN-TODAY-SCOPE -->` / `<!-- END-TODAY-SCOPE -->`):
   - Today with unchecked items → surface them; ask which to pick up.
   - Older date with unchecked items → suggest `/daily-wrap` for that date, then `/daily-scope` for today.
   - Empty/missing → suggest `/daily-scope`.
4. **Check frontmatter `updated:`** — if >3 days old, flag discipline slip.
5. **Match the task to a skill** if applicable. Daily skills: `/daily-scope`, `/daily-wrap`, `/todos-audit`, `/todos-add`, `/claim`, `/release`, `/claims`.

Skip only for trivial one-off questions that don't touch personal work.

## Session Claims (multi-session coordination)

Multiple Claude Code sessions can run in parallel. The session-claims table inside `mark-todos.md` (between `<!-- BEGIN-SESSION-CLAIMS -->` / `<!-- END-SESSION-CLAIMS -->`) is the shared coordination state. Schema: `| Label | Scope | CWD | Started | Heartbeat |`, UTC ISO-8601 minute-precision.

**Rules:**
1. Before doing tracked work, check the claims table. If your planned scope overlaps another session's claim (same CWD or same §N), warn: "Session `<label>` is already claimed for `<scope>` — continue anyway?"
2. When the user starts a non-trivial tracked §N item and no claim exists for this session, suggest `/claim`.
3. When work wraps (user says "done", runs `/daily-wrap`, switches scope), suggest `/release`.
4. If a claim's heartbeat is >30 min stale and the user has moved on, offer `/release <label>`.

**Don't claim:** one-shot questions, read-only exploration, edits <15 min.

## Task Completion Ritual

When you finish a tracked unit (mark-todos line item, Jira ticket, workstream sub-task), do all four at the moment of closure:

1. **Update `mark-todos` — distribute, don't accumulate.**
   - Today's Scope picks: flip `[ ]` → `[x]` (stays until `/daily-wrap`).
   - §N workstream sub-items: **move the bullet** to today's daily note `## Closed Sub-items` under `**§N — <title>:**`, preserving original text. Then remove the line from mark-todos.
   - Add a one-line completion hook (PR #, merge commit, wikilink).
   - If the item unblocked something else, remove the `*(blocked by ...)*` marker.
   - Whole-workstream closure: copy the §N to daily note `## Closed Workstreams`, remove from mark-todos, add an Archive table row.
2. **Log to KB** per the "After Work: Log to KB" table below. Filename `YYYY-MM-DD_slug.md`; mark-todos hook should wikilink to it.
3. **Append to today's daily note stub** at `topics/personal-notes/notes/daily/YYYY-MM-DD.md` (template in that dir's README). Add a bullet under `## Closed Line Items`. Don't fill `## Summary` — that's `/daily-wrap`'s job.
4. **If push/merge involved**, run the Post-Push Audit.

Skip only for trivial untracked work.

## Mark-todos discipline (file is hot-path; keep it lean)

`mark-todos.md` is **a tracker, not a write-up**. It's read every session; bloat is friction. Detail belongs in KB notes that mark-todos cross-links to via wikilinks.

**Per-§N section budget:** ~30 lines target, 60 lines hard ceiling. Beyond that → factor inline content into a KB synthesis note and replace with a wikilink.

**Belongs inline in §N:**
- Title line + ticket + status + priority
- One-paragraph context (≤3 sentences) OR a status table
- The actual checkboxes (open work)
- Cross-references via wikilinks

**Does NOT belong inline:**
- Architecture explanations → KB synthesis
- Decision records → KB synthesis (`{date}_adr-{slug}.md`)
- Verbose sub-bullets explaining what each task means — checkbox text says it
- Quoted output / log dumps — link to a daily note or a `*-installed.md` concept
- Per-phase progress narratives — that's what `*-phase-N-installed.md` notes are for

**When updating a bloated §N:** trim aggressively. Git history retains the old form. The KB notes are the durable artifact. mark-todos is the live surface — keep it scannable.

`/todos-audit` enforces this with a size check that flags any §N over 60 lines. Reminder, not a blocker.

## Session Budget Management

KB reads, greps, syntheses, scans, and planning chew through context. When cumulative meta-work approaches **~80% of session budget**, pause and ask:

> "We've spent ~80% of this session on KB / R&D / planning. Continue, pivot to execution, or wrap and resume in a fresh session?"

Signals: many consecutive `Read`/`Grep`/KB skill calls; long synthesis runs; multiple `/kb-*` or `/todos-audit` invocations; mostly-planning conversation with few code edits. Judgment call — no hard counter. Defer the cap if user explicitly asked for deep research, but still surface status.

## Python Package Management

Use **`uv`** for new Python projects. Never `pip install` / `requirements.txt` / `python -m venv` directly.

- Add dep: `uv add <pkg>` (writes `pyproject.toml` + `uv.lock`)
- Sync: `uv sync` (creates `.venv` deterministically)
- Run: `uv run <bin>` or `uv run python ...`
- Update locks: `uv lock --upgrade`

Scaffolding: `pyproject.toml` `[project]` block (not requirements.txt), installer runs `uv sync`, systemd can call `.venv/bin/<bin>` or `uv run`. Existing `requirements.txt` projects: don't migrate unprompted. Install: `curl -LsSf https://astral.sh/uv/install.sh | sh`.

## Git Safety

- **Never push to `main` on actuate-libraries** unless user explicitly asks. Pushes auto-publish stable to CodeArtifact.
- **The dev → stable transition lives in the squash commit message.** At merge time:
  1. Squash subject + body MUST contain `[patch:<package>]` (or `[minor:`, `[major:`) — triggers `bump-stable`.
  2. Squash subject + body must NOT contain any CI-skip directive token. GitHub Actions scans the FULL commit message for these and aborts ALL workflows (build, deploy, version-bump, reset-stage, sonar) if any token appears anywhere — including inside backticks, inside code fences, inside instructional prose, inside example blocks. They are NOT escaped by markdown. The auto-generated `Bump versions for: <package>` commits embed these tokens — strip those lines from the squash body entirely.
  3. **NEVER write the literal CI-skip tokens anywhere in a PR body or commit message** — not in instructions, not in explanatory prose, not in "what NOT to use" examples, not in fenced code blocks. If you need to reference them, use paraphrase only: "the CI-skip markers", "the auto-generated bump commits", "the dev-bump bot tokens". The specific tokens themselves must NEVER appear in the message text.
- **Default `gh pr merge --squash` is unsafe.** Always pass explicit `--subject` (PR title with `[patch:<package>]` preserved) and `--body` (clean — no CI-skip tokens anywhere), or edit in the GitHub UI.
- **Before any PR-body edit on a library-or-connector repo, grep your drafted body for the CI-skip token forms** (no-ci with any spelling, ci-skip, ci skip, skip-ci, skip ci, skip-actions, actions-skip). If any match, rewrite using paraphrase.

Bitten 2026-04-22 (PR #341 — strip step missed in squash body). Bitten again 2026-05-11 (PR #1688 — token appeared in instructional prose explaining what NOT to use; ALL rearch workflows skipped including build/deploy/reset-stage/sonar; required manual `workflow_dispatch` to recover). See `feedback_library_no_dev_versions.md` and `feedback_ci_skip_tokens_anywhere.md`.

## New Relic Query Rules

1. **Never `SELECT *`** — name attributes (`message`, `level`, `container_name`).
2. **Aggregate first, drill second** — `count(*)` / `FACET` before raw rows.
3. **Always scope** — include `cluster_name = 'Connector-EKS'` AND `container_name` for connector queries.
4. **Tight time windows** — `SINCE 1 hour ago` not `SINCE 7 days ago`.
5. **Small `LIMIT`** — 10 for FACET, 5 for raw rows.
6. **Use TIMESERIES for trends.**

NR deep links are broken (state layer strips params). Use `onenr.io` short codes (manual) or NerdGraph `staticChartUrl` (programmatic, PNG only). See KB: `topics/new-relic/notes/concepts/nrql-efficient-query-patterns.md`, `nr-connector-query-cookbook.md`, `nr-programmatic-deep-links.md`.

## Routine Checks: Three-Tier Pattern

Routine checks (`/dashboard-check`, `/repo-scan`, `/autopatrol-overnight-check`, `/autopatrol-cleanup-lambda-check`, `/kb-recap`, etc.) follow this order. **Stop at the first that succeeds:**

1. **Tier 1 — Firebat script** at `~/bin/<name>` on `mork-firebat`, systemd `--user` timer. Writes to `~/.local/state/claude-jobs/`, `~/.local/state/minipc-tasks/`, dashboard sink. Zero tokens.
2. **Tier 2 — Local laptop script** at `~/bin/<name>` (deployed via `/home/mork/work/local_network_scripts/files/`). Use when Firebat unreachable.
3. **Tier 3 — LLM skill** at `~/.claude/skills/<name>/`. Last resort. When Tier 3 runs: diagnose why scripts failed, patch the script if possible, surface env issues, log to daily note `## Notes / Learnings`.

Anti-patterns: don't run `claude -p` on Firebat (autopatrol regression 2026-04-30); don't skip the laptop tier; surface Tier-1 cache staleness >8h.

Full rationale + retrofit guide: `topics/engineering-process/notes/syntheses/2026-04-30_three-tier-routine-check-pattern.md`. Conversion inventory: `topics/personal-laptop/notes/syntheses/2026-04-30_firebat-script-conversion-candidates.md`.

## Repo Cloning

When a task needs a repo not in `/home/mork/work/`, clone first: `cd /home/mork/work && gh repo clone aegissystems/{repo}`. Update `topics/actuate-platform/notes/entities/core-repo-suite.md` to move it from "Clone on Need" to "Local".

## Knowledge Base Integration

KB at `/home/mork/Documents/worklog/knowledgebase/`. Use proactively but cheaply.

**Obsidian CLI is installed at `~/.local/bin/obsidian`** on both the laptop and firebat — it talks to the running Obsidian instance over a unix socket and exposes the vault's index. Prefer it over recursive Grep/Glob for these question shapes:

| Question | CLI command |
|---|---|
| "Who links to X?" | `obsidian backlinks file=X` |
| "What files have tag #X?" | `obsidian tag name=#X` |
| "Which tags exist + counts?" | `obsidian tags counts` |
| "What broken wikilinks?" | `obsidian unresolved` |
| "Orphan / dead-end notes?" | `obsidian orphans` / `obsidian deadends` |
| "Free-text search with context" | `obsidian search:context query="..."` |
| "Frontmatter property audit" | `obsidian properties` |

Health probe: `~/.local/bin/obsidian vault 2>&1 | head -1`. If it fails (Obsidian not running), fall back to Read/Grep. **Don't** use the CLI for synthesis-level reasoning over file contents — `/kb-ask`-style "what does the KB say about X" still needs file reads. Full capability matrix at `topics/obsidian/notes/entities/obsidian-cli.md`; retrofit history at `topics/obsidian/notes/syntheses/2026-04-30_kb-skill-cli-retrofit.md`.

**Before coding** in any Actuate repo: run `/kb-lookup` (or read the relevant topic `_summary.md`). Skip only for trivial single-line changes. The skill walks the cost-ordered retrieval ladder; mirror it if querying directly.

**After completing significant work**, log per this table:

| Work Type | Where |
|---|---|
| Bug fix | `notes/concepts/{date}_bugfix-{slug}.md` in relevant topic |
| New feature | `notes/concepts/` or `notes/syntheses/` |
| ADR / design decision | `notes/syntheses/{date}_adr-{slug}.md` |
| Skill creation/update | `notes/entities/` in `actuate-platform` |
| Investigation / research | `notes/syntheses/` in relevant topic |
| Integration work | `notes/concepts/` in relevant integration topic |

Notes: 200-800 words, `author: kb-bot`, `updated:` date, cross-link with `[[wikilinks]]`.

**After planning** (plan mode or otherwise): write a synthesis at `topics/{topic}/notes/syntheses/{date}_{slug}.md` capturing the *what*, *why*, choices considered, and cross-service impacts.

**Staleness:** if a note's `updated:` is >14 days old, verify critical facts against current code/Confluence before acting.

**New task orientation:** before diving in, run `git status && gh pr list --state open` and resolve blockers in order: merge conflicts → dev pins (`/pre-merge-workflow`) → failing CI → unaddressed reviews. Then check Jira context and the relevant KB topic.

## Post-Push Audit

After every push to a PR or feature branch, audit automatically:

1. **KB & docs sync** — RBAC changes → `security-hardening-checklist.md` + `docs/backend/security.md`. API endpoint/model changes → run `/write-external-docs` (for inference-api v5: also `docs/api/v5/detect.md`, `models.md`, per-model pages, README; verify `ENDPOINT_ROLE_MAPPING`). Test patterns → `code-review-checklist.md`. Config/factory routing → connector CLAUDE.md + topic summaries. New skills → register in skills table. Library bumps → check `actuate-libraries/_summary.md` version catalog. Surprising failures → write a synthesis.
2. **Security review** — bounded user inputs, generic error messages, RBAC before validation, list/discovery endpoints filtered by caller's roles, 404 hints filtered by caller's roles.
3. **CI monitoring** — tests, ECR build (connector: ARM64 + x86), Terraform plan, library Publish Stable workflow, uv.lock diff (connector).
4. **Deployment chain** — feature branch PR → suggest `/validate-release`. Merged to stage → trigger `/post-deploy-monitor`. Merged to rearchitecture → `/post-deploy-monitor` + schedule `/overnight-logs`. Pushed to actuate-libraries main → verify Publish Stable, remind about `/pre-merge-workflow` for connector pins.

## Subagent Routing

Custom subagents at `~/.claude/agents/`, cataloged at `topics/engineering-process/notes/entities/agents-catalog.md`. **Prefer delegating to a specialized subagent over working in parent context** when one matches — they protect main context and bake in conventions. Each agent's `description` specifies when to invoke it; that's the routing source of truth.

Exceptions (keep in parent): trivial one-shot MCP calls, write-tasks the read-only agents lack, flows already covered end-to-end by a skill.

## Skill Post-Run Review

After any `/skill` finishes:

1. Scan tool results for failures (errors, empty output, file-not-found, permission denied).
2. Verify outcomes: files created exist + non-empty; sync/deploy reached terminal state; tests passed.
3. Distinguish env issues (creds, network, deps — report; don't modify skill) from skill bugs (wrong paths, bad assumptions, outdated commands — auto-fix `SKILL.md` and commit `fix(skill): ...`).
4. Briefly report what ran, succeeded, and any skill fixes applied.
