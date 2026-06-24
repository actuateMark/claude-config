---
name: kb-lookup
description: Search Obsidian KB for context relevant to the current coding task. Run BEFORE implementation — surfaces architecture decisions, related services, prior art. Trigger: '/kb-lookup', 'check kb first'.
user-invocable: true
allowed-tools:
  - Read
  - Glob
  - Grep
  - Bash
---

# KB Lookup

Fast, focused search of the Obsidian KB at `/home/mork/Documents/worklog/knowledgebase/` to gather context before coding.

**This is not a research skill.** It reads what's already in the KB. For ingesting new information, use `/kb-ingest` or `/kb-sync`.

## Arguments

- A topic, service name, or question: `inference-api`, `how does the pipeline work`, `EBUS`, `actuate-filters`
- No args: Infer the relevant topic from the current working directory

## Procedure

### Step 0 — Prefer the Obsidian CLI for discovery

The CLI at `~/.local/bin/obsidian` exposes structured discovery primitives that beat recursive Grep on token cost. Probe first with `~/.local/bin/obsidian vault 2>&1 | head -1`. If it works, prefer the CLI for:

| Goal | CLI command | Replaces |
|---|---|---|
| All notes tagged with a topic | `obsidian tag name=#<topic>` | Grep over frontmatter `tags:` |
| All notes that link to an entity | `obsidian backlinks file=<entity-slug>` | Recursive Grep for `[[entity-slug]]` |
| Vault-wide phrase search | `obsidian search query="<phrase>"` | Recursive Grep |
| Search w/ line context | `obsidian search:context query="<phrase>"` | Grep -C 3 |
| Read by name (no path) | `obsidian read file=<name>` | Read with absolute path |

Tag-driven discovery is often the fastest route to relevant notes — most KB topics have a corresponding `#<topic>` tag, and `obsidian tag name=#<topic>` returns the full file list in one call.

### Step 1 — Resolve search terms

Determine search terms from the argument or current working directory:
- If in `/home/mork/work/actuate-inference-api` -> search for `inference-api`
- If in `/home/mork/work/vms-connector` -> search for `vms-connector`
- If in `/home/mork/work/actuate-libraries/actuate-filters` -> search for `actuate-filters`, `filters`
- Otherwise, use the provided argument

### Step 2 — Topic summary first (cheapest path)

```
Read /home/mork/Documents/worklog/knowledgebase/topics/<term>/_summary.md
```

If the topic doesn't exist as a directory, fall through to Step 3.

### Step 3 — Tag-driven discovery (preferred over Grep)

```bash
~/.local/bin/obsidian tag name="#<term>"     # all files tagged with the topic
~/.local/bin/obsidian backlinks file=<term>  # what links to the topic anchor
```

If `<term>` is not a registered tag, run `obsidian tags counts | grep -i <fragment>` to find the right canonical tag form before searching.

### Step 4 — Phrase search (when tags don't fit)

```bash
~/.local/bin/obsidian search:context query="<phrase>"
```

Falls back to Grep if the CLI is unavailable.

### Step 5 — Cross-topic context

- If the topic summary references other topics via `[[wikilinks]]`, read those summaries too.
- Run `obsidian backlinks file=<topic-summary>` to find notes that reference this topic from other topics — often more useful than re-grepping.

### Step 6 — Return a concise brief

Under 500 words containing:
- **What this is:** One-paragraph summary from the topic
- **Key architecture:** How it fits into the platform
- **Active work:** Current Jira tickets, who's working on what
- **Watch out for:** Known issues, risks, ADRs, design decisions
- **Related:** Links to other KB topics that may be relevant
- **Tag inventory:** Top-3 tags from the matched notes (helps the caller pick follow-up `obsidian tag name=#X` queries)

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
