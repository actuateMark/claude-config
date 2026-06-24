---
name: autopatrol-cleanup-lambda-check
description: Health check for the AutoPatrol stale-schedule cleanup Lambda — SQS, Lambda invocation, DLQ, DDB counters, disable rates. Distinct from /autopatrol-check (patrol pipeline). Trigger: 'cleanup lambda', 'cleanup health'.
user-invocable: true
allowed-tools:
  - Bash
  - Read
  - Grep
  - Glob
  - Agent
  - mcp__newrelic__execute_nrql_query
  - mcp__newrelic__list_recent_logs
---

# AutoPatrol Cleanup Lambda Health Check

Confirms the full chain: vms-connector emits → SQS → Lambda → DDB counters → threshold → Immix confirms → disable (when ENABLED).

**Runbook:** [[2026-04-20_cleanup-lambda-runbook]]. **Design:** [[2026-04-17_stale-schedule-cleanup-design]]. **Rollout history + 8b/8c/8d rationale:** [[2026-04-23_cleanup-rollout-day]].

## Environment config

| Env | Account | Region | Queue | Lambda | DDB |
|---|---|---|---|---|---|
| **stage** | `388576304176` | us-west-2 | `autopatrol_stale_schedule_cleanup_dev.fifo` | `immix-autopatrol-schedule-cleanup` | `autopatrol_cleanup_counters-dev` |
| prod (Step F, future) | same | us-west-2 | `autopatrol_stale_schedule_cleanup.fifo` | same Lambda | same/sibling |
| eu (Step G, future) | same | eu-west-1 | not yet | not yet | not yet |

Default to stage. Use `AWS_PROFILE=prod` for AWS CLI.

## Arguments

- *(none)*: stage check
- `prod` / `eu`: once those steps land
- A schedule UUID: focus on that schedule's counter

## Step 0 — Three-tier preamble

Per CLAUDE.md § "Routine Checks: Three-Tier Pattern". Walk tiers; stop at first success.

**Tier 0 — dashboard signals (preferred for routine status checks):**
The mechanical chain — DLQ depth, main-queue depth, Lambda errors, would-PATCH/actual-disable/anomaly-reset rates, and SQS event-source mapping state — is now collected hourly by `/dashboard-check`. Pull from the sink directly:
```bash
curl -fsS "http://mork-firebat/app/api/observations?signal_id=cleanup_lambda_event_source_mapping_state&limit=1"
curl -fsS "http://mork-firebat/app/api/observations?signal_id=cleanup_lambda_dlq_depth&limit=1"
# ... etc — see http://mork-firebat/dashboard/ for the autopatrol_cleanup component card
```
If you only need "is the cleanup pipeline healthy right now," check the `autopatrol_cleanup` component on the dashboard and stop. Use Tier 1+ only when you need DDB drift, retry-idempotency validation, or onboarder hotfix code-grep — the **interpretive** checks the dashboard doesn't cover.

**Tier 1 — Firebat cache:**
```bash
DIGEST=$(curl -fsS --max-time 5 "http://mork-firebat/logs/autopatrol-cleanup-lambda-check-$(date +%F).stdout")
SUMMARY=$(curl -fsS --max-time 5 "http://mork-firebat/logs/morning-prep-latest.summary.json")
```
Fresh (≤8h) + `exit_code == 0` → fold digest into output and exit.

**Tier 2 — local script:**
```bash
[ -x ~/bin/autopatrol-cleanup-check ] && exec ~/bin/autopatrol-cleanup-check "$@"
```
Source: `/home/mork/work/local_network_scripts/files/autopatrol-cleanup-check.sh`. Auth: `AWS_PROFILE=dashboard-check`, NR key at `~/.config/newrelic/key`, GitHub PAT.

**Tier 3 — LLM (this skill).** Run §§0-9 below. Diagnostic obligations:
- Script missing: `cp /home/mork/work/local_network_scripts/files/autopatrol-cleanup-check.sh ~/bin/autopatrol-cleanup-check && chmod 755`
- boto3 missing: `pip3 install --user --break-system-packages boto3`
- IAM `AccessDeniedException` on `lambda:ListEventSourceMappings` / `dynamodb:Scan` / etc. → surface ARN + Action gap to user (console fix)
- NR query timeout → tighten `WHERE` and shrink `SINCE` in the .sh
- Firebat unreachable → see [[firebat-minipc-access]]
- Patch the .sh inline if mechanical; log the diagnosis in today's daily note `## Notes / Learnings`.

