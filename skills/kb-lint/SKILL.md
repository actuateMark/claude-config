---
name: kb-lint
description: KB health check — validates structure, finds broken wikilinks, orphan pages, missing frontmatter, stale content. Trigger: '/kb-lint', 'kb health'.
user-invocable: true
allowed-tools:
  - Read
  - Glob
  - Grep
  - Bash
---

# KB Lint

Structural health check for the Obsidian knowledge base.

## Arguments

- `[topic]`: Lint a specific topic only
- No args: Lint the entire KB

## KB Location

`/home/mork/Documents/worklog/knowledgebase/`

## Step 0 — Prefer the Obsidian CLI

Several of the lint checks below have direct CLI equivalents that return the answer in a single call (no recursive Glob/Grep). The CLI is at `~/.local/bin/obsidian` on both laptop and firebat.

| Check | CLI command | Replaces |
|---|---|---|
| Broken wikilinks (Check 3) | `obsidian unresolved` | Recursive scan of `[[...]]` references against filesystem |
| Orphan pages (Check 4) | `obsidian orphans` | Index-vs-filesystem cross-walk |
| Dead-end pages | `obsidian deadends` | (new check — pages with no outgoing links) |
| Tag inventory | `obsidian tags counts` | (new check — tags used 1× may be typos) |
| Vault stats | `obsidian vault` | File/folder/size counts |

Run a quick health probe first:

```bash
~/.local/bin/obsidian vault 2>&1 | head -1
```

If it succeeds, use the CLI commands. If it fails (Obsidian not running / socket missing / CLI not on PATH), fall back to the Read/Glob/Grep procedure for those checks and note the degradation in the report.

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
   - **Tag hygiene** (CLI-driven): `obsidian tags counts` — tags used exactly 1× across the whole vault are usually typos or one-offs; surface them for review. Tags that differ only in case or kebab-vs-snake (e.g. `#new-relic` vs `#newrelic`) are likely fragmentation; flag pairs.

3. **Broken wikilinks** (CLI: `obsidian unresolved`):
   - Each line is a target name that's referenced but doesn't exist as a file
   - Report each, plus the source files that reference it (use `obsidian backlinks file=<target>` to identify referrers if needed)

4. **Orphan pages** (CLI: `obsidian orphans`):
   - Files with no incoming wikilinks
   - Cross-check against `_index.md` listing — index-only references count

5. **Dead-end pages** (CLI: `obsidian deadends`):
   - Files with no outgoing wikilinks. Most concept/entity/synthesis notes should have at least one outgoing link; a dead-end suggests the note is missing connective tissue.
   - Exclude summaries (`_summary.md`) and source notes from this check — those legitimately may have no outgoing links.

6. **Stale content:**
   - Notes with `updated:` older than 30 days
   - `_checkpoint.md` last sync older than 7 days

7. **Source integrity:**
   - Source notes should not have been modified after creation (compare `ingested:` date with file mtime)

8. **Empty directories:**
   - Topic subdirectories with no content

## Output

Report organized by severity:
- **Errors:** Broken links, missing required frontmatter, structural violations
- **Warnings:** Stale content, orphan pages, dead-end pages, dubious tags, empty directories
- **Info:** Statistics (total topics, notes, sources, last sync date, total tags, top-10 tags by use)

## Rules

- **Report-by-default, autofix-on-request.** The underlying `~/bin/kb-lint` script supports `--fix` (dedup tag/list items in known list keys) and `--fix-orphan-bullets` (additionally drop orphan list bullets that are stale duplicates of an existing list block — legacy damage from the pre-2026-05-11 kb-incoming-refresh regex bug). Orphans that aren't drop-safe duplicates are left alone and reported. Use `--dry-run` to preview. Scheduled nightly on firebat (`kb-lint.timer`, ~04:00 UTC, after `kb-incoming-refresh`).
- **Be specific.** Report exact file paths and line numbers for issues.
- **Suggest fixes.** For each non-auto-fixable issue, suggest what action to take (e.g., "run `/kb-sync` to refresh", "run `/kb-relink --tags-only` to re-tag", "add to `_index.md`").
- **Prefer CLI over recursive scan.** When a check has a `obsidian` CLI equivalent listed in Step 0, use it. Recursive Grep/Glob is the fallback path, not the default.
