#!/usr/bin/env bash
# cost-check — AWS Cost Explorer query wrapper
# Usage: run.sh [SERVICE] [--days N] [--granularity G] [--group-by G] [--format markdown|json|raw] [--compare-to-prior]
# See SKILL.md for full contract.

set -euo pipefail

# --- arg parsing ---
SERVICE=""
DAYS=30
GRANULARITY=""
GROUP_BY=""
FORMAT="markdown"
COMPARE_TO_PRIOR=0
TOP_SERVICES=0
FILTER_KEY=""
FILTER_VALUES=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --service) SERVICE="$2"; shift 2 ;;
    --days) DAYS="$2"; shift 2 ;;
    --granularity) GRANULARITY="$2"; shift 2 ;;
    --group-by) GROUP_BY="$2"; shift 2 ;;
    --format) FORMAT="$2"; shift 2 ;;
    --compare-to-prior) COMPARE_TO_PRIOR=1; shift ;;
    --top-services) TOP_SERVICES=1; shift ;;
    --filter-key) FILTER_KEY="$2"; shift 2 ;;
    --filter-values) FILTER_VALUES="$2"; shift 2 ;;
    --help|-h)
      echo "Usage: $0 [SERVICE] [--days N] [--granularity G] [--group-by G] [--format F] [--compare-to-prior] [--top-services]"
      exit 0 ;;
    -*) echo "Unknown flag: $1" >&2; exit 2 ;;
    *)
      # positional service alias
      if [[ -z "$SERVICE" ]]; then SERVICE="$1"; else echo "Extra positional arg: $1" >&2; exit 2; fi
      shift ;;
  esac
done

# --- service alias resolution ---
case "$SERVICE" in
  "") CANONICAL_SERVICE="" ;;
  S3|s3) CANONICAL_SERVICE="Amazon Simple Storage Service" ;;
  DynamoDB|DDB|dynamodb|ddb) CANONICAL_SERVICE="Amazon DynamoDB" ;;
  Lambda|lambda) CANONICAL_SERVICE="AWS Lambda" ;;
  EC2|ec2) CANONICAL_SERVICE="Amazon Elastic Compute Cloud - Compute" ;;
  EBS|ebs) CANONICAL_SERVICE="Amazon Elastic Block Store" ;;
  RDS|rds) CANONICAL_SERVICE="Amazon Relational Database Service" ;;
  SQS|sqs) CANONICAL_SERVICE="Amazon Simple Queue Service" ;;
  SNS|sns) CANONICAL_SERVICE="Amazon Simple Notification Service" ;;
  CloudWatch|CW|cloudwatch|cw) CANONICAL_SERVICE="AmazonCloudWatch" ;;
  "Secrets Manager"|secrets-manager) CANONICAL_SERVICE="AWS Secrets Manager" ;;
  EKS|eks) CANONICAL_SERVICE="Amazon Elastic Container Service for Kubernetes" ;;
  CloudTrail|cloudtrail) CANONICAL_SERVICE="AWS CloudTrail" ;;
  CodeArtifact|codeartifact) CANONICAL_SERVICE="AWS CodeArtifact" ;;
  *) CANONICAL_SERVICE="$SERVICE" ;;  # pass-through; CE will reject unknowns
esac

# --- default granularity / group-by ---
if [[ -z "$GRANULARITY" ]]; then
  if [[ "$DAYS" -ge 30 ]]; then GRANULARITY="MONTHLY"; else GRANULARITY="DAILY"; fi
fi
if [[ -z "$GROUP_BY" ]]; then
  if [[ -n "$CANONICAL_SERVICE" ]]; then GROUP_BY="USAGE_TYPE"; else GROUP_BY="SERVICE"; fi
fi
if [[ "$TOP_SERVICES" -eq 1 ]]; then GROUP_BY="SERVICE"; CANONICAL_SERVICE=""; fi

# --- time window ---
START=$(date -d "${DAYS} days ago" +%Y-%m-%d)
END=$(date +%Y-%m-%d)

