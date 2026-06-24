---
name: autopatrol-check
description: Check autopatrol health: overnight logs, site status, deployment verification. Distinct from /autopatrol-cleanup-lambda-check. Trigger: '/autopatrol-check', 'autopatrol health'.
user-invocable: true
allowed-tools:
  - Bash
  - Read
  - Grep
  - Glob
  - Agent
  - mcp__newrelic__execute_nrql_query
  - mcp__newrelic__list_available_new_relic_accounts
  - mcp__kubefwd__list_k8s_namespaces
---

# AutoPatrol System Health Check

Run a comprehensive health check across the autopatrol pipeline: k8s cronjobs, VMS connector pods, SQS queue flow, and the autopatrol microservice.

## Arguments

- No args or `prod`: Check production autopatrol sites (default)
- `dev` or `staging`: Check staging/dev autopatrol sites
- A specific site ID (e.g. `41158`): Focus on a single site

## Environment Config

| Environment | CronJob Prefix | SQS Queue | Image Tag | NR Account |
|-------------|---------------|-----------|-----------|------------|
| **prod** | `connector-` (no staging prefix) | `autopatrol_jobs.fifo` | `:latest` | 3421145 |
| **staging** | `staging-connector-` | `autopatrol_jobs_dev.fifo` | `:stage` | 3421145 |

## Known Prod Sites

| Site ID | Name | Immix siteId | Schedule |
|---------|------|-------------|----------|
| 41158 | Live Site 2 | 9 | every 30min (28,58) |
| 41178 | Vehicle Test | 10 | every 30min (28,58) |
| 45061 | Camect Test | 15 | hourly (:58) |
| 37837 | Test - RTSP\Generic | 5 | hourly (:58) |
| 40672 | AutoPatrol-Live | 7 | hourly (:58) |

## Step 0 — Three-tier preamble (canonical pattern; do not skip)

This skill follows the [[2026-04-30_three-tier-routine-check-pattern|three-tier routine check pattern]]. **Walk the tiers; stop at the first that succeeds.** See `~/.claude/CLAUDE.md` § "Routine Checks: Three-Tier Pattern" for the global rule and [[2026-04-30_morning-prep-scripts-runbook]] for per-script debug playbooks.

**Tier 1 — Firebat script (canonical)**

```bash
DIGEST=$(curl -fsS --max-time 5 "http://mork-firebat/logs/autopatrol-overnight-check-$(date +%F).stdout" 2>/dev/null)
SUMMARY=$(curl -fsS --max-time 5 "http://mork-firebat/logs/morning-prep-latest.summary.json" 2>/dev/null)
```

If the cache is fresh (≤8h) and the summary's `skills["autopatrol-overnight-check"].exit_code == 0`, fold the digest into the caller's flow and exit. The script discovers active sites dynamically via NRQL `capture()` — site IDs are no longer hardcoded.

**Tier 2 — Local laptop script (fallback)**

```bash
if [ -x ~/bin/autopatrol-overnight-check ]; then
  ~/bin/autopatrol-overnight-check "$@"
  exit $?
fi
```

Source: `/home/mork/work/local_network_scripts/files/autopatrol-overnight-check.sh`. Auth: NR API key at `~/.config/newrelic/key`.

**Tier 3 — LLM skill (last resort + diagnostic)**

If neither tier worked, run the inline checks below. **When LLM is the active tier, you have a diagnostic obligation** — surface the script error, propose a fix where mechanical (NRQL repair, missing module install, path fix), surface user-needs-to-act items (NR key rotation), and log the diagnosis in today's daily note. See [[2026-04-30_three-tier-routine-check-pattern]] § "Tier 3" for the full checklist.

**Note on §1 + §2 below (k8s checks):** the script DEFERS k8s cronjob/pod checks because the Firebat doesn't have EKS access yet. NR log activity is a strong proxy ("if no patrols are running, k8s is broken"). If a site shows red, run `kubectl get cronjobs -n rearchitecture | grep autopatrol` and `kubectl get pods -n rearchitecture | grep autopatrol` from the laptop.

**Note on the SKILL.md "Known Prod Sites" table:** that list went stale (sites 41158/41178/45061/37837/40672 no longer appear in logs). The Tier 1 script discovers sites dynamically — prefer the script's output over the hardcoded table for what's actually running.

---

## Checks to Run (LLM-fallback only)

Execute these checks in order. Run independent checks in parallel where possible. Use the New Relic MCP tool (`mcp__newrelic__execute_nrql_query` with `account_id: 3421145`) for log queries and `kubectl` via Bash for k8s checks.

### 1. K8s CronJob Health

```bash
kubectl get cronjobs -n rearchitecture | grep autopatrol
```

For each cronjob check:
- **LAST SCHEDULE**: Flag if `<none>` (never ran) for cronjobs older than 2 hours
- **SUSPEND**: Flag if `True`
- **Image tag**: Run `kubectl get cronjob <name> -n rearchitecture -o jsonpath='{.spec.jobTemplate.spec.template.spec.containers[0].image}'` for each. Flag `:stage` on prod or `:latest` on staging as mismatched.

For **prod**, filter to cronjobs NOT prefixed with `staging-`.
For **staging**, filter to cronjobs prefixed with `staging-`.

### 2. VMS Connector Pod Status

```bash
kubectl get pods -n rearchitecture --sort-by=.metadata.creationTimestamp | grep autopatrol | tail -30
```

Flag:
- `CrashLoopBackOff` or `Error` status
- `OOMKilled` (check with `kubectl get pods -n rearchitecture -o json | jq` if needed)
- Pods running longer than 30 minutes (may be stuck — normal for large sites like 40672 is ~25min)

