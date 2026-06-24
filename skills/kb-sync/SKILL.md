---
name: kb-sync
description: Refresh the KB by re-scanning Confluence and Jira for updates. Identifies stale topics and updates them. Trigger: '/kb-sync', 'refresh kb'.
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

**CLI-first.** Health probe `~/.local/bin/obsidian vault 2>&1 | head -1`; if it succeeds, prefer the CLI for the scan-heavy parts of this skill.

1. **Read `_checkpoint.md`** to determine last sync date. (`obsidian read path=_checkpoint.md` or filesystem Read.)
2. **Read `_index.md`** to understand current KB state. (`obsidian read path=_index.md` or filesystem Read.)
3. **For each topic (or the specified topic):**
   a. Read the `_summary.md` to understand what's tracked. Use `obsidian read path=topics/<slug>/_summary.md`.
   b. Find notes referencing Confluence/Jira via the CLI rather than recursive Grep:
      - `obsidian search query="confluence:"` (filenames + matches across vault)
      - `obsidian search query="jira:"` for tickets
      - For backlinks of a specific page anchor: `obsidian backlinks file=<anchor>`
   c. Check Confluence pages and Jira tickets surfaced in (b) for updates since last sync (via the atlassian MCP tools).
   d. Search for new pages/tickets not yet in the KB (CQL/JQL via atlassian MCP).
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
