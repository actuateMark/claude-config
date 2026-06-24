---
name: dashboard-check
description: Generate the local operational dashboard at ~/Documents/worklog/dashboard/. Classifies signals green/yellow/red, regression-detects, writes dated snapshot + observations sink. Trigger: '/dashboard-check', 'dashboard'.
user-invocable: true
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash
  - Glob
  - Grep
  - mcp__newrelic__execute_nrql_query
  - mcp__newrelic__list_recent_logs
---

# /dashboard-check

Local static HTML operational dashboard — the forcing function for **regression prevention + fastest-possible detection**, which is the #1 operational priority per [[engineering-process/_summary]].

**Load-bearing principle:** `Errors=0` is not a health signal. Activity-marker log lines + downstream side effects are. Every launch runs `/dashboard-check`. No release is verified until the dashboard is GREEN against the deployed component for at least one full cron cycle / one real-traffic window.

## Arguments

- No args: full scan of all `enabled: true` signals in `config/signals.json`, renders complete HTML
- `--component <name>`: narrow to one component (vms-connector, autopatrol_onboarder, alert-pipeline, etc.)
- `--gate <pr-or-commit>`: release-gate mode — narrow to the component(s) the merge touched, block until GREEN or 15-min timeout
- `--diff <YYYY-MM-DD>`: regenerate comparing against a specific prior snapshot
- `--open`: open the generated index.html in default browser after writing

## Procedure

### Step 0 — Preflight

Verify the credentials needed for the enabled signals are live. Mirrors `/daily-scope` Step 2bb.

Run the parallel checks:

```bash
AWS_PROFILE=prod aws sts get-caller-identity 2>&1 | head -3
gh auth status 2>&1 | head -3
```

Also probe NR MCP with a trivial query (this is a live MCP call, not a bash command — execute via the tool `mcp__newrelic__execute_nrql_query` with NRQL `SELECT count(*) FROM Log SINCE 1 minute ago LIMIT 1`).

**Pass criteria:** all three preflight probes return successfully. If any fails, **pause and ask the user to remediate** before continuing — do NOT run the signal queries with known-broken credentials.

### Step 1 — Load catalog + baselines

Read `~/.claude/skills/dashboard-check/config/signals.json` and `config/baselines.json`.

Filter to `enabled: true` signals. If `--component` was given, additionally filter to signals with matching `component` field.

Group signals by `source` (cw_log / cw_metric / cw_sqs / nr_log / nr_k8s_container_sample / nr_issues / nr_transaction / aws_ce).

### Step 2 — Collect

For the Phase 1a MVP, you will only run signals with `enabled: true`. The full collector matrix is implemented incrementally across Phase 1b.

#### 2a. AWS CloudWatch (CW) signals

For each CW log / metric / sqs signal, run the appropriate `aws` CLI command under `AWS_PROFILE=prod`. Capture the numeric output.

For Phase 1a the one enabled CW pair is:

**`onboarder_activity_us`** — count `get_sites HTTP` lines in `/aws/lambda/immix-autopatrol-onboarding` (us-west-2) in the last 1 hour. This fingerprint fires per-tenant-per-invocation and is a reliable proof-of-work signal; calibrated 2026-04-23 after the postmortem's "Fetched N contracts" fingerprint didn't match actual logs.

```bash
AWS_PROFILE=prod aws logs filter-log-events \
  --region us-west-2 \
  --log-group-name /aws/lambda/immix-autopatrol-onboarding \
  --start-time $(( $(date -u +%s) * 1000 - 3600000 )) \
  --end-time $(date -u +%s)000 \
  --filter-pattern 'get_sites HTTP' \
  --query 'events | length(@)' --output text
```

**`onboarder_lambda_invocations_us`** — Lambda invocation count over 1h:

```bash
AWS_PROFILE=prod aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda --metric-name Invocations \
  --dimensions Name=FunctionName,Value=immix-autopatrol-onboarding \
  --region us-west-2 \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 3600 --statistics Sum \
  --query 'Datapoints[0].Sum' --output text
```

Write both results to `$TEMPDIR/cw_results.json` as `{"signal_id": value, ...}`.

#### 2b. New Relic (NR) signals

For each NR signal (`source: "nr_*"`) that is `enabled: true`, execute the NRQL via the `mcp__newrelic__execute_nrql_query` tool. Capture the scalar count or FACET breakdown.

Write to `$TEMPDIR/nr_results.json`.

