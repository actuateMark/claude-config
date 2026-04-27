---
name: kb-lookup
description: Search the Obsidian knowledge base for context relevant to the current coding task. Use this BEFORE starting implementation work -- it surfaces architecture decisions, related services, team context, integration patterns, and prior art. Should be invoked automatically when working on Actuate codebases. Trigger on "kb lookup", "check kb first", "what do we know about", "context for".
user-invocable: true
allowed-tools:
  - Read
  - Glob
  - Grep
---

# KB Lookup

Fast, focused search of the Obsidian KB at `/home/mork/Documents/worklog/knowledgebase/` to gather context before coding.

**This is not a research skill.** It reads what's already in the KB. For ingesting new information, use `/kb-ingest` or `/kb-sync`.

## Arguments

- A topic, service name, or question: `inference-api`, `how does the pipeline work`, `EBUS`, `actuate-filters`
- No args: Infer the relevant topic from the current working directory

## Procedure

1. **Determine search terms** from the argument or current working directory:
   - If in `/home/mork/work/actuate-inference-api` -> search for `inference-api`
   - If in `/home/mork/work/vms-connector` -> search for `vms-connector`
   - If in `/home/mork/work/actuate-libraries/actuate-filters` -> search for `actuate-filters`, `filters`
   - Otherwise, use the provided argument

2. **Read the topic summary** (fastest path to context):
   ```
   Glob: topics/*/_ summary.md matching the search term
   Read the matched _summary.md
   ```

3. **Search for specific entity/concept notes:**
   ```
   Grep: search term across topics/*/notes/**/*.md
   Read the top 3-5 most relevant hits
   ```

4. **Check for related cross-topic context:**
   - If the topic summary references other topics via `[[wikilinks]]`, read those summaries too
   - Look for synthesis notes that span the relevant topics

5. **Return a concise brief** (under 500 words) containing:
   - **What this is:** One-paragraph summary from the topic
   - **Key architecture:** How it fits into the platform
   - **Active work:** Current Jira tickets, who's working on what
   - **Watch out for:** Known issues, risks, ADRs, design decisions
   - **Related:** Links to other KB topics that may be relevant

## Auto-Detection by Working Directory

| Working Directory | Primary Topic | Also Check |
|-------------------|--------------|------------|
| `actuate-inference-api` | inference-api | external-api, ebus-integration, actuate-libraries |
| `vms-connector` | vms-connector | actuate-libraries, ai-models, data-science |
| `actuate-libraries` | actuate-libraries | vms-connector, inference-api |
| `actuate_admin` | admin-api | external-api, infrastructure |
| `autopatrol-server` | autopatrol | actuate-libraries, vms-connector |
| `kubernetes-deployments` | infrastructure | vms-connector, actuate-platform |
| `ds-terraform-eks-v2` | infrastructure | actuate-platform |

## Rules

- **Be fast.** This runs before coding starts. Read summaries first, detail notes only if needed.
- **Read-only.** Never write to the KB from this skill.
- **Surface decisions.** ADRs, design choices, and "why" context are more valuable than "what" descriptions.
- **Flag staleness.** If the `updated:` date on a note is older than 14 days, mention it.
