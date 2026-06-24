---
name: stage-release
description: Push a feature branch to develop via PR, watch CI, merge, verify dev deploy. Full cycle PR → live verification. Trigger: '/stage-release', 'push to dev'.
user-invocable: true
allowed-tools:
  - Bash
  - Read
  - Edit
  - Grep
  - Glob
  - Agent
---

# Stage Release to Dev

Push changes from the current feature branch to develop, verify CI, merge, and confirm the dev deployment works.

## Prerequisites

- On a feature branch with commits ahead of develop
- All tests passing locally
- Lint clean

## Procedure

### 1. Pre-flight checks

```bash
# Verify branch and status
git branch --show-current
git status --short
git log --oneline origin/develop..HEAD | head -10

# Run tests
uv run --project=inference_api pytest inference_api/inference_api/test/ -q --tb=short

# Lint
ruff check inference_api/
```

If tests or lint fail, fix before proceeding.

### 2. Create or update PR

Check if a PR already exists for this branch:

```bash
gh pr list --head $(git branch --show-current) --state open --repo aegissystems/actuate-inference-api
```

If no PR exists, create one:

```bash
gh pr create --base develop --title "TITLE" --body-file /tmp/pr-body.md
```

If PR exists, ensure it's up to date (push any new commits).

### 3. Watch CI

```bash
gh pr checks PR_NUMBER --repo aegissystems/actuate-inference-api
```

Wait for all checks to pass:
- **Test** — unit tests
- **Build Image** — Docker image to ECR
- **Terraform** (x3 regions) — plan on PR, apply on merge

If terraform plan comments aren't posting, check `pull-requests: write` permission in the workflow.

### 4. Review terraform plans

```bash
gh api repos/aegissystems/actuate-inference-api/issues/PR_NUMBER/comments --jq '.[-3:][].body' | grep -E 'Plan:|will be updated'
```

Expected for code-only changes: `Plan: 0 to add, 1 to change, 0 to destroy` (Lambda image digest update only).

### 5. Merge

```bash
gh pr merge PR_NUMBER --repo aegissystems/actuate-inference-api --merge
```

### 6. Watch deploy

After merge, `deploy-dev.yaml` triggers automatically:

```bash
gh run list --repo aegissystems/actuate-inference-api --branch develop --limit 3
```

Wait for "Deploy to AWS" to complete. Check all jobs:

```bash
gh run view RUN_ID --repo aegissystems/actuate-inference-api --json jobs --jq '.jobs[] | "\(.name): \(.conclusion)"'
```

### 7. Verify on dev

```bash
# Test v5 models endpoint
curl -s -w "\n%{http_code}" https://dev-api.actuateui.net/v5/models \
  -H "X-API-Key: $(grep DEV_API_KEY .env | cut -d= -f2)"

# Test v4 endpoint
curl -s -w "\n%{http_code}" -X POST https://dev-api.actuateui.net/v4/intruder/detections \
  -H "X-API-Key: $(grep DEV_API_KEY .env | cut -d= -f2)" \
  -F "frames=@inference_api/inference_api/test/test_sample.jpg" \
  -F "sensitivity=medium"
```

**API Gateway redeployment is almost always needed.** Terraform only redeploys when gateway resources change (methods, integrations), not when the Lambda image updates. After every merge to develop, force a redeploy:

```bash
REST_API_ID=$(aws apigateway get-rest-apis --region us-west-2 --query "items[?name=='inference_api_lambda_gw-dev'].id" --output text)
aws apigateway create-deployment --rest-api-id $REST_API_ID --stage-name dev --region us-west-2
```

Do the same for eu-west-1 if needed:
```bash
REST_API_ID=$(aws apigateway get-rest-apis --region eu-west-1 --query "items[?name=='inference_api_lambda_gw-dev'].id" --output text)
aws apigateway create-deployment --rest-api-id $REST_API_ID --stage-name dev --region eu-west-1
```

If authorizer errors (500 with `{"message":null}`): verify DynamoDB `roles` field is type `SS` (String Set), not `S` (String).

### 8. Post-deploy

- Update the PR with a verification comment
- Run `/write-external-docs` if endpoint changes were included
- Update KB synthesis notes if applicable

## Known Issues

- **Stale API Gateway deployment:** Now auto-redeployed by CI (PR #51). If you still see stale responses, the Redeploy API Gateway step may have failed — check the workflow logs and manually run `aws apigateway create-deployment` if needed.
- **DynamoDB roles type:** Must be `SS` not `S`. The Rust authorizer crashes with opaque "Unauthorized" if wrong.
- **Authorizer cache:** TTL is 5s on dev. If you change a key's roles, wait a few seconds before retesting.
- **Base64 frames too large for curl args:** When testing v5 endpoints with base64-encoded frames, write the JSON body to a temp file and use `curl -d @/tmp/request.json` — the base64 string exceeds shell argument length limits.
- **S3 presigned URL content-type:** S3 objects uploaded without explicit content type return `binary/octet-stream`. This is accepted by the frame downloader (PR #52) — no action needed.
