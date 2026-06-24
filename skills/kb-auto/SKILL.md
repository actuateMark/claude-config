---
name: kb-auto
description: Headless autonomous ingestion from the dive queue (_dive-queue.md). For scheduled/looped execution without user interaction. Trigger: '/kb-auto', 'auto ingest'.
user-invocable: true
allowed-tools:
  - Bash
  - Read
  - Write
  - Edit
  - Glob
  - Grep
  - Agent
  - WebFetch
  - mcp__atlassian__getConfluencePage
  - mcp__atlassian__getJiraIssue
  - mcp__atlassian__searchConfluenceUsingCql
  - mcp__atlassian__searchJiraIssuesUsingJql
  - mcp__atlassian__searchAtlassian
  - mcp__atlassian__getPagesInConfluenceSpace
---

# KB Auto

Headless autonomous ingestion from `_dive-queue.md`. Designed for scheduled or looped execution (e.g., `/loop /kb-auto`).

## Arguments

- `[topic]`: Only process queue items related to a specific topic
- No args: Process all unchecked items in `_dive-queue.md`

## KB Location

`/home/mork/Documents/worklog/knowledgebase/`

## Procedure

1. **Read `_dive-queue.md`** and find all unchecked items (`- [ ]`).
2. **For each item (up to 5 per run to stay within context limits):**
   a. Determine item type (Confluence space, Jira project, URL, topic keyword)
   b. **Fetch content:**
      - Confluence space: Use `getPagesInConfluenceSpace`, read key pages
      - Jira project: Search for open issues, read key tickets
      - URL: Use `WebFetch`
      - Topic: Search across Confluence + Jira
   c. **Determine target topic.** Create new topic if needed.
   d. **Create source notes** in `topics/{topic}/sources/`
   e. **Update or create concept/entity notes** in `topics/{topic}/notes/`
   f. **Update `_summary.md`** if needed
   g. **Mark item as done** (`- [x]`) in `_dive-queue.md`
3. **Update `_checkpoint.md`** with sync timestamp.
4. **Update `_index.md`** if new topics were created.
5. **Report:** Items processed, notes created/updated, items remaining.

## Rules

- **No user interaction.** This runs headless -- make all decisions autonomously.
- **Limit to 5 items per run** to avoid context overflow. Remaining items stay queued.
- **Follow all kb-ingest rules** for source note creation and topic updates.
- **Be conservative.** When unsure about topic assignment, create a note in the most general relevant topic.
- **Always set `author: kb-bot`** on all created/modified notes.
- **Never modify human-authored notes** (notes without `author: kb-bot`).
- **Log progress** in `_log.md` with date and what was processed.
