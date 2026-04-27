---
name: cost-check
description: AWS Cost Explorer query skill. Runs CE queries via the `prod` AWS profile (account 388576304176) with NR-style discipline — aggregate first, summarize, never dump raw rows. Use directly for ad-hoc cost queries or invoke as a sub-skill from other skills to surface cost-side signals alongside operational health. Trigger on "cost check", "run cost query", "aws cost", "cost explorer", "/cost-check".
user-invocable: true
allowed-tools:
  - Bash
  - Read
---

# /cost-check — AWS Cost Explorer Query Skill

Proven 2026-04-22 during the frame-storage design-delta validation. First-class tool alongside NR + CloudWatch for cost-side investigation.

## Two invocation modes

### 1. Direct mode (user-invoked)

User runs `/cost-check` with positional / flag arguments:

```
/cost-check                                   # default: 30-day service-level summary
/cost-check S3                                # 30-day S3 USAGE_TYPE breakdown
/cost-check S3 --days 7                       # 7-day S3 breakdown
/cost-check S3 --days 7 --granularity DAILY   # 7-day S3 daily trend
/cost-check DynamoDB --days 30                # 30-day DynamoDB breakdown
/cost-check --service "Amazon EC2-Instance"   # 30-day EC2 breakdown (quoted for multi-word services)
/cost-check --top-services --days 30          # 30-day top-10 services by cost
```

Output: markdown tables with cost + quantity + % of total, flagging anything >1.5× yesterday's equivalent day or >2× the prior-period average.

### 2. Sub-skill mode (invoked by other skills)

Other skills call `/cost-check` programmatically by running the `run_query` bash pattern (see §"Sub-skill API" below) and parsing the JSON output. Example callers:

- `/autopatrol-cleanup-lambda-check` — get 7-day DynamoDB + SQS + Lambda invocation cost trend for the cleanup pipeline resources
- `/daily-scope` morning fan-out — weekly cost-drift exec item (any service > 2× week-over-week)
- `/overnight-logs` — if overnight logs reveal a spike, correlate with overnight cost delta
- Fleet-architecture investigations — ad-hoc S3/EC2/Redis pulls grounding cost claims

The skill responds in JSON when `--format=json` is passed.

## Arguments

| Arg | Type | Default | Purpose |
|-----|------|---------|---------|
| (positional) `<SERVICE>` | string | — | Service name. Accepts short aliases: `S3`, `DynamoDB`, `Lambda`, `EC2`, `RDS`, `SQS`, `CloudWatch`, `Secrets Manager`. Maps to canonical CE service names internally. Omit for cross-service summary. |
| `--service <name>` | string | — | Alternative to positional when service name has spaces / special chars |
| `--days <N>` | integer | 30 | Time window (ending today). 7 / 30 / 90 are typical. |
| `--granularity <G>` | enum | `MONTHLY` (if days ≥ 30) else `DAILY` | `DAILY` / `MONTHLY` / `HOURLY`. `HOURLY` only for <3-day windows. |
| `--group-by <G>` | enum | `USAGE_TYPE` (if service set) else `SERVICE` | `SERVICE` / `USAGE_TYPE` / `LINKED_ACCOUNT` / `REGION` / `INSTANCE_TYPE` |
| `--filter-key <K> --filter-values <v1,v2>` | key + comma list | — | Custom filter. E.g., `--filter-key REGION --filter-values us-west-2` |
| `--top-services` | flag | false | Shorthand: cross-service group-by, cost-sorted, top 10. |
| `--format <f>` | enum | `markdown` | `markdown` (default human-readable) / `json` (for sub-skill consumers) / `raw` (pass-through CE JSON) |
| `--compare-to-prior` | flag | false | Include a "prior equivalent window" column to spot changes |

## Service name aliases (internal mapping)

| Alias | Canonical CE SERVICE value |
|-------|---------------------------|
| `S3` | `Amazon Simple Storage Service` |
| `DynamoDB` or `DDB` | `Amazon DynamoDB` |
| `Lambda` | `AWS Lambda` |
| `EC2` | `Amazon Elastic Compute Cloud - Compute` |
| `EBS` | `Amazon Elastic Block Store` |
| `RDS` | `Amazon Relational Database Service` |
| `SQS` | `Amazon Simple Queue Service` |
| `SNS` | `Amazon Simple Notification Service` |
| `CloudWatch` or `CW` | `AmazonCloudWatch` |
| `Secrets Manager` | `AWS Secrets Manager` |
| `EKS` | `Amazon Elastic Container Service for Kubernetes` |
| `CloudTrail` | `AWS CloudTrail` |
| `CodeArtifact` | `AWS CodeArtifact` |

