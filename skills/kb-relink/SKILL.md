---
name: kb-relink
description: Wikilink + tag enrichment pass over the Obsidian KB — finds inline mentions and missing tags, adds them. Distinct from /kb-lint (broken links). Trigger: '/kb-relink', 'kb relink', 'enrich wikilinks'.
user-invocable: true
allowed-tools:
  - Read
  - Write
  - Edit
  - Glob
  - Grep
  - Bash
---

# KB Relink

Sweep the Obsidian KB at `/home/mork/Documents/worklog/knowledgebase/` for missing connective tissue:

1. **Missing wikilinks** — prose mentions an anchor term but doesn't `[[link]]` to it.
2. **Missing tags** — frontmatter doesn't declare a tag the prose / outgoing wikilinks imply.

**Distinct from `/kb-lint`:** kb-lint = BROKEN links + structural problems. kb-relink = MISSING links/tags (target exists, prose unlinked; rule exists, frontmatter missing tag).

## When to run

- Ad-hoc when you spot un-linked anchors in a recent note
- Cadence: `/loop weekly /kb-relink`
- After a synthesis batch (e.g. post-`/kb-synthesise`) before declaring a topic done

## Arguments

Positional (one of):
- *(none)* → full KB sweep
- Topic slug (`video-processing`, `vms-connector`) → `topics/<slug>/`
- Relative path (`topics/video-processing/notes/concepts/`) → that subdir

Mode flags (mutually exclusive; default `--apply`):
- `--dry-run` → don't edit; print proposed additions
- `--report-only` → write proposals to `_relink-report.md` at KB root; no edits
- `--apply` → edit in place

Pass scope (mutually exclusive opt-outs):
- `--links-only` → skip tag pass
- `--tags-only` → skip wikilink pass

Other:
- `--max-per-section N` → override once-per-`##`-section default for wikilinks (default 1)

## Execution: invoke the committed driver

```
~/.claude/skills/kb-relink/relink.py
```

This is the canonical path. **Do not re-implement logic per-invocation in `/tmp`** — historically that dropped 80% of files. The driver is deterministic; the SKILL.md describes WHAT, the script HOW.

```bash
# Default: dry-run, both passes, full KB
~/.claude/skills/kb-relink/relink.py

# Single topic
~/.claude/skills/kb-relink/relink.py new-relic --mode dry-run
~/.claude/skills/kb-relink/relink.py new-relic --mode apply

# Single pass
~/.claude/skills/kb-relink/relink.py new-relic --tags-only --mode dry-run
~/.claude/skills/kb-relink/relink.py new-relic --links-only --mode apply

# Markdown report
~/.claude/skills/kb-relink/relink.py new-relic --mode report-only
```

The driver loads `aliases.yaml` and `tag-rules.yaml` from this skill's dir, walks the KB to build the anchor + tag inventory, scans scoped files, applies edits with a YAML safety check, and emits a JSON summary to stdout. Resumption sidecar at `<KB>/_relink-progress.json` makes mid-run interrupts recoverable.

## Behavior summary (what the driver does)

**Scope exclusions** (always): `_*.md`, `README.md`, `reading-list.md`, `.obsidian/`, `.git/`, `.trash/`, `bases/`, `*.base`, `_research-inbox/`, `topics/personal-notes/notes/daily/*.md`, `topics/personal-notes/notes/entities/mark-todos.md`.

**Anchor inventory:** for every `.md` outside the exclusion list (and not a source note `topics/*/sources/*`, and with `type:` in frontmatter), collect: filename slug, `title:`, `aliases:`. Slug-heuristic (strip `-entity`/`-deep-dive`/`-overview`, split on `-`, re-case) adds common-noun forms like `PyAV` from `pyav-entity`. Synthesis anchors are **excluded from slug-heuristic** — only explicit `aliases:` contribute (slug components like `webrtc` are owned by more-specific anchors). `aliases.yaml` is the curated extension surface; `HARD_SKIP_PHRASES` blocks generics (`format, container, stream, frame, packet, protocol, model, video, audio, data, service, pipeline, system, library, api, client, server, agent, note, source, topic, layer, layers` + plurals).

