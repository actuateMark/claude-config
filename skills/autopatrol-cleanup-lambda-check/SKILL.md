---
name: autopatrol-cleanup-lambda-check
description: Health check for the AutoPatrol stale-schedule cleanup Lambda pipeline. Use when the user asks "check cleanup lambda", "cleanup health", "overnight cleanup check", "how's the cleanup lambda doing", "check the stale-schedule pipeline", or similar. Covers SQS queue flow, Lambda invocation metrics, DLQ state, DDB counter accumulation, and would-disable / actual-disable rates. Distinct from /autopatrol-check which covers the patrol pipeline itself.
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

Run a comprehensive nightly/on-demand check on the AutoPatrol stale-schedule cleanup Lambda pipeline. Confirms the full chain is working: vms-connector emits → SQS delivers → Lambda consumes → DDB counters increment → threshold hits → Immix confirms → disable path fires (when ENABLED).

**Runbook**: [[2026-04-20_cleanup-lambda-runbook]] for command references.
**Design**: [[2026-04-17_stale-schedule-cleanup-design]].

## Environment config

| Environment | Account | Region | Queue | Lambda | DDB Table |
|---|---|---|---|---|---|
| **stage (current)** | `388576304176` (prod) | us-west-2 | `autopatrol_stale_schedule_cleanup_dev.fifo` | `immix-autopatrol-schedule-cleanup` | `autopatrol_cleanup_counters-dev` |
| **prod (future, Step F)** | `388576304176` | us-west-2 | `autopatrol_stale_schedule_cleanup.fifo` (not yet created) | same Lambda, different env | same table or sibling |
| **eu (future, Step G)** | `388576304176` | eu-west-1 | not yet created | not yet created | not yet created |

Default to stage unless the user specifies otherwise. Use `AWS_PROFILE=prod` for all AWS CLI commands.

## Arguments

- No args: stage check (default)
- `prod`: once Step F lands, check prod-tier resources
- `eu`: once Step G lands, check EU resources
- A specific schedule_id (UUID): focus on that one schedule's counter state

## Checks (run in order; parallel where independent)

### 0. Onboarder Lambda liveness (CRITICAL — added after 2026-04-23 incident)

The onboarder Lambda (`immix-autopatrol-onboarding`, US + EU) is a sibling that runs every 5 min and is what actually onboards new schedules. If it silently bails (as it did for ~2 days in April 2026 when a broken healthcheck gate shipped), users can't activate new schedules — but nothing errors, nothing pages. **Always check it first.**

```bash
# Both regions in parallel — both should show get_contracts-level activity, not just early exits
for REGION in us-west-2 eu-west-1; do
  echo "=== $REGION onboarder — last 30m of log activity ==="
  AWS_PROFILE=prod aws logs tail /aws/lambda/immix-autopatrol-onboarding \
    --region $REGION --since 30m --format short 2>&1 | \
    grep -cE 'get_contracts|Fetched [0-9]+ contracts|get_sites|activating|deactivating' \
    | xargs -I{} echo "  worker activity lines: {}"
  echo "  early-exit 404 count:"
  AWS_PROFILE=prod aws logs tail /aws/lambda/immix-autopatrol-onboarding \
    --region $REGION --since 30m --format short 2>&1 | \
    grep -cE 'Failed to connect to (AutoPatrol|autopatrol) API.*404'
done
```

**Healthy:** worker-activity lines > 10 per invocation window (the flow is actually running). 404 warnings from the healthcheck log are OK post-2026-04-23 — the hotfix downgraded those to warnings and the flow continues past them.

**Flag if:**
- Worker activity lines near 0 while invocations continue — Lambda is running but bailing early. Repro of the April 2026 incident pattern.
- 404 lines at ERROR (not WARNING) level — someone reverted the hotfix. Check `lambda_function.py:142` — the healthcheck block should `logging.warning(...)` without an early `return`.

### 1. Event source mapping state