# --- preflight: verify SSO + permission ---
if ! AWS_PROFILE=prod aws sts get-caller-identity --no-cli-pager >/dev/null 2>&1; then
  echo "ERROR: AWS_PROFILE=prod is not authenticated. Run: aws sso login --profile prod" >&2
  exit 3
fi

# --- build filter ---
FILTER_JSON=""
if [[ -n "$CANONICAL_SERVICE" ]]; then
  FILTER_JSON=$(printf '{"Dimensions":{"Key":"SERVICE","Values":["%s"]}}' "$CANONICAL_SERVICE")
elif [[ -n "$FILTER_KEY" && -n "$FILTER_VALUES" ]]; then
  # comma-list → JSON array
  VALS_JSON=$(echo "$FILTER_VALUES" | awk -F, '{for(i=1;i<=NF;i++) printf "\"%s\"%s", $i, (i<NF?",":"")}')
  FILTER_JSON=$(printf '{"Dimensions":{"Key":"%s","Values":[%s]}}' "$FILTER_KEY" "$VALS_JSON")
fi

# --- run CE query ---
CE_FILE="/tmp/ce_$$.json"
if [[ -n "$FILTER_JSON" ]]; then
  AWS_PROFILE=prod aws ce get-cost-and-usage \
    --time-period "Start=${START},End=${END}" \
    --granularity "$GRANULARITY" \
    --metrics "UnblendedCost" "UsageQuantity" \
    --filter "$FILTER_JSON" \
    --group-by "Type=DIMENSION,Key=${GROUP_BY}" \
    --no-cli-pager > "$CE_FILE"
else
  AWS_PROFILE=prod aws ce get-cost-and-usage \
    --time-period "Start=${START},End=${END}" \
    --granularity "$GRANULARITY" \
    --metrics "UnblendedCost" "UsageQuantity" \
    --group-by "Type=DIMENSION,Key=${GROUP_BY}" \
    --no-cli-pager > "$CE_FILE"
fi

# --- post-process ---
export CE_FILE SERVICE CANONICAL_SERVICE DAYS GRANULARITY GROUP_BY FORMAT START END

if [[ "$FORMAT" == "raw" ]]; then
  cat "$CE_FILE"
  rm -f "$CE_FILE"
  exit 0
fi

python3 <<'PYEOF'
import json, collections, os, sys, datetime

CE_FILE = os.environ['CE_FILE']
SERVICE = os.environ.get('CANONICAL_SERVICE', '') or os.environ.get('SERVICE', '')
DAYS = int(os.environ['DAYS'])
GROUP_BY = os.environ['GROUP_BY']
FORMAT = os.environ['FORMAT']
START = os.environ['START']
END = os.environ['END']

data = json.load(open(CE_FILE))

def classify(ut, service):
    # Service-specific classification
    s = (service or '').lower()
    if 'storage service' in s or 's3' in s:
        if 'Tier1' in ut: return 'PUT/COPY/POST/LIST (Tier1)'
        if 'Tier2' in ut: return 'GET/SELECT (Tier2)'
        if 'Tier3' in ut: return 'Replication/Lifecycle (Tier3)'
        if 'Tier8' in ut or 'Tier9' in ut: return 'Glacier retrieval (Tier8/9)'
        if 'TimedStorage' in ut or ('Storage' in ut and 'Requests' not in ut): return 'Storage (GB-month)'
        if 'DataTransfer' in ut or 'CloudFront-Out' in ut or 'AWS-Out-Bytes' in ut or 'AWS-In-Bytes' in ut: return 'Data transfer'
        if 'EarlyDelete' in ut: return 'Early-delete fees'
        if 'Retrieval' in ut: return 'Retrieval fees'
        return f'Other: {ut}'
    if 'dynamodb' in s:
        if 'ReadRequestUnits' in ut or 'ReadCapacityUnit' in ut: return 'Read capacity'
        if 'WriteRequestUnits' in ut or 'WriteCapacityUnit' in ut: return 'Write capacity'
        if 'TimedStorage' in ut: return 'Storage'
        if 'Streams' in ut: return 'Streams'
        if 'Backup' in ut or 'PITR' in ut: return 'Backup/PITR'
        if 'DAX' in ut: return 'DAX'
        return f'Other: {ut}'
    if 'lambda' in s:
        if 'Request' in ut or 'Invocation' in ut: return 'Invocations'
        if 'Lambda-GB-Second' in ut or 'GB-Second' in ut: return 'Compute (GB-sec)'
        if 'Provisioned' in ut: return 'Provisioned concurrency'
        if 'DataTransfer' in ut: return 'Data transfer'
        return f'Other: {ut}'
    if 'ec2' in s or 'elastic compute' in s:
        if 'BoxUsage' in ut:
            return f'Compute: {ut.split(":")[-1] if ":" in ut else ut}'
        if 'EBS' in ut: return 'EBS volumes'
        if 'NatGateway' in ut or 'NAT' in ut: return 'NAT gateway'
        if 'LoadBalancer' in ut or 'ELB' in ut: return 'Load balancer'
        if 'DataTransfer' in ut: return 'Data transfer'
        return f'Other: {ut}'
    # generic fallback
    return ut[:60]

