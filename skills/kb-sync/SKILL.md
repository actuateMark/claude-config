---
name: kb-sync
description: Refresh the knowledge base by re-scanning Confluence and Jira for updates. Identifies stale topics and updates them with current data. Trigger on "kb sync", "refresh kb", "update kb", "sync knowledge base", "kb is stale", "refresh knowledge base".
user-invocable: true
allowed-tools:
  - Bash
  - Read
  - Write
  - Edit
  - Glob
  - Grep
  - Agent
  - mcp__atlassian__getConfluencePage
  - mcp__atlassian__getJiraIssue
  - mcp__atlassian__searchConfluenceUsingCql
  - mcp__atlassian__searchJiraIssuesUsingJql
  - mcp__atlassian__searchAtlassian
  - mcp__atlassian__getPagesInConfluenceSpace
---

# KB Sync

Refresh the Obsidian knowledge base at `/home/mork/Documents/worklog/knowledgebase/` by re-scanning Confluence and Jira for updates since the last sync.

## Arguments

- No args: Full sync across all topics
- A topic slug (e.g., `inference-api`): Sync only that topic
- `--jira`: Only refresh Jira-sourced data (tickets, assignments, statuses)
- `--confluence`: Only refresh Confluence-sourced data

## Procedure

1. **Read `_checkpoint.md`** to determine last sync date.
2. **Read `_index.md`** to understand current KB state.
3. **For each topic (or the specified topic):**
   a. Read the `_summary.md` to understand what's tracked
   b. Check Confluence pages referenced in frontmatter (`confluence:` fields) for updates since last sync
   c. Check Jira tickets referenced in frontmatter (`jira:` fields) for status changes
   d. Search for new pages/tickets not yet in the KB
4. **Launch parallel agents** for different Confluence spaces and Jira projects to maximize throughput.
5. **Update notes:**
   - Update entity notes with current Jira statuses and assignments
   - Update concept notes if Confluence pages have been modified
   - Update summaries if the big picture has changed
   - Create new source notes for newly discovered content
   - Always set `updated:` date and preserve `author: kb-bot`
6. **Update `_checkpoint.md`** with new sync timestamp.
7. **Update `_index.md`** if new topics were created.
8. **Report:** What changed, what was added, what's still stale.

## Confluence Spaces to Scan

| Space | Key | Focus |
|-------|-----|-------|
| Engineering Docs | EDOCS | Library docs, connector, inference API |
| Product Management | PM | Watchman, infrastructure |
| Data Science | DS | Models, evaluation, methodology |
| Integrations | Integratio | EBUS, Morphean, Evalink |
| Product Roadmap | PR | Roadmap, initiatives |
| Jira Process | CAJP | Jira reorg, process |
| Knowledge Base | kb | Operational docs (200 pages) |

## Jira Projects to Scan

ENG, ED, AI, AUTO, CS3, SA, AIM, PROD, BT, BACK

## Rules

- **Never delete notes.** If content is outdated, update it; don't remove it.
- **Never edit source notes.** Sources are immutable. Create new sources for updated content.
- **Never edit human-authored notes** (notes without `author: kb-bot`).
- **Parallelize aggressively.** Launch multiple agents for different spaces/projects.
- **Track what changed.** The report should clearly list what was updated and why.