```bash
AWS_PROFILE=prod aws lambda list-event-source-mappings \
  --function-name immix-autopatrol-schedule-cleanup --region us-west-2 \
  --query 'EventSourceMappings[0].[State,StateTransitionReason,LastProcessingResult]' --output text
```

Healthy: `Enabled  USER_INITIATED  OK` (or no `LastProcessingResult`).
Flag if `State=Disabled` or `LastProcessingResult` mentions errors.

### 2. Queue depth (survey all four queues)

The cleanup Lambda consumes from both stage and prod queues. Both sides need their DLQ checked independently.

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

**Healthy:**
- `_dev.fifo` (stage main): 0–low. Lambda drains fast. Tens during bursts is OK.
- `autopatrol_stale_schedule_cleanup.fifo` (prod main): **0 until prod pods opt in**. Any messages here before prod rollout = someone flipped a feature flag early.
- Both DLQs: always 0. Any DLQ message = alarm fires + Lambda processing failed 3 times.

**Flag if:**
- Stage main >100 — Lambda is falling behind
- Prod main >0 without a corresponding rollout decision — early activation
- Either DLQ >0 — check Lambda error logs

### 3. Lambda invocation metrics (last 24h)

```bash
AWS_PROFILE=prod aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Invocations \
  --dimensions Name=FunctionName,Value=immix-autopatrol-schedule-cleanup \
  --start-time $(date -u -d '24 hours ago' +%Y-%m-%dT%H:%M:%S) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
  --period 3600 --statistics Sum --region us-west-2
```

Also check `Errors`, `Throttles`, `Duration`:

```bash
for METRIC in Errors Throttles Duration; do
  echo "=== $METRIC ==="
  AWS_PROFILE=prod aws cloudwatch get-metric-statistics \
    --namespace AWS/Lambda \
    --metric-name $METRIC \
    --dimensions Name=FunctionName,Value=immix-autopatrol-schedule-cleanup \
    --start-time $(date -u -d '24 hours ago' +%Y-%m-%dT%H:%M:%S) \
    --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
    --period 3600 --statistics Sum,Average,Maximum --region us-west-2
done
```

**Expected baseline (once stage emits):**
- Invocations: ~1/sec at peak, ~3500/day total per the NR fleet baseline
- Errors: 0 (transient admin/Immix errors are handled in code with `_TransientError` + SQS retry)
- Throttles: 0 unless the reserved concurrency (2) is too low
- Duration avg: <1000ms per invocation

### 4. Recent Lambda logs (last 1h)

Tail the log group for recent activity:

```bash
AWS_PROFILE=prod aws logs tail /aws/lambda/immix-autopatrol-schedule-cleanup \
  --region us-west-2 --since 1h --format short | tail -40
```

Key patterns to grep + count:

```bash
LOGS=$(AWS_PROFILE=prod aws logs tail /aws/lambda/immix-autopatrol-schedule-cleanup \
  --region us-west-2 --since 24h --format short)

echo "Invocations (24h):  $(echo "$LOGS" | grep -c 'cleanup_lambda invoked')"
echo "Messages processed: $(echo "$LOGS" | grep -c 'processing schedule_id=')"
echo "Threshold hits:     $(echo "$LOGS" | grep -c 'would PATCH\|disabled admin')"
echo "Would-disables:     $(echo "$LOGS" | grep -c 'would PATCH')"
echo "Actual disables:    $(echo "$LOGS" | grep -c '^disabled admin')"
echo "Anomaly resets:     $(echo "$LOGS" | grep -c 'anomaly: bucket=')"
echo "Transient errors:   $(echo "$LOGS" | grep -c 'transient error for msg')"
echo "ERROR lines:        $(echo "$LOGS" | grep -c ERROR)"
```

**Flag if:**
- Actual disables occurring while `CLEANUP_ENABLED=false` — bug somewhere
- Transient errors > ~5% of invocations — upstream (admin/Immix) flaking
- ERROR lines > 0 — investigate each

### 5. Lambda env / config sanity

```bash
AWS_PROFILE=prod aws lambda get-function-configuration \
  --function-name immix-autopatrol-schedule-cleanup --region us-west-2 \
  --query 'Environment.Variables' --output json
```