If a user-provided alias doesn't match, pass through to CE as-is (CE will reject unknown values with a clear error).

## Procedure

### Step 0 — Preflight

1. Verify `AWS_PROFILE=prod aws sts get-caller-identity` returns a valid identity. If SSO token is expired, stop and tell the user to run `aws sso login --profile prod`.
2. Verify `ce:GetCostAndUsage` permission is present (run a tiny 1-day query with `--max-items 1` and check for `AccessDenied`).

### Step 1 — Parse args + resolve service alias

Resolve positional service arg against the alias table above. Default `--days 30`, `--granularity MONTHLY` for 30+ days / `DAILY` otherwise. Default `--group-by USAGE_TYPE` if a service is set, else `SERVICE`.

### Step 2 — Build the CE invocation

Canonical pattern (direct mode, S3 example):

```bash
START=$(date -d "30 days ago" +%Y-%m-%d)
END=$(date +%Y-%m-%d)
AWS_PROFILE=prod aws ce get-cost-and-usage \
  --time-period "Start=${START},End=${END}" \
  --granularity MONTHLY \
  --metrics "UnblendedCost" "UsageQuantity" \
  --filter '{"Dimensions":{"Key":"SERVICE","Values":["Amazon Simple Storage Service"]}}' \
  --group-by "Type=DIMENSION,Key=USAGE_TYPE" \
  --no-cli-pager > /tmp/ce_$$.json
```

Write raw output to `/tmp/ce_$$.json` (PID-suffixed to avoid collisions across parallel runs).

### Step 3 — Post-process

Use inline Python — CE JSON is deeply nested and needs flattening before summary. Reference recipe:

```bash
python3 <<'EOF'
import json, collections, sys, os
data = json.load(open(os.environ['CE_FILE']))
categories = collections.defaultdict(lambda: {'cost': 0.0, 'quantity': 0.0, 'unit': '', 'types': []})

def classify(ut):
    # S3-specific classification; extend for other services
    if 'Tier1' in ut: return 'PUT/COPY/POST/LIST (Tier1)'
    if 'Tier2' in ut: return 'GET/SELECT (Tier2)'
    if 'Tier3' in ut: return 'Replication/Lifecycle (Tier3)'
    if 'Tier8' in ut or 'Tier9' in ut: return 'Glacier retrieval (Tier8/9)'
    if 'TimedStorage' in ut or ('Storage' in ut and 'Requests' not in ut): return 'Storage (GB-month)'
    if 'DataTransfer' in ut or 'CloudFront-Out' in ut or 'AWS-Out-Bytes' in ut or 'AWS-In-Bytes' in ut: return 'Data transfer'
    if 'EarlyDelete' in ut: return 'Early-delete fees'
    if 'Retrieval' in ut: return 'Retrieval fees'
    return f'Other: {ut}'

for bucket in data['ResultsByTime']:
    for g in bucket.get('Groups', []):
        ut = g['Keys'][0]
        cost = float(g['Metrics']['UnblendedCost']['Amount'])
        qty = float(g['Metrics']['UsageQuantity']['Amount'])
        unit = g['Metrics']['UsageQuantity']['Unit']
        c = classify(ut)
        categories[c]['cost'] += cost
        categories[c]['quantity'] += qty
        categories[c]['unit'] = unit

total = sum(v['cost'] for v in categories.values())
rows = sorted(categories.items(), key=lambda kv: -kv[1]['cost'])

# Human output
print(f"\n{'Category':42s} {'Cost (USD)':>12s} {'Quantity':>22s} {'% total':>8s}")
print('-' * 90)
for cat, v in rows:
    if v['cost'] < 0.01 and total > 10: continue  # suppress rounding-error noise
    q_str = f"{v['quantity']:>15,.2f} {v['unit'][:10]}"
    pct = 100 * v['cost'] / total if total else 0
    print(f"{cat:42s} ${v['cost']:>10,.2f}   {q_str}  {pct:>5.1f}%")
print('-' * 90)
print(f"{'TOTAL':42s} ${total:>10,.2f}")
EOF
```

For other services, extend the `classify()` function. Common categories per service:

**DynamoDB:** Read/Write capacity (on-demand vs provisioned), storage GB-month, streams, backup, PITR, DAX nodes.
**Lambda:** invocations, GB-seconds (compute), provisioned concurrency, data transfer.
**EC2:** BoxUsage by instance class, EBS (broken out), NAT, ELB, data transfer.
**SQS:** requests (standard vs FIFO), data transfer.

### Step 4 — Anomaly flagging (when `--compare-to-prior` is set)

