---
name: kb-lint
description: Health check for the knowledge base. Validates structure, finds broken wikilinks, orphan pages, missing frontmatter, stale content, and contradictions. Trigger on "kb lint", "kb health", "check kb health", "validate kb", "kb check".
user-invocable: true
allowed-tools:
  - Read
  - Glob
  - Grep
---

# KB Lint

Structural health check for the Obsidian knowledge base.

## Arguments

- `[topic]`: Lint a specific topic only
- No args: Lint the entire KB

## KB Location

`/home/mork/Documents/worklog/knowledgebase/`

## Checks

1. **Structure validation:**
   - Every topic has `_summary.md`
   - Every topic has `sources/`, `notes/concepts/`, `notes/entities/`, `notes/syntheses/` directories
   - `_index.md` lists all topics
   - No orphan topic directories (in filesystem but not in `_index.md`)

2. **Frontmatter validation:**
   - Every `.md` file in topics/ has YAML frontmatter
   - Required fields present: `title`, `type`, `topic`, `author`
   - `type` is one of: `summary`, `source`, `concept`, `entity`, `synthesis`
   - `created` and `updated` dates are present
   - `sources:` field on concept/entity/synthesis notes references existing files

3. **Broken wikilinks:**
   - Scan all `[[wikilink]]` references
   - Report any that don't resolve to an existing file

4. **Orphan pages:**
   - Files not referenced by any wikilink or index entry

5. **Stale content:**
   - Notes with `updated:` older than 30 days
   - `_checkpoint.md` last sync older than 7 days

6. **Source integrity:**
   - Source notes should not have been modified after creation (compare `ingested:` date with file mtime)

7. **Empty directories:**
   - Topic subdirectories with no content

## Output

Report organized by severity:
- **Errors:** Broken links, missing required frontmatter, structural violations
- **Warnings:** Stale content, orphan pages, empty directories
- **Info:** Statistics (total topics, notes, sources, last sync date)

## Rules

- **Read-only.** This skill reports issues but does not fix them.
- **Be specific.** Report exact file paths and line numbers for issues.
- **Suggest fixes.** For each issue, suggest what action to take (e.g., "run /kb-sync to refresh", "add to _index.md").