Check:
- `CLEANUP_ENABLED` — `"false"` during bake, `"true"` once flipped (flipped 2026-04-23T17:59Z)
- `DRY_RUN` — should NOT be `"true"` in prod (dev smoke-tests only)
- `CLEANUP_TARGET_HOURS` — **`18`** (lowered from 48 at 2026-04-23T18:12Z; see [[2026-04-23_cleanup-rollout-day]]). For 6h-cadence schedules this drops threshold to the floor of 3.
- `CLEANUP_SITE_DISABLED_TARGET_HOURS` — 336 (site_disabled)
- `DDB_COUNTERS_TABLE` — `autopatrol_cleanup_counters-dev`
- `AUTOPATROL_STAGE` — `prod`
- `AUTOPATROL_REGION` — `US`

### 6. DDB counter state

```bash
# Total rows
AWS_PROFILE=prod aws dynamodb scan \
  --table-name autopatrol_cleanup_counters-dev --region us-west-2 \
  --select COUNT

# Top N schedules by count (patrol_exit bucket)
AWS_PROFILE=prod aws dynamodb scan \
  --table-name autopatrol_cleanup_counters-dev --region us-west-2 \
  --projection-expression "schedule_id, admin_pk, #c, #t, last_failure_at" \
  --expression-attribute-names '{"#c":"count","#t":"threshold"}' \
  --max-items 25
```

**Healthy patterns:**
- Rows exist (stage is emitting + Lambda is processing)
- Counts mostly low (1–5) for active schedules that occasionally blip
- A few schedules approach threshold — those are legitimate cleanup candidates

**Flag if:**
- Zero rows after stage has been emitting >1h → pipeline broken somewhere
- Rows with `count` way over `threshold` → Lambda should have acted (check ENABLED state)
- Same `schedule_id` appearing repeatedly with a reset pattern → Immix anomaly (keeps bouncing active ↔ paused)

**Known post-18:16 state (not a bug):** rows `c3808175`, `fbdfdba6`, `ee1822f1` have no `threshold` attribute — deliberately cleared 2026-04-23T18:16Z when target was lowered 48→18 so the next emit picks up the new computed threshold. They're stuck at `count=3,3,4` from pre-ENABLED accumulation. Next 6h-cadence emit for each should trigger the Immix check + disable path (or anomaly-reset). Verify by watching for these IDs in subsequent runs — they should either disappear (disabled) or reset to 0 (anomaly). See [[2026-04-23_cleanup-rollout-day]] §Timeline.

### 7. Correlation: connector emits vs Lambda invocations

Via New Relic (account 3421145):

```nrql
-- Connector emits (24h) — what the connector SHOULD have sent
SELECT count(*) FROM Log
WHERE cluster_name = 'Connector-EKS'
AND message LIKE '%emit_no_patrols_signal%'
SINCE 24 hours ago
```

Compare against Lambda invocation count from §3. They should be ~equal (minor delta from FIFO dedup or timing). Large gap = messages lost between connector and Lambda.

### 8. NR custom events (once layer attached — track Not-Yet-Prioritized)

```nrql
-- Disable decisions, 24h, by bucket + reason + dry_run state
SELECT count(*) FROM AutoPatrolScheduleDisabled
FACET bucket, reason, dry_run SINCE 24 hours ago

-- Schedules hitting threshold repeatedly (flappy)
SELECT count(*) FROM AutoPatrolScheduleDisabled
FACET schedule_id SINCE 7 days ago LIMIT 20

-- Re-enables
SELECT count(*) FROM AutoPatrolScheduleReenabled
FACET user_email SINCE 7 days ago
```

Until the NR Lambda layer is attached, these return no data — fall back to §4 CloudWatch log parsing.

### 8b. Post-fix validation (added 2026-04-23 — watch list for the retry-idempotency fix)