---

## Checks (run in order; parallel where independent)

### 0. Onboarder Lambda liveness (CRITICAL)

If the onboarder silently bails, new schedules can't activate but nothing pages. **Always check first.**

```bash
for REGION in us-west-2 eu-west-1; do
  echo "=== $REGION onboarder — last 30m ==="
  AWS_PROFILE=prod aws logs tail /aws/lambda/immix-autopatrol-onboarding \
    --region $REGION --since 30m --format short 2>&1 | \
    grep -cE 'get_contracts|Fetched [0-9]+ contracts|get_sites|activating|deactivating' \
    | xargs -I{} echo "  worker activity: {}"
  echo "  early-exit 404 count:"
  AWS_PROFILE=prod aws logs tail /aws/lambda/immix-autopatrol-onboarding \
    --region $REGION --since 30m --format short 2>&1 | \
    grep -cE 'Failed to connect to (AutoPatrol|autopatrol) API.*404'
done
```

Healthy: worker activity > 10/window. 404s at WARNING level OK (post-2026-04-23 hotfix). Flag if activity ~0 with invocations continuing, or 404s at ERROR level (hotfix reverted — check `lambda_function.py:142`).

### 1. Event source mapping state

```bash
AWS_PROFILE=prod aws lambda list-event-source-mappings \
  --function-name immix-autopatrol-schedule-cleanup --region us-west-2 \
  --query 'EventSourceMappings[0].[State,StateTransitionReason,LastProcessingResult]' --output text
```

Healthy: `Enabled  USER_INITIATED  OK`. Flag `Disabled` or error in `LastProcessingResult`.

### 2. Queue depth (all four queues)

```bash
for Q in autopatrol_stale_schedule_cleanup_dev.fifo \
         autopatrol_stale_schedule_cleanup.fifo \
         autopatrol_stale_schedule_cleanup_dlq_dev.fifo \
         autopatrol_stale_schedule_cleanup_dlq.fifo; do
  DEPTH=$(AWS_PROFILE=prod aws sqs get-queue-attributes \
    --queue-url "https://sqs.us-west-2.amazonaws.com/388576304176/$Q" \
    --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible \
    --region us-west-2 --query Attributes --output text)
  echo "  $Q: $DEPTH"
done
```

Healthy: dev main 0–low (tens during bursts OK), prod main 0 until Step F, both DLQs always 0. Flag stage main >100 (lambda lagging), prod main >0 pre-rollout (early activation), any DLQ >0 (alarm + 3× failures).

### 3. Lambda invocation metrics (24h)

```bash
for METRIC in Invocations Errors Throttles Duration; do
  echo "=== $METRIC ==="
  AWS_PROFILE=prod aws cloudwatch get-metric-statistics \
    --namespace AWS/Lambda --metric-name $METRIC \
    --dimensions Name=FunctionName,Value=immix-autopatrol-schedule-cleanup \
    --start-time $(date -u -d '24 hours ago' +%Y-%m-%dT%H:%M:%S) \
    --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
    --period 3600 --statistics Sum,Average,Maximum --region us-west-2
done
```

Baseline (stage emitting): Invocations ~3500/day, Errors 0 (transient handled in code), Throttles 0 unless reserved concurrency 2 too low, Duration avg <1000ms.

### 4. Recent Lambda logs (1h tail + 24h grep)

```bash
AWS_PROFILE=prod aws logs tail /aws/lambda/immix-autopatrol-schedule-cleanup \
  --region us-west-2 --since 1h --format short | tail -40

LOGS=$(AWS_PROFILE=prod aws logs tail /aws/lambda/immix-autopatrol-schedule-cleanup \
  --region us-west-2 --since 24h --format short)
echo "Invocations:        $(echo "$LOGS" | grep -c 'cleanup_lambda invoked')"
echo "Messages processed: $(echo "$LOGS" | grep -c 'processing schedule_id=')"
echo "Threshold hits:     $(echo "$LOGS" | grep -c 'would PATCH\|disabled admin')"
echo "Would-disables:     $(echo "$LOGS" | grep -c 'would PATCH')"
echo "Actual disables:    $(echo "$LOGS" | grep -c '^disabled admin')"
echo "Anomaly resets:     $(echo "$LOGS" | grep -c 'anomaly: bucket=')"
echo "Transient errors:   $(echo "$LOGS" | grep -c 'transient error for msg')"
echo "ERROR lines:        $(echo "$LOGS" | grep -c ERROR)"
```