**Tag inventory:** `tag-rules.yaml` is the authoritative rule file (any tag absent = never proposed; anti-hallucination). `obsidian tags counts` provides the canonical in-vault tag set for cross-checks.

**Safe zones** (never relink/tag-trigger inside): YAML frontmatter, fenced + indented code blocks, inline backticks, existing `[[...]]` (incl. aliased), markdown links `[text](url)`, bare URLs, paths, HTML/Obsidian comments, **markdown headings**.

**Wikilink rules:**
- Skip self-link (file's slug == anchor's slug)
- Skip if file's `title:` matches an anchor's display phrase (likely the anchor's own page)
- Word-boundary match (`\b<phrase>\b`); case-sensitive for proper-noun phrases (`PyAV`), case-insensitive for lowercase slugs
- **Reject hyphen-adjacent matches** (token next to `-` is inside a hyphenated identifier like `imageio-ffmpeg`)
- **Once per `##` section** by default (lead paragraph counts; `--max-per-section` overrides)
- Apply as aliased form `[[anchor-slug|original-phrase]]` (preserves prose surface) — un-aliased OK only if phrase exactly equals slug
- **Anti-hallucination** (Step 4.5): proposed `phrase` must be in the anchor's authorized `display_phrases`. Never link by subject-matter similarity. Rejections logged to the report.

**Tag rules:**
- Skip if tag already in file's `tags:` set
- **Phrase trigger:** count safe-zone matches of the tag's `phrases` ≥ `PHRASE_TRIGGER_MIN` (default 5; tuned up from 3 after over-fires on `#immix`, `#vms-connector`)
- **Anchor trigger:** count distinct slugs from the tag's `via_anchor:` in the file's outgoing-anchor set ≥ `VIA_ANCHOR_TRIGGER_MIN` (default 2; "linking to ONE entity ≠ topic centrality")
- Self-tag exemption: file's own slug appears in the tag's `via_anchor` → don't propose
- **Anti-hallucination** (Step 4.7): tag must have a key in `tag-rules.yaml`. Trigger must come from this tag's rule entry, not a sibling. No semantic adds (e.g. don't propose `#aws` because note mentions S3).
- Edit only the `tags:` field; preserve other frontmatter formatting; YAML re-parse check before save.

**Resumption:** `<KB>/_relink-progress.json` shape `{started, scope, completed_files: []}`. Append after each file. Discard if `scope` differs from current invocation. Delete on Step 7 success.

## Report format (Step 6)

```
# KB Relink Report -- {YYYY-MM-DD HH:MM}

Scope: {…}  Mode: {apply|dry-run|report-only}  Passes: {wikilinks + tags | links-only | tags-only}

## Summary
- Files scanned: N
- Files modified: M
- Wikilinks added: total
- Tags added: total                                 (omit if --links-only)
- Anchors with no candidates: K  (orphan)
- Tags with no candidates: Tk    (rule defined but never fired; omit if --links-only)
- Wikilink edits skipped (4.5): S  (phrase not in anchor's authorized display_phrases)
- Tag edits skipped (4.7): ST     (tag not in tag-rules.yaml)
- Resumed from prior run: bool

## Top anchors by wikilink additions
| Anchor | Additions | Sample phrase |

## Top tags by additions
| Tag | Additions | Trigger mix (P phrase / V via_anchor) |

## Per-file changes
### topics/<topic>/<file>.md (+N wikilinks, +M tags)
- L42: "PyAV" → [[pyav-entity|PyAV]]
- frontmatter tags: + #ffmpeg (via_anchor: ffmpeg-entity)

## Orphan anchors  (defined but never mentioned in scope)

## Skipped — wikilink anti-hallucination
- topics/.../foo.md L42: "VP9" → proposed [[webrtc-deep-dive]] but display_phrases is ["WebRTC"]; rejected

## Skipped — tag anti-hallucination
- topics/.../bar.md: proposed #aws (S3 mention); no rule for #aws; rejected

## Suggested rules to curate
(canonical-tag uses minus tag-rules.yaml keys, top 5):
- #integration (86), #worklog (49), #aws (49), #monitoring (25), #pipeline (17)
```

