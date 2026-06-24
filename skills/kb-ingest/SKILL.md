---
name: kb-ingest
description: Ingest a source (URL, Confluence page, Jira ticket, or topic) into the Obsidian KB. Creates source notes, updates concepts/entities, refreshes topic summary. Trigger: '/kb-ingest', 'add to kb'.
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
---

# KB Ingest

Ingest a source (URL, Confluence page, Jira ticket, or research topic) into the Obsidian knowledge base at `/home/mork/Documents/worklog/knowledgebase/`.

## Arguments

- A Confluence URL or page ID: Fetches the page and creates a source note + updates topic notes
- A Jira ticket ID (e.g., `ENG-126`): Fetches the ticket and creates/updates entity notes
- A web URL: Fetches and distills content into the KB
- A topic name (e.g., "wireguard architecture"): Researches the topic across Confluence/Jira and populates the KB
- No args: Processes the next item from `_dive-queue.md`

## Procedure

1. **Read `_index.md`** to understand current KB state.
2. **Fetch the source content:**
   - Confluence: Use `mcp__atlassian__getConfluencePage` or search tools
   - Jira: Use `mcp__atlassian__getJiraIssue`
   - Web: Use `WebFetch`
   - Topic: Search Confluence + Jira across relevant spaces
3. **Determine the target topic.** If no matching topic exists, create one:
   - Create `topics/{slug}/` with `_summary.md` and subdirectories
   - Add to `_index.md`
4. **Create a source note** in `topics/{topic}/sources/`:
   - Filename: `{date}_{slug}.md` (e.g., `2026-04-13_ebus-phase1-prd.md`)
   - Include full frontmatter with `type: source`, `confluence:` or `jira:` link
   - Content: distilled summary of the source (not a full copy)
   - Sources are **immutable** after creation
5. **Update or create concept/entity notes** in `topics/{topic}/notes/`:
   - `concepts/` for ideas, patterns, techniques, decisions
   - `entities/` for people, services, repos, tools
   - `syntheses/` for cross-source analysis
   - Always set `author: kb-bot` and `updated:` date
   - Include `sources:` frontmatter listing which source notes informed the content
6. **Update `_summary.md`** if the new information changes the big picture.
7. **Update `_index.md`** if new topics or significant notes were added.
8. **Update `_checkpoint.md`** with sync timestamp.
9. **Report** what was ingested and what notes were created/updated.

## Frontmatter Templates

### Source Note
```yaml
---
title: "Source Title"
type: source
topic: topic-slug
tags: [tag1, tag2]
confluence: "https://..."  # or jira: "PROJ-123" or url: "https://..."
ingested: 2026-04-13
author: kb-bot
---
```

### Concept Note
```yaml
---
title: "Concept Name"
type: concept
topic: topic-slug
tags: [tag1, tag2]
sources: [source-file-1.md, source-file-2.md]
created: 2026-04-13
updated: 2026-04-13
author: kb-bot
---
```

### Entity Note
```yaml
---
title: "Entity Name"
type: entity
topic: topic-slug
tags: [tag1, tag2]
sources: [source-file.md]
created: 2026-04-13
updated: 2026-04-13
author: kb-bot
---
```

## Rules

- **Never edit existing source notes.** Create new source notes for updated information.
- **Never edit notes without `author: kb-bot`.** Those are human-authored.
- **Always cross-link** with `[[wikilinks]]` to related notes in other topics.
- **Keep summaries current.** If ingesting new info that changes the big picture, update `_summary.md`.
- **One source = one source note.** Don't merge multiple sources into one source note.