Flag: actual disables while `CLEANUP_ENABLED=false`; transient >5%; any ERROR.

### 5. Lambda env / config sanity

```bash
AWS_PROFILE=prod aws lambda get-function-configuration \
  --function-name immix-autopatrol-schedule-cleanup --region us-west-2 \
  --query 'Environment.Variables' --output json
```

Expected: `CLEANUP_ENABLED=true` (flipped 2026-04-23T17:59Z), `DRY_RUN` not `"true"` in prod, `CLEANUP_TARGET_HOURS=18` (lowered from 48 at 2026-04-23T18:12Z), `CLEANUP_SITE_DISABLED_TARGET_HOURS=336`, `DDB_COUNTERS_TABLE=autopatrol_cleanup_counters-dev`, `AUTOPATROL_STAGE=prod`, `AUTOPATROL_REGION=US`.

### 6. DDB counter state

```bash
# Total rows
AWS_PROFILE=prod aws dynamodb scan \
  --table-name autopatrol_cleanup_counters-dev --region us-west-2 \
  --select COUNT

# Top 25
AWS_PROFILE=prod aws dynamodb scan \
  --table-name autopatrol_cleanup_counters-dev --region us-west-2 \
  --projection-expression "schedule_id, admin_pk, #c, #t, last_failure_at" \
  --expression-attribute-names '{"#c":"count","#t":"threshold"}' \
  --max-items 25
```

Healthy: rows exist, counts mostly 1-5, a few near threshold. Flag: zero rows after >1h of stage emits (pipeline broken); count >> threshold (Lambda not acting); same `schedule_id` repeating with reset (Immix anomaly bouncing). Known pre-ENABLED leftover rows: `c3808175`, `fbdfdba6`, `ee1822f1` cleared at 2026-04-23T18:16Z when target was lowered 48→18.

### 7. Correlation: connector emits vs Lambda invocations (NRQL)

```nrql
SELECT count(*) FROM Log
WHERE cluster_name = 'Connector-EKS' AND message LIKE '%emit_no_patrols_signal%'
SINCE 24 hours ago
```

Compare to §3 Invocations. Should be ~equal (small delta from FIFO dedup). Large gap = messages lost.

### 8. NR custom events (once layer attached)

```nrql
SELECT count(*) FROM AutoPatrolScheduleDisabled FACET bucket, reason, dry_run SINCE 24 hours ago
SELECT count(*) FROM AutoPatrolScheduleDisabled FACET schedule_id SINCE 7 days ago LIMIT 20
SELECT count(*) FROM AutoPatrolScheduleReenabled FACET user_email SINCE 7 days ago
```

Until layer attached: no data, fall back to §4.

### 8b. Retry-idempotency fix validation (PR #5, 2026-04-23T16:33Z)

```bash
LOGS=$(AWS_PROFILE=prod aws logs tail /aws/lambda/immix-autopatrol-schedule-cleanup \
  --region us-west-2 --since 24h --format short 2>&1)

# (1) Retry-dedup hits — proves ConditionExpression fired
echo "retry-dedup hits: $(echo "$LOGS" | grep -c 'retry of message_id=.*skipping increment')"

# (2) DDB rows with last_message_id (post-fix rows; --select COUNT can't combine with --projection-expression)
AWS_PROFILE=prod aws dynamodb scan \
  --table-name autopatrol_cleanup_counters-dev --region us-west-2 \
  --filter-expression "attribute_exists(last_message_id)" \
  --select COUNT --query 'Count' --output text

# (3) Counter drift — count > threshold * 2 = retry-overcount regression
AWS_PROFILE=prod aws dynamodb scan \
  --table-name autopatrol_cleanup_counters-dev --region us-west-2 \
  --projection-expression "schedule_id, #c, #t" \
  --expression-attribute-names '{"#c":"count","#t":"threshold"}' \
  --output json 2>&1 | python3 -c "
import json, sys
for item in json.load(sys.stdin).get('Items', []):
    c = int(item.get('count',{}).get('N',0) or 0)
    t = int(item.get('threshold',{}).get('N',0) or 0)
    if t > 0 and c > t*2:
        print(f\"DRIFT: {item['schedule_id']['S'][:12]}... count={c}/{t}\")
"
```

Expected: (1) >0 if any transient errors; (2) grows from 0; (3) no output. Drift = regression.