categories = collections.defaultdict(lambda: {'cost': 0.0, 'quantity': 0.0, 'unit': '', 'raw_types': []})
for bucket in data.get('ResultsByTime', []):
    for g in bucket.get('Groups', []):
        key = g['Keys'][0]
        cost = float(g['Metrics']['UnblendedCost']['Amount'])
        qty = float(g['Metrics']['UsageQuantity']['Amount'])
        unit = g['Metrics']['UsageQuantity']['Unit']
        c = classify(key, SERVICE)
        categories[c]['cost'] += cost
        categories[c]['quantity'] += qty
        categories[c]['unit'] = unit
        categories[c]['raw_types'].append(key)

total = sum(v['cost'] for v in categories.values())
rows = sorted(categories.items(), key=lambda kv: -kv[1]['cost'])

if FORMAT == 'json':
    out = {
        "query": {
            "service": SERVICE or "all",
            "days": DAYS,
            "granularity": os.environ['GRANULARITY'],
            "group_by": GROUP_BY,
        },
        "time_period": {"start": START, "end": END},
        "total_cost_usd": round(total, 2),
        "categories": [
            {
                "name": cat,
                "cost_usd": round(v['cost'], 4),
                "quantity": round(v['quantity'], 2),
                "unit": v['unit'],
                "pct": round(100 * v['cost'] / total, 2) if total else 0.0,
            }
            for cat, v in rows if v['cost'] >= 0.01 or total < 10
        ],
        "flags": [],
    }
    print(json.dumps(out, indent=2))
else:
    # markdown
    hdr = f"## Cost-Check Summary — {SERVICE or 'all services'} over last {DAYS} days ({START} to {END})"
    print(hdr)
    print()
    if not rows:
        print("_No data returned — check service name or time window._")
        sys.exit(0)
    print(f"| {'Category':42s} | {'Cost (USD)':>12s} | {'Quantity':>22s} | {'% total':>7s} |")
    print(f"|{'-'*44}|{'-'*14}|{'-'*24}|{'-'*9}|")
    for cat, v in rows:
        if v['cost'] < 0.01 and total > 10: continue
        q_str = f"{v['quantity']:,.2f} {v['unit'][:12]}"
        pct = 100 * v['cost'] / total if total else 0
        print(f"| {cat:42s} | ${v['cost']:>10,.2f} | {q_str:>22s} | {pct:>6.1f}% |")
    print(f"|{'-'*44}|{'-'*14}|{'-'*24}|{'-'*9}|")
    print(f"| {'**TOTAL**':42s} | **${total:,.2f}** | {'':22s} | |")
    print()
    # Headline
    annual = total * 365 / DAYS
    print(f"**Headline:** ${total:,.2f} over {DAYS} days = ~${annual:,.0f}/year annualized")
    if rows:
        print("\n**Top cost drivers:**")
        for cat, v in rows[:3]:
            pct = 100 * v['cost'] / total if total else 0
            print(f"- {cat}: ${v['cost']:,.2f} ({pct:.1f}%)")
PYEOF

rm -f "$CE_FILE"