The 2026-04-23 retry-idempotency fix (PR #5, deployed 16:33Z) adds `last_message_id` tracking + a DDB ConditionExpression guard. Until it's been exercised organically, we can't confirm it works in prod. These queries surface the evidence.

```bash
LOGS=$(AWS_PROFILE=prod aws logs tail /aws/lambda/immix-autopatrol-schedule-cleanup \
  --region us-west-2 --since 24h --format short 2>&1)

# 1. Retry-dedup log lines — proof the ConditionExpression fired
echo "retry-dedup hits (24h): $(echo "$LOGS" | grep -c 'retry of message_id=.*skipping increment')"
```

**Expected:** >0 if any transient errors occurred during the day. 0 means no organic exercise happened yet; fix remains unit-tested-only.

```bash
# 2. DDB rows with last_message_id populated (post-fix rows)
# Note: --select COUNT cannot be combined with --projection-expression (AWS CLI validation).
AWS_PROFILE=prod aws dynamodb scan \
  --table-name autopatrol_cleanup_counters-dev --region us-west-2 \
  --filter-expression "attribute_exists(last_message_id)" \
  --select COUNT --query 'Count' --output text
```

**Expected:** grows from 0 at deploy time as new messages hit. If it stays at 0 after >1h of traffic, the fix may not be running (check Lambda `LastModified` and `CodeSha256`).

```bash
# 3. Counter drift detection — any row where count > threshold * 2 is a retry-overcount warning sign
AWS_PROFILE=prod aws dynamodb scan \
  --table-name autopatrol_cleanup_counters-dev --region us-west-2 \
  --projection-expression "schedule_id, #c, #t" \
  --expression-attribute-names '{"#c":"count","#t":"threshold"}' \
  --output json 2>&1 | python3 -c "
import json, sys
d = json.load(sys.stdin)
for item in d.get('Items', []):
    c = int(item.get('count', {}).get('N', 0) or 0)
    t = int(item.get('threshold', {}).get('N', 0) or 0)
    if t > 0 and c > t * 2:
        sid = item['schedule_id']['S'][:12]
        print(f'DRIFT: {sid}... count={c}/{t} (ratio {c/t:.1f}x)')
"
```

**Expected:** no output. Post-fix, counters can't meaningfully exceed threshold — the Lambda acts at threshold OR anomaly-resets. Drift = bug regression.

### 8c. Onboarder healthcheck hotfix validation (added 2026-04-23)

Confirm the 2026-04-23 healthcheck hotfix (PR #4, downgrade-to-warning) is still in effect. Someone reverting would silently break onboarder again.

```bash
cd /home/mork/work/autopatrol_onboarder
grep -A2 'autopatroller.get_healthcheck' lambda_function.py
```

**Expected:** block should `logging.warning(...)` and NOT have `return` on the next line. If it has a `return`, the hotfix has been reverted — the 2026-04-23 incident could recur.

### 8d. Deploy workflow integrity (added 2026-04-23)

After any merge to master, confirm all 6 deploy steps succeeded (no silent AccessDenied). Skip this if no deploys have happened since yesterday.

```bash
cd /home/mork/work/autopatrol_onboarder
RUN_ID=$(gh run list --workflow deploy.yml --limit 1 --json databaseId --jq '.[0].databaseId')
gh run view --job $(gh run view "$RUN_ID" --json jobs --jq '.jobs[0].databaseId') --log 2>&1 \
  | grep -cE 'AccessDeniedException|ServiceException' \
  | xargs -I{} echo "real-error lines in last deploy: {} (expected: 0)"
gh run view --job $(gh run view "$RUN_ID" --json jobs --jq '.jobs[0].databaseId') --log 2>&1 \
  | grep -cE 'CODEARTIFACT_AUTH_TOKEN=eyJ' \
  | xargs -I{} echo "plaintext CodeArtifact token leaks: {} (expected: 0)"
```

**Expected:** both counts 0. Any >0 means a workflow or IAM policy regressed.

### 9. DLQ peek (only if DLQ >0 from §2)

```bash
AWS_PROFILE=prod aws sqs receive-message \
  --queue-url https://sqs.us-west-2.amazonaws.com/388576304176/autopatrol_stale_schedule_cleanup_dlq_dev.fifo \
  --visibility-timeout 0 --max-number-of-messages 5 \
  --attribute-names All --region us-west-2
```

Inspect the `Body` + `Attributes.ApproximateReceiveCount` to understand what failed.

## Output format

```markdown
## AutoPatrol Cleanup Lambda Health Check — <date> (<env>)

### Pipeline state
- Event source mapping: <Enabled|Disabled> <reason>
- Main queue: N messages (visible + in-flight)
- DLQ: N messages ← **must be 0**
- Lambda concurrency: <N reserved> / <M provisioned>
- CLEANUP_ENABLED: <true|false>

### 24h metrics
| Metric | Value | Expected |
|---|---|---|
| Invocations | N | ~3500/day at fleet peak |
| Errors | N | 0 |
| Throttles | N | 0 |
| Duration avg | N ms | <1000 |
| Messages processed (from logs) | N | matches invocations |
| Would-disables (CLEANUP_ENABLED=false) | N | varies by bucket; expect site_disabled rare, patrol_exit steady |
| Actual disables | N | 0 if dark, expected if ENABLED |
| Anomaly resets | N | low |
| Transient errors | N | <5% of invocations |

### Connector ↔ Lambda correlation
- Connector `emit_no_patrols_signal` log lines (24h): N
- Lambda invocations (24h): M
- Gap: N-M = X (expected: ~0, FIFO dedup may slim it)

### DDB state
- Total counter rows: N
- Schedules at threshold (count ≥ threshold): N
- Schedules with site_disabled bucket populated: N
- Oldest `last_failure_at`: <timestamp>

### Issues found
- [list anything concerning, or "No issues found — pipeline healthy"]
```

## Interpreting results

- **Zero DLQ messages** is the non-negotiable bar. Any DLQ message = processing bug or upstream (admin/Immix) unrecoverable error.
- **Would-disables while CLEANUP_ENABLED=false** is the INTENDED dark-mode state. Count them, sanity-check against the site's state in Immix — they're what would fire once we flip the switch.
- **Patrol_exit vs site_disabled mix** — patrol_exit signals are ~3500/day fleet baseline (per NR). site_disabled is rarer (only when Immix reports Paused/Suspended/Removed/Deleted on `get_patrol_stream`). A site_disabled count climbing is a signal worth a closer look.
- **Anomaly resets** — "schedule hit threshold but Immix says active, so we did NOT disable" — should be rare. This is the safety-net firing. Elevated rate ⇒ ongoing Immix-side mismatch or classifier drift. Two dimensions worth tracking:
  - **Total rate** (count/h): spike = new classifier bug OR Immix outage. Baseline ~0-5/day.
  - **Repeat offenders over 7 days**: any schedule_id appearing 2+ times is a specific flappy schedule / state-mismatch candidate. Example command:
    ```bash
    AWS_PROFILE=prod aws logs filter-log-events \
      --log-group-name /aws/lambda/immix-autopatrol-schedule-cleanup \
      --region us-west-2 \
      --start-time $(( $(date -u +%s) * 1000 - 7*86400*1000 )) \
      --filter-pattern 'anomaly: bucket=' \
      --query 'events[].message' --output text | \
      grep -oE 'schedule [a-f0-9-]+' | sort | uniq -c | sort -rn | head -10
    ```
    Returns counts per schedule_id; any `count >= 2` is a candidate for Immix-side investigation.
- **Transient errors** — admin API 5xx or Immix API 5xx — normal at low rate. Spike = upstream incident.

## Related

- [[2026-04-20_cleanup-lambda-runbook]] — the full command reference this skill pulls from
- [[2026-04-17_stale-schedule-cleanup-design]] — architecture
- [[autopatrol-cleanup-lambda]] — entity
- [[skill-autopatrol-overnight-check|/autopatrol-check]] — sibling skill for the patrol pipeline (not this Lambda)
- [[2026-04-20_overnight-check-skill-pattern]] — meta-process for creating these skills per project/repo
