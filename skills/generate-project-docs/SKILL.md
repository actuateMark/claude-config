---
name: generate-project-docs
description: Generate comprehensive project documentation (API docs, backend architecture, testing guides) for any repository. Creates docs/, sets up Confluence sync via GitHub Actions, generates a bespoke per-project maintenance skill, verifies accuracy, and adds a CLAUDE.md rule. Trigger on "generate docs", "create documentation", "document this project", "set up project docs", "docs generation".
user-invocable: true
allowed-tools:
  - Bash
  - Read
  - Write
  - Edit
  - Glob
  - Grep
  - Agent
---

# Project Documentation Generator

Generate, verify, and publish comprehensive project documentation for any repository. Syncs to Confluence and creates a self-maintaining per-project skill.

## What This Skill Does

1. **Explores the codebase** to understand architecture, endpoints, models, config, testing, and deployment
2. **Creates a `docs/` directory** with two sections:
   - `docs/api/` -- External-facing documentation (safe to share with customers/partners)
   - `docs/backend/` -- Internal developer documentation (architecture, deployment, testing)
3. **Sets up Confluence sync** via GitHub Actions -- pushes docs to Confluence on every push
4. **Generates a bespoke per-project maintenance skill** (`.claude/skills/update-project-docs/`) that can detect code changes, update affected docs, and self-update
5. **Verifies accuracy** by cross-referencing every claim against the actual source code
6. **Adds a CLAUDE.md rule** requiring docs to be updated when the codebase changes
7. **Commits all changes** on the current branch

## Arguments

- No args: Full documentation generation (explore, generate, confluence, skill, verify, commit)
- `verify`: Only verify existing docs against the codebase, report inaccuracies
- `confluence`: Only set up Confluence sync (assumes docs/ already exists)

## Prerequisites