If the prior equivalent window has a top-5 cost driver that's >2× the current window (or vice versa), flag it with `⚠️`. If a new category appeared that wasn't in the prior window, flag with `🆕`. If a category dropped to zero, flag with `⬇️`.

Use CE's multi-period feature — query the 2× window and split in post-processing — rather than making two separate CE calls.

### Step 5 — Output format

**`--format markdown` (default, direct mode):**

```markdown
## Cost-Check Summary — <service_or_"all"> over last <N> days (YYYY-MM-DD to YYYY-MM-DD)

<cost table — categories sorted by cost desc>

**Headline:** $<total> over <N> days = ~$<annualized>/year
- <top-driver-1>: $<cost> (<%>) — <qualitative note>
- <top-driver-2>: $<cost> (<%>)
- <top-driver-3>: $<cost> (<%>)

**Changes vs prior <N> days** (when `--compare-to-prior` set):
- ⚠️ <driver>: <delta> %
- 🆕 New: <driver>
- ⬇️ Dropped: <driver>
```

**`--format json` (sub-skill mode):**

```json
{
  "query": {"service": "S3", "days": 30, "granularity": "MONTHLY", "group_by": "USAGE_TYPE"},
  "time_period": {"start": "2026-03-23", "end": "2026-04-22"},
  "total_cost_usd": 32820.89,
  "categories": [
    {"name": "PUT/COPY/POST/LIST (Tier1)", "cost_usd": 15016.91, "quantity": 2801375782, "unit": "Requests", "pct": 45.8},
    ...
  ],
  "flags": [
    {"severity": "info", "category": "...", "msg": "..."}
  ]
}
```

**`--format raw`:** pass through the raw CE JSON for callers that want to parse themselves.

## Sub-skill API

Other skills call `/cost-check` via:

```bash
# From inside another skill's procedure:
SUMMARY_JSON=$(/home/mork/.claude/skills/cost-check/run.sh --service DynamoDB --days 7 --format json)
# Parse with jq or inline python
```

(The `run.sh` wrapper is a thin shell that maps CLI args to the CE invocation + post-processing; it's created from this skill's canonical procedure and lives alongside `SKILL.md`.)

**Contract:** sub-skill mode must return within 30s, return non-zero exit code on CE error (with `stderr` explaining why), and emit valid JSON or nothing on stdout.

## Discipline (same spirit as NR query rules)

1. **Always filter** to a single service when drilling down — unfiltered `--group-by USAGE_TYPE` returns thousands of rows with rounding-error-tiny costs.
2. **Small time windows by default.** 30 days is the default. Use 7 or 3 days when looking for recent changes. Use 90+ only for long-term trend questions.
3. **MONTHLY for 30+ days / DAILY for 7-30 / HOURLY only for same-day.** CE bills per query-day; don't use HOURLY on a 30-day window.
4. **Cache query results to `/tmp/ce_$$.json`** during a session — CE calls are slow and usage-billed.
5. **Surface only aggregates.** Never dump raw `ResultsByTime` to the user. Classify + summarize + percent-of-total is the minimum useful output.
6. **Suppress rows <$0.01** when total >$10 — rounding-error noise, not signal.
7. **Use `UnblendedCost`** by default. Switch to `BlendedCost` only for consolidated-billing-aware views (rare).

## Error handling

| Error | Symptom | Fix |
|-------|---------|-----|
| SSO token expired | `Error when retrieving token from sso: Token has expired and refresh failed` | User runs `aws sso login --profile prod`; restart skill. |
| Profile not found | `The config profile (prod) could not be found` | Check `aws configure list-profiles`; fix config. |
| Service name not recognized | `ValidationException: No results` | Verify service name against the alias table; pass full canonical name via `--service`. |
| No data in window | Empty `Groups` | Time window precedes CE retention (13 months default); adjust `--days`. |
| `AccessDenied` | `User: ... is not authorized to perform: ce:GetCostAndUsage` | Permission missing on the profile's role; needs admin attention. |

## Related

- `topics/engineering-process/notes/concepts/aws-cost-explorer-access-pattern.md` — the canonical invocation + post-processing recipe this skill automates
- `topics/engineering-process/notes/concepts/nrql-efficient-query-patterns.md` — adjacent NR query discipline; same summarise-don't-dump philosophy
- `topics/personal-notes/notes/entities/mark-todos.md` Not-Yet-Prioritized → "AWS Cost Explorer integration for skills/checks" (the tracking line-item that spawned this skill)
- Load-bearing first use: `topics/fleet-architecture/notes/syntheses/2026-04-22_frame-storage-design-deltas.md` (API-calls-dominate validation; corrected via this skill's predecessor ad-hoc query)
- Future extensions: per-bucket filtering via CUR + Athena (follow-up, not in scope for v1)