### 8c. Onboarder healthcheck hotfix (PR #4, 2026-04-23) still in effect

```bash
cd /home/mork/work/autopatrol_onboarder
grep -A2 'autopatroller.get_healthcheck' lambda_function.py
```

Block must `logging.warning(...)` with NO `return` after. Any `return` = hotfix reverted, 2026-04-23 incident can recur.

### 8d. Deploy workflow integrity (skip if no deploys since yesterday)

```bash
cd /home/mork/work/autopatrol_onboarder
RUN_ID=$(gh run list --workflow deploy.yml --limit 1 --json databaseId --jq '.[0].databaseId')
JOB=$(gh run view "$RUN_ID" --json jobs --jq '.jobs[0].databaseId')
gh run view --job $JOB --log 2>&1 | grep -cE 'AccessDeniedException|ServiceException' \
  | xargs -I{} echo "real errors: {} (expected: 0)"
gh run view --job $JOB --log 2>&1 | grep -cE 'CODEARTIFACT_AUTH_TOKEN=eyJ' \
  | xargs -I{} echo "plaintext token leaks: {} (expected: 0)"
```

### 9. DLQ peek (only if DLQ >0)

```bash
AWS_PROFILE=prod aws sqs receive-message \
  --queue-url https://sqs.us-west-2.amazonaws.com/388576304176/autopatrol_stale_schedule_cleanup_dlq_dev.fifo \
  --visibility-timeout 0 --max-number-of-messages 5 \
  --attribute-names All --region us-west-2
```

Inspect `Body` + `Attributes.ApproximateReceiveCount`.

## Output format

```markdown
## AutoPatrol Cleanup Lambda Health Check — <date> (<env>)

### Pipeline state
- Event source mapping: <Enabled|Disabled> <reason>
- Main queue: N msgs (visible + in-flight)
- DLQ: N ← **must be 0**
- Lambda concurrency: <N reserved> / <M provisioned>
- CLEANUP_ENABLED: <true|false>

### 24h metrics
| Metric | Value | Expected |
|---|---|---|
| Invocations | N | ~3500/day at fleet peak |
| Errors | N | 0 |
| Throttles | N | 0 |
| Duration avg | N ms | <1000 |
| Messages processed | N | matches invocations |
| Would-disables | N | varies (CLEANUP_ENABLED=false) |
| Actual disables | N | 0 if dark, expected if ENABLED |
| Anomaly resets | N | low |
| Transient errors | N | <5% |

### Connector ↔ Lambda correlation
- Connector emit lines: N | Lambda invocations: M | Gap: N-M (expect ~0)

### DDB state
- Total counter rows: N | At threshold: N | site_disabled bucket: N | Oldest last_failure_at: <ts>

### Issues found
- [list, or "No issues found"]
```

## Interpreting results

- **DLQ messages = non-negotiable bar.** Any = processing bug or upstream unrecoverable.
- **Would-disables while `CLEANUP_ENABLED=false`** = intended dark-mode. Sanity-check against Immix state.
- **Patrol_exit vs site_disabled mix** — patrol_exit ~3500/day baseline, site_disabled rare (Paused/Suspended/Removed/Deleted from `get_patrol_stream`). Climbing site_disabled deserves a look.
- **Anomaly resets** — schedule hit threshold but Immix says active, so we did NOT disable. Baseline 0-5/day. Spike = classifier bug or Immix outage. Repeat offenders (any `schedule_id` 2+ times in 7d):
  ```bash
  AWS_PROFILE=prod aws logs filter-log-events \
    --log-group-name /aws/lambda/immix-autopatrol-schedule-cleanup --region us-west-2 \
    --start-time $(( $(date -u +%s) * 1000 - 7*86400*1000 )) \
    --filter-pattern 'anomaly: bucket=' \
    --query 'events[].message' --output text | \
    grep -oE 'schedule [a-f0-9-]+' | sort | uniq -c | sort -rn | head -10
  ```
- **Transient errors** — admin/Immix 5xx normal at low rate. Spike = upstream incident.

## Related

- [[2026-04-20_cleanup-lambda-runbook]] — full command reference
- [[2026-04-17_stale-schedule-cleanup-design]] — architecture
- [[autopatrol-cleanup-lambda]] — entity
- [[skill-autopatrol-overnight-check|/autopatrol-check]] — sibling (patrol pipeline)
- [[2026-04-20_overnight-check-skill-pattern]] — meta-process