### 3. SQS Queue Flow (New Relic)

```nrql
SELECT count(*) FROM Log
WHERE container_name = 'autopatrol-server'
AND message LIKE '%Received message from queue%'
SINCE 24 hours ago TIMESERIES 1 hour
```

Flag: Any hour with 0 messages during expected active hours (roughly 14:00-06:00 UTC for US sites, varies by timezone).

### 4. Autopatrol Server Health (New Relic)

Run these queries in parallel:

**Patrol counts per site:**
```nrql
SELECT count(*) FROM Log
WHERE container_name = 'autopatrol-server'
AND message LIKE '%Processing patrol_id%'
AND (message LIKE '%41158%' OR message LIKE '%40672%' OR message LIKE '%45061%' OR message LIKE '%37837%' OR message LIKE '%41178%')
SINCE 24 hours ago
FACET cases(
  WHERE message LIKE '%41158%' AS '41158',
  WHERE message LIKE '%40672%' AS '40672',
  WHERE message LIKE '%45061%' AS '45061',
  WHERE message LIKE '%37837%' AS '37837',
  WHERE message LIKE '%41178%' AS '41178'
)
```

**Server errors:**
```nrql
SELECT count(*) FROM Log
WHERE container_name = 'autopatrol-server'
AND level = 'ERROR'
SINCE 24 hours ago
```

**Detections (patrols with actual analysis results):**
```nrql
SELECT count(*) FROM Log
WHERE container_name = 'autopatrol-server'
AND message LIKE '%RESPONSE DATA%'
AND message LIKE '%Analysis completed%'
SINCE 24 hours ago
FACET cases(
  WHERE message LIKE '%41158%' OR message LIKE '%Live Site 2%' AS '41158',
  WHERE message LIKE '%41178%' OR message LIKE '%Vehicle Test%' AS '41178',
  WHERE message LIKE '%40672%' OR message LIKE '%AutoPatrol-Live%' AS '40672',
  WHERE message LIKE '%45061%' OR message LIKE '%Camect%' AS '45061',
  WHERE message LIKE '%37837%' OR message LIKE '%RTSP%' AS '37837'
)
```

**CNCTNFAIL counts:**
```nrql
SELECT count(*) FROM Log
WHERE container_name = 'autopatrol-server'
AND message LIKE '%CNCTNFAIL%'
SINCE 24 hours ago
FACET cases(
  WHERE message LIKE '%41158%' AS '41158',
  WHERE message LIKE '%41178%' AS '41178',
  WHERE message LIKE '%40672%' AS '40672',
  WHERE message LIKE '%45061%' AS '45061',
  WHERE message LIKE '%37837%' AS '37837'
)
```

**Healthcheck uploads:**
```nrql
SELECT count(*) FROM Log
WHERE cluster_name = 'Connector-EKS'
AND message LIKE '%uploading healthcheck%'
AND (message LIKE '%41158%' OR message LIKE '%40672%' OR message LIKE '%45061%' OR message LIKE '%37837%' OR message LIKE '%41178%')
SINCE 24 hours ago
FACET cases(
  WHERE message LIKE '%41158%' AS '41158',
  WHERE message LIKE '%40672%' AS '40672',
  WHERE message LIKE '%45061%' AS '45061',
  WHERE message LIKE '%37837%' AS '37837',
  WHERE message LIKE '%41178%' AS '41178'
)
```

### 5. Connector Pod Errors (New Relic)

```nrql
SELECT count(*) FROM Log
WHERE cluster_name = 'Connector-EKS'
AND level = 'ERROR'
AND container_name LIKE '%autopatrol%'
SINCE 24 hours ago
FACET container_name
```

If count > 0, fetch the actual error messages:
```nrql
SELECT message, timestamp FROM Log
WHERE cluster_name = 'Connector-EKS'
AND level = 'ERROR'
AND container_name LIKE '%autopatrol%'
SINCE 24 hours ago LIMIT 10
```

## Output Format

Present results as a structured report:

```markdown
## AutoPatrol Health Check - [date] ([prod/staging])

### CronJob Status
| CronJob | Schedule | TZ | Last Run | Image | Status |
|---------|----------|----|----------|-------|--------|

### Patrol Execution (24h)
| Site | Patrols | Healthchecks | Detections | CNCTNFAIL | Status |
|------|---------|-------------|------------|-----------|--------|

### SQS Queue Flow
Messages/hour: [min]-[max] range, [any gaps noted]

### Autopatrol Server
- Errors: [count]
- Patrol outcomes: [Finished/Failed breakdown if available]

### Issues Found
- [list any problems, or "No issues found - all systems healthy"]
```

## Interpreting Results

- **Patrol counts**: 41158/41178 run every 30min (~48/day), others hourly (~24/day). Some runs may be outside active hours depending on schedule timezone windows.
- **CNCTNFAIL**: Connection failures are Immix-side (WebSocket stream issues), not our fault. Track trends — increasing CNCTNFAIL across runs is concerning.
- **Detections**: Sites with `production_vehicle` product (41178) actively produce detections. Sites with `production_car` (41158) currently filter all detections in post-processing — this is a known product config difference, not a pipeline failure.
- **Immix "Failed" status**: Immix may return `patrolStatus: "Failed"` even when our pipeline completes successfully. This is Immix-side classification, not an error on our end. Compare with our internal `patrol_status: 'completed'`.
- **Image mismatch**: `:stage` image on prod cronjobs means staging code running in production — should be fixed to `:latest`.