**GitHub org secrets** (must be configured once per org):
- `CONFLUENCE_USER_EMAIL` -- Atlassian account email for API access
- `CONFLUENCE_API_TOKEN` -- Atlassian API token (generate at https://id.atlassian.com/manage-profile/security/api-tokens)

**Confluence space:** `EDOCS` (Engineering Docs). The sync script will check for this space. Create it manually if it doesn't exist.

## Documentation Structure

```
docs/
  README.md                        -- Index with links to all sections
  api/                             -- EXTERNAL-FACING
    README.md                      -- API overview, base URLs, versioning
    authentication.md              -- Auth mechanism, roles, access control
    models.md                      -- All request/response schemas
    errors.md                      -- Error codes, troubleshooting
    [endpoint docs]                -- One file per API version or endpoint group
    customers/                     -- Per-customer integration guides (if applicable)
  backend/                         -- INTERNAL
    README.md                      -- Architecture overview, component diagram
    [topic docs]                   -- One file per architectural topic
    architecture-decisions.md      -- ADRs for key design choices
    project-plan.md                -- Current project plan (if applicable)
```

## Steps

### Phase 1: Explore the Codebase

Launch up to 3 Explore agents in parallel to understand:

**Agent 1 -- API Surface:**
- Framework (FastAPI, Django, Flask, Express, etc.)
- All endpoints, routes, request/response shapes
- Authentication/authorization mechanism
- Error handling patterns
- API versioning strategy

**Agent 2 -- Backend Architecture:**
- Project structure and key directories
- Core business logic and data flow
- Database models and storage
- External service integrations
- Configuration and environment variables

**Agent 3 -- DevOps & Testing:**
- Build system (package.json, pyproject.toml, Makefile, etc.)
- Test framework and patterns
- CI/CD pipelines
- Deployment mechanism (Docker, k8s, Lambda, etc.)
- Existing documentation (README.md, CLAUDE.md, .cursorrules, etc.)

### Phase 2: Generate Documentation

Based on exploration results, create the `docs/` directory structure.

**For each doc file:**
- Write content based on what was actually found in the code -- never fabricate
- Include specific file paths, function names, and line references where helpful
- Use code examples from the actual codebase
- Link between docs where concepts connect

**Adapt the structure to the project type:**
- REST API: endpoint docs per version, auth, models, errors
- Library: public API reference, usage examples, architecture
- CLI tool: command reference, configuration, plugins
- Microservice: service interactions, message formats, deployment

### Phase 3: Set Up Confluence Sync

1. **Detect repo info:**
   ```bash
   REPO_NAME=$(basename $(git remote get-url origin) .git)
   ```

2. **Create `.github/scripts/sync_docs_to_confluence.py`** -- Python script that:
   - Reads all `.md` files from `docs/` recursively
   - Converts markdown to Confluence storage format (XHTML)
   - Creates pages if missing, updates if content changed (idempotent)
   - Maintains parent-child hierarchy matching directory structure
   - Tracks page IDs in `.github/confluence-page-map.json` for fast updates
   - Uses `atlassian-python-api` for Confluence Cloud REST API
   - Auth via `CONFLUENCE_USER` + `CONFLUENCE_TOKEN` env vars

3. **Create `.github/workflows/sync-docs.yaml`:**
   ```yaml
   name: Sync Docs to Confluence
   on:
     push:
       branches: [main, develop]
       paths: ['docs/**']
     workflow_dispatch:
   jobs:
     sync:
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v4
         - uses: actions/setup-python@v5
           with:
             python-version: '3.12'
         - run: pip install atlassian-python-api markdown
         - run: python .github/scripts/sync_docs_to_confluence.py
           env:
             CONFLUENCE_URL: https://actuate-team.atlassian.net
             CONFLUENCE_USER: ${{ secrets.CONFLUENCE_USER_EMAIL }}
             CONFLUENCE_TOKEN: ${{ secrets.CONFLUENCE_API_TOKEN }}
             CONFLUENCE_SPACE: EDOCS
             REPO_NAME: {detected_repo_name}
         - name: Commit page map if changed
           run: |
             git config user.name "github-actions[bot]"
             git config user.email "github-actions[bot]@users.noreply.github.com"
             git add .github/confluence-page-map.json
             git diff --staged --quiet || git commit -m "chore: update confluence page map [skip ci]"
             git push || true
   ```

4. **Add `.github/confluence-page-map.json`** to `.gitignore` or commit it (the workflow auto-commits updates).

### Phase 4: Generate Per-Project Maintenance Skill

Create `.claude/skills/update-project-docs/SKILL.md` -- a **bespoke** skill tailored to this specific project.

**The skill must contain:**

1. **A Code-to-Docs Mapping table** -- for every source file, which doc file(s) it feeds. Build this by:
   - Scanning all source files in the project
   - Matching them to the docs you just generated
   - Recording what each doc file documents about each source file

2. **A Current Project State section** -- snapshot of:
   - Endpoint count per version
   - Model/service list
   - Configuration values (limits, thresholds, etc.)
   - Roles/permissions
   - Key dependencies

3. **Step-by-step instructions** for the skill to:
   - Detect changes via `git diff` since last docs commit
   - Match changed files to affected docs using the mapping table
   - Update only affected doc sections
   - Optionally run the Confluence sync script
   - **Self-update**: regenerate the mapping table and project state by rescanning the codebase
   - Commit everything together

**The skill self-updates** by regenerating its own "Project Mapping" section each time it runs. This ensures it stays accurate even if the project structure changes significantly between runs.

### Phase 5: Add CLAUDE.md Documentation Rule

Add or update the `## Documentation` section in CLAUDE.md:

```markdown
## Documentation
When adding or modifying API endpoints, update the corresponding file in docs/api/.
When modifying backend architecture, update the corresponding file in docs/backend/.
Per-customer documentation in docs/api/customers/ must be updated when response contracts change.
Full documentation: see docs/README.md or the Confluence space (https://actuate-team.atlassian.net/wiki/spaces/EDOCS).
```

If CLAUDE.md doesn't exist, create it with the documentation rule included.

### Phase 6: Verify Accuracy

Launch Explore agents to cross-reference every factual claim in the docs against the source code:

- Parameter names and types match function signatures
- Default values match code defaults
- File paths and line numbers are correct
- Response schemas match model definitions
- Error codes and messages match exception handling
- Configuration values match config files
- Architecture descriptions match actual code flow

**Report and fix** any inaccuracies found.

### Phase 7: Commit

Stage and commit all files with a descriptive message:
- `docs/` directory (all documentation)
- `.github/scripts/sync_docs_to_confluence.py`
- `.github/workflows/sync-docs.yaml`
- `.claude/skills/update-project-docs/SKILL.md`
- `CLAUDE.md` updates

Remind the user:
- Ensure `CONFLUENCE_USER_EMAIL` and `CONFLUENCE_API_TOKEN` are set as GitHub org secrets
- The `EDOCS` Confluence space must exist
- Push the branch to trigger the first Confluence sync

## Verification Mode (`verify` argument)

When called with `verify`:
1. Read all files in `docs/`
2. For each factual claim, find the corresponding source code
3. Report discrepancies with file paths and correct values
4. Offer to fix inaccuracies

## Confluence-Only Mode (`confluence` argument)

When called with `confluence`:
1. Detect the repo name from git remote
2. Create the sync script and workflow
3. Add link to CLAUDE.md
4. Commit and remind user about org secrets
