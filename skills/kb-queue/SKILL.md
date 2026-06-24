---
name: kb-queue
description: Batch-process a topic's reading list or the global dive queue with per-item approval (pause/resume). Trigger: '/kb-queue', 'process queue', 'batch ingest'.
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
  - AskUserQuestion
  - mcp__atlassian__getConfluencePage
  - mcp__atlassian__getJiraIssue
  - mcp__atlassian__searchConfluenceUsingCql
  - mcp__atlassian__searchJiraIssuesUsingJql
---

# KB Queue

Batch process sources from a topic's reading list or the global `_dive-queue.md`.

## Arguments

- `[topic]`: Process the reading list for a specific topic
- No args: Process the global `_dive-queue.md`

## KB Location

`/home/mork/Documents/worklog/knowledgebase/`

## Procedure

1. **Read the queue:**
   - If topic specified: read `topics/{topic}/reading-list.md`
   - If no topic: read `_dive-queue.md`
2. **For each unchecked item (`- [ ]`):**
   a. Show the item to the user and ask: Ingest / Skip / Stop
   b. If **Ingest:** Run the kb-ingest procedure (fetch, create source note, update topic notes)
   c. If **Skip:** Mark with `- [~]` (skipped) and continue
   d. If **Stop:** Save progress and exit
   e. After processing, mark with `- [x]` (done)
3. **Report:** How many items processed, skipped, remaining.

## Rules

- **Always ask before ingesting.** Show the source title and a one-line summary.
- **Save progress after each item.** If interrupted, the queue reflects what was processed.
- **Create reading-list.md if it doesn't exist** for a topic.
- **Follow all kb-ingest rules** for source note creation and topic updates.
