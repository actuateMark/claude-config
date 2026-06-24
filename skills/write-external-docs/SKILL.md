---
name: write-external-docs
description: Write or review API docs for external partner audience — strips internal details, mid-level engineer audience, per-model/endpoint pages with examples. Trigger: '/write-external-docs', 'partner docs'.
user-invocable: true
allowed-tools:
  - Read
  - Write
  - Edit
  - Glob
  - Grep
  - Bash
  - Agent
---

# Write External Documentation

Create or review API documentation intended for external integration partners. The output must contain zero internal implementation details.

## Arguments

- A path to a docs directory, or a description of what to document
- No args: review all docs in the current repo's `docs/api/` for internal leaks

## Audience

**Mid-level external engineer** integrating with the API. They:
- Know HTTP, JSON, REST, curl
- Don't know your infrastructure, framework, or internal architecture
- Need: what to call, what to send, what to expect back, what can go wrong
- Don't need: how it works internally, what roles exist, what libraries you use

## What to Include

For each **endpoint**:
- HTTP method and path
- Request format with full JSON example
- Parameter table: name, type, default, description
- Response format with full JSON example
- Field descriptions for every response field
- Error codes table: status code + what it means (user-facing language)
- 2-3 curl examples showing common use cases

For each **model/resource variant**:
- Model ID and brief description (benefit-oriented, not mechanism)
- Detection classes / capabilities
- Accepted parameters specific to this variant
- Confidence thresholds by sensitivity level (if applicable)
- Example request and response

## What to NEVER Include

| Category | Examples to Remove |
|----------|-------------------|
| **Role/RBAC details** | Role names (`intruder`, `full_access`, `v5_detect`), AcceptedRoles, CheckRoles |
| **Infrastructure** | Lambda, API Gateway, DynamoDB, ECR, Terraform, Kubernetes, Mangum |
| **Libraries/frameworks** | Pydantic, PIL, FastAPI, SAHI, OpenCV, aiohttp |
| **Internal code** | File paths (`api/v5/registry.py`), class names (`StandardModelData`), function names |
| **Internal tooling** | Test pages, run scripts, dev endpoints, proxy endpoints |
| **Processing internals** | "RBAC check before validation", "PIL verification", "thread pool", "filter chain" |
| **Deployment details** | "Lambda payload limit", env vars, deployment stages, CI/CD |

## Rewording Patterns

| Internal Language | External Language |
|-------------------|-------------------|
| "SAHI sliced inference" | "analyzes images at multiple zoom levels" |
| "frame differences / absolute pixel diff" | "detects moving objects, ignores static background" |
| "PIL verification" | "validated as a valid image" |
| "Lambda payload limit of 6MB" | "maximum ~4.5 MB per base64-encoded frame" |
| "Model server not configured" | (use generic 500 error) |
| "filtered by your API key's roles" | "available to your API key" |

## Procedure

1. **Identify all docs** — `Glob` for `docs/api/**/*.md` (or the specified path)

2. **For new docs:** Write from scratch following the templates above. One file per endpoint, one file per model/resource variant.

3. **For review:** Read each file and check for:
   - Any internal role names, class names, or file paths
   - References to infrastructure (Lambda, API Gateway, k8s, DynamoDB)
   - References to libraries (Pydantic, PIL, SAHI, FastAPI)
   - Processing order / internal pipeline details
   - Dev-only URLs (`dev-api.actuateui.net`, `localhost`)
   - Missing examples or incomplete parameter tables

4. **For dynamic content:** If model lists appear in docs, use `<!-- MODEL_TABLE -->` placeholder so the serving layer can role-filter them at runtime.

5. **Verify:** After writing, re-read every file and confirm zero internal leaks. Check that examples use production URLs (`api.actuateui.net`), not dev URLs.

## Prose Rules

- **No redundant descriptions.** If the heading says `# intruder` and the next section is a detection classes table, don't add "Detects people, bicycles, and vehicles in a scene" — the reader can see that.
- **Only add prose when it tells the reader something the tables don't.** Examples that earn their space:
  - "Higher default confidence thresholds to minimize false positives." (explains the unusual threshold values)
  - "Focuses on moving objects, ignores static background. Requires 2+ frames." (explains when to pick this model over others)
  - "Better accuracy for small or distant objects in high-resolution images." (explains the tradeoff)
- **One line max.** If a model intro can't justify itself in one line, delete it.
- **No filler phrases:** "in a scene", "This model...", "Detailed documentation for...", "Click below to see...", "This page describes..."
- **Let structure speak.** Headings, tables, and code blocks are self-evident. Don't narrate them.

## Quality Bar

Before marking docs as complete, verify:
- [ ] Every endpoint has a request example, response example, and error table
- [ ] Every model page has parameters, thresholds, and request/response examples
- [ ] No internal role names, class names, file paths, or library names anywhere
- [ ] No redundant prose restating what the tables already show
- [ ] Prose only where it adds context the reader can't derive from structure alone
- [ ] All URLs use production base (`api.actuateui.net`), not dev
- [ ] Parameter tables include type, default, and description for every field
- [ ] Response field table describes every field in the example response