## Self-review (Step 7, before returning)

1. Verify no wikilink edit landed inside frontmatter / code fence / heading / existing wikilink. Revert + flag if so.
2. For each tag-edited file, re-parse frontmatter YAML. Revert + flag on parse failure.
3. `--apply` modified >50 files in one run → warn (suspicious).
4. Single anchor produced >20 additions in one file → flag (probably a too-generic alias slipped in).
5. Single tag added to >10 files → flag (rule too broad; tighten `phrases:`).

## Where edits go (driver vs rules)

| Symptom | Fix |
|---|---|
| Anchor/tag missed where it should have proposed | Add to `aliases.yaml` / `tag-rules.yaml`. No driver change. |
| New class of false positive (e.g. forgot a safe-zone) | Edit `relink.py` `find_unsafe_spans` / Step 4 sub-step 3. |
| Confidence thresholds wrong | Edit constants at top of `scan_file_tags` in `relink.py`. |
| New trigger type for tags (e.g. tag-overlap) | Extend `TagRule` + `scan_file_tags`; update `tag-rules.yaml` schema. |

## Obsidian CLI integration

Driver prefers `~/.local/bin/obsidian` over recursive Glob/Grep when available — single-call structured results vs N file reads:

| Step | CLI | Why |
|---|---|---|
| Tag inventory | `obsidian tags counts` | Canonical tag set in one call |
| Confirm tag exists | `obsidian tag name=<tag>` | Validate curated rule |
| Pre-filter linked files | `obsidian backlinks file=<anchor>` | Skip already-linked files for that anchor |
| Aliases supplement | `obsidian aliases verbose` | Second source of canonical phrases |

Health check: `~/.local/bin/obsidian vault 2>&1 | head -2` (prints name + path TSV). Fall through to filesystem scans on failure; note "CLI unavailable — used filesystem fallback" in the report.

## Tooling fallback (rg shadowing)

If Glob/Grep return ENOENT in `/home/mork/Documents/worklog/knowledgebase/`, the user's `rg` shell function may be shadowing ripgrep. Fall back to `find` + `grep -rn`:

```bash
find /home/mork/Documents/worklog/knowledgebase/topics/<topic>/notes/ -name '*.md' -type f
head -20 <file> | grep -E '^(title|aliases):'
grep -n -F 'PyAV' <file>
```

Read/Edit/Write are unaffected.

## Known limitations

- **Plurals/possessives.** `PyAV's`, `OpenCVs` not matched. Add to `aliases.yaml` if needed.
- **Compound phrases.** Longest match wins. Order phrases longest-first in `aliases.yaml` for precedence.
- **No semantic disambiguation.** Shared alias (`Frame` → two anchors) → first match wins; warns. Resolve in `aliases.yaml`.
- **Markdown tables.** Treated as prose; relinking works but may shift column widths. Spot-check.

## Rules

- **Never touch frontmatter (except `tags:`), code blocks, or existing wikilinks.**
- **Tag edits ONLY modify the `tags:` field.** Don't reorder/remove other keys or comments.
- **Never link to the anchor's own page.** No self-links, no self-tags.
- **First mention per `##` section only** (wikilinks). Tags are file-level.
- **Aliased form `[[slug|phrase]]`** preserves prose surface.
- **Curate via `aliases.yaml` and `tag-rules.yaml`**, not this SKILL.md.
- **Skip generic common nouns** (`HARD_SKIP_PHRASES`).
- **Skip source notes and daily notes/mark-todos.**

## Related

- [[skill-kb-lint]] — complementary; finds BROKEN wikilinks
- [[skill-kb-synthesise]] — often produces notes that benefit from a follow-up `/kb-relink` pass
- [[skill-kb-recap]] — combine: recap recent changes, relink only changed files via path scope