Phase 1a has no NR signals enabled. Phase 1b will wire the ~12 NR signals in the catalog.

#### 2c. GitHub (GH) signals

None in Phase 1a. Reserved for SSL-cert + CI-health signals in Phase 2.

#### 2d. AWS Cost Explorer (CE)

None enabled in Phase 1a. Phase 1b wires the two cost signals (daily spend delta + weekly top-10 delta).

### Step 3 — Render

Invoke the Python renderer:

```bash
~/.claude/skills/dashboard-check/run.sh render \
  --tempdir "$TEMPDIR" \
  --output-root "$HOME/Documents/worklog/dashboard" \
  --snapshot-date "$(date -u +%Y-%m-%d)"
```

The renderer:
1. Loads `config/signals.json` + `config/baselines.json`
2. Reads each `$TEMPDIR/*_results.json` + merges into a single observations dict
3. Classifies each observed signal against its thresholds (green/yellow/red/informational)
4. Applies regression rules 1 (silent drop), 2 (new pattern in top-N), 5 (activity-marker anti-pattern)
5. Appends one sink record per signal via `sink.py::write_observation()`
6. Renders `$OUTPUT_ROOT/$DATE/index.html` + `components/*.html` + `regressions.html` + writes `data.json`
7. Updates the `$OUTPUT_ROOT/latest` symlink
8. Prints a 3-5 line console summary + path
9. Returns exit code 0 (all green) / 1 (any yellow) / 2 (any red)

### Step 4 — Console output + optional browser

If `--open` was given, open the generated `index.html`:

```bash
xdg-open "$HOME/Documents/worklog/dashboard/latest/index.html" &
```

If `--gate <commit>` was given, and the exit code is 2 (red), surface a rollback dialogue to the user: "Dashboard RED on the deployed component; consider rolling back? [signals: X, Y, Z]."

## Exit codes (release-gate contract)

- `0` — all enabled signals green. Launch verified.
- `1` — at least one yellow, no red. Launch proceeds with caution; follow-up required.
- `2` — at least one red. Launch must be investigated before declaring verified. Release skills should BLOCK on this.

CI / release-skill invocation pattern:
```bash
/dashboard-check --gate "$GIT_SHA" || {
  if [ $? -eq 2 ]; then
    echo "Dashboard RED after deploy. Roll back or investigate."
    exit 1
  fi
}
```

## Regression rules (Phase 1a: rules 1/2/5)

- **Rule 1 — Silent drop:** signal with `regression_rules` containing `"silent_drop"` where today's value < 10% of prior-day value AND prior-day > minimum threshold → **RED**. Catches values going to zero when normally non-zero.
- **Rule 2 — New pattern:** FACET-style signal with `regression_rules` containing `"new_pattern"` — any facet key in today's top-N that wasn't in prior-day or 7d trailing top-N → **YELLOW** (or **RED** if `critical: true`).
- **Rule 5 — Activity-marker anti-pattern:** paired signals (via `pair_with`) where invocations > 10/h AND activity < 10% of invocations → **RED**. Catches the 2026-04-23 onboarder silent-early-return fingerprint — the canonical acceptance test.

Rules 3 (baseline drift 2σ) and 4 (chronic-offender promotion) land in Phase 1b.

## Sink integration

Every signal evaluated writes one record to `~/Documents/worklog/dashboard/sink/observations.jsonl` via the `sink.py` helper with `source_skill="dashboard-check"`. Schema at `sink/.schema.md`.

Other skills write to the sink with their own `source_skill` identifier (`daily-scope.fan-out`, etc.) — the dashboard's Morning summary section aggregates these for cross-skill observability.

## Related

- **Adding a new signal:** [[2026-04-27_dashboard-signal-cookbook]] — full cookbook, per-source recipes, threshold calibration, gotchas
- [[2026-04-27_iam-rolesanywhere-minipc]] — AWS auth on minipc cron (Roles Anywhere flow that backs cw_*/ce_* signals)
- [[2026-04-23_dashboard-sketch]] — authoritative design sketch
- [[2026-04-23_postmortem-onboarder-healthcheck]] — incident that motivated this skill
- [[mark-todos]] §9 — workstream tracker (Phase 1a scope)
- Plan: `/home/mork/.claude/plans/clever-tickling-swing.md`
- Schema: `~/Documents/worklog/dashboard/sink/.schema.md`
- Catalog: `~/.claude/skills/dashboard-check/config/signals.json`
