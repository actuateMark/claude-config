---
name: kb-synthesise
description: Generate synthesis notes from accumulated sources in a topic. Cross-references source notes; presents a plan before writing. Trigger: '/kb-synthesise', 'synthesize topic'.
user-invocable: true
allowed-tools:
  - Read
  - Write
  - Edit
  - Glob
  - Grep
  - AskUserQuestion
---

# KB Synthesise

Generate concept, entity, and synthesis notes from accumulated source notes within a topic.

## Arguments

- `[topic]`: Synthesise notes for a specific topic
- No args: Scan all topics for source notes without corresponding synthesis notes

## KB Location

`/home/mork/Documents/worklog/knowledgebase/`

## Procedure

**CLI-first.** Health probe `~/.local/bin/obsidian vault 2>&1 | head -1`; if it succeeds, prefer the CLI to enumerate sources, find cross-source concept frequency, and check for existing coverage. Fall back to Glob/Grep only if the probe fails.

1. **Read `_index.md`** and the target topic's `_summary.md` (use `obsidian read path=...`).
2. **Enumerate source notes** in `topics/{topic}/sources/` — `obsidian files | grep "^topics/{topic}/sources/"` is one cheap call. Then read each via `obsidian read path=...` or Read.
3. **Check existing notes** in `topics/{topic}/notes/` to avoid duplication. For concept-by-concept duplication checks across the whole vault, prefer `obsidian search query="<concept name>"` over recursive Grep — it returns hit counts and file paths in one call.
4. **Identify synthesis opportunities:**
   - **Concepts** that appear across 2+ sources. `obsidian search query="<concept>"` gives frequency directly.
   - **Entities** (services, repos, people, tools) mentioned but not yet documented. Check existing coverage via `obsidian tag name=#<topic>` and `obsidian backlinks file=<entity-anchor>`.
   - **Syntheses** -- cross-source analysis, comparisons, architectural patterns
5. **Present a plan** to the user:
   - List proposed notes with type, title, and which sources inform them
   - Ask for approval before writing
6. **Write approved notes:**
   - Follow frontmatter conventions from `_schema.md`
   - Set `author: kb-bot`, `sources:` listing source files, `created:` and `updated:` dates
   - Use `[[wikilinks]]` to cross-reference related notes in other topics
   - **Concept threshold:** 1 source = stub (one sentence); 2+ sources = full article (500-1500 words)
7. **Update `_summary.md`** if synthesis reveals new insights.
8. **Report:** What was created, what sources were cross-referenced.

## Rules

- **Always present a plan first.** Don't write notes without user approval.
- **Never modify source notes.** Sources are immutable.
- **Never modify human-authored notes** (notes without `author: kb-bot`).
- **Cross-link aggressively.** Every synthesis note should link to related concepts and entities.
- **Cite sources.** Every claim should trace back to a source note via the `sources:` field.
