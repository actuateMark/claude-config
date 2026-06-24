---
name: kb-recap
description: Categorized recap of KB files created/modified in a date range. Groups by note type (source/concept/synthesis/entity/etc.) and topic. Trigger: '/kb-recap', 'kb recap', 'what did we write today'.
user-invocable: true
allowed-tools:
  - Bash
  - Read
  - Grep
  - Glob
---

# KB Recap

Mechanical categorizer for "which KB files changed in this date range, grouped by kind." Produces a structured markdown list. **Narrative is the caller's responsibility** — the skill tells you _what_ moved, not _why_.

Read-only. Never mutates the KB.

## Arguments

Positional:

- `(no args)` → today (00:00 → 23:59 local)
- `YYYY-MM-DD` → that specific day
- `YYYY-MM-DD..YYYY-MM-DD` → inclusive date range

Flags (additive):

- `--include-binaries` → include `.pdf` / `.png` / `.jpg` / `.webp` files (default: markdown + `.base` only)
- `--include-automated` → include jira-sync / overnight-check auto-generated files (default: excluded as noise)
- `--summary-only` → print only per-category counts + totals, not the file list
- `--bytes` → show size in bytes (default: KB rounded)

## Procedure

### Step 1 — Parse the date range

Compute start (epoch at 00:00 local of the start date) and end-exclusive (epoch at 00:00 local of the day after the end date). Default when no arg: today.

```bash
TODAY="${1:-$(date +%Y-%m-%d)}"
if [[ "$TODAY" == *..* ]]; then
  START="${TODAY%..*}"
  END="${TODAY#*..}"
else
  START="$TODAY"
  END="$TODAY"
fi
END_NEXT=$(date -I -d "$END + 1 day")
```

### Step 2 — Run the find

KB root: `/home/mork/Documents/worklog/knowledgebase/`.

```bash
KB=/home/mork/Documents/worklog/knowledgebase

find "$KB" \
  -newermt "$START 00:00" ! -newermt "$END_NEXT 00:00" \
  -type f \
  \( -name "*.md" -o -name "*.base" \) \
  ! -path "*/.obsidian/*" ! -path "*/.git/*" ! -path "*/.trash/*" \
  -printf '%T+ %s %p\n' 2>/dev/null | sort
```

If `--include-binaries`: add `-o -name "*.pdf" -o -name "*.png" -o -name "*.jpg" -o -name "*.webp"` to the `-name` group.

### Step 3 — Classify new vs edited (best-effort)

For each file, `stat --format='%W %Y %s %n' "$path"`:
- `%W` = birth-time epoch (0 if the filesystem doesn't support it; ext4 does)
- If birth-time is within the date range → **new** (✨)
- If birth-time is before the range → **edited** (✏️)
- If birth-time is 0 (unavailable) → **touched** (🔄, unknown)

### Step 4 — Categorize by path

Bucket each file into one category. First match wins.

| Path pattern (relative to KB root) | Category |
|---|---|
| `topics/personal-notes/notes/daily/*.md` | **Daily note** |
| `topics/personal-notes/notes/entities/mark-todos.md` | **Mark-todos** |
| `topics/*/sources/*.md` or `topics/*/*/sources/*.md` | **Source note** |
| `topics/*/notes/concepts/*.md` or `topics/*/*/notes/concepts/*.md` | **Concept note** |
| `topics/*/notes/syntheses/*.md` or `topics/*/*/notes/syntheses/*.md` | **Synthesis note** |
| `topics/*/notes/entities/*.md` or `topics/*/*/notes/entities/*.md` | **Entity note** |
| `topics/*/_summary.md` | **Topic summary** |
| `topics/*/reading-list.md` | **Reading list** |
| `topics/*/_pilot-*.md` or `topics/*/_staging-*.md` or `topics/*/_dive-queue.md` | **Staging / scratch** |
| `topics/operational-health/notes/syntheses/*_jira-sync.md` | **Automated — jira-sync** |
| `topics/operational-health/notes/syntheses/*_overnight-check.md` | **Automated — overnight-check** |
| `_research-inbox/*` | **Research inbox** |
| `_index.md` or other root-level files | **Top-level** |
| everything else | **Other** |

Within each bucket, sort alphabetically by topic then by filename.

Filter: if `--include-automated` is NOT set, drop the two Automated buckets from the output (but count them in the totals footer).

### Step 5 — Emit structured markdown

Exact format:

```
# KB Recap: {date or date..date}

## Source notes ({new-count} new, {edited-count} edited)

### {topic-1}
- ✨ `{relative-path}` ({size-kb} KB)
- ✏️ `{relative-path}` ({size-kb} KB)

### {topic-2}
- ✨ `{relative-path}` ({size-kb} KB)

## Concept notes (N new, M edited)
(same shape)

## Synthesis notes (N new, M edited)

## Entity updates (N)
- ✏️ `topics/personal-notes/notes/entities/mark-todos.md` ({size-kb} KB)

## Topic summaries touched (N)

## Reading lists touched (N)

## Daily notes (N)

## Staging / scratch (N)

## Research inbox (N)

## Top-level / other (N)

## Automated (N — excluded by default; pass --include-automated to show)

## Totals
- **{total}** KB files touched in {date-range}
- **{new-count}** new, **{edited-count}** edited, **{unknown-count}** touched (birth-time unavailable)
- **{total-bytes}** authored (sum across all listed files)
```

Empty categories are omitted (don't print "## Source notes (0 new, 0 edited)" if nothing landed there).

If `--summary-only`, print ONLY the header + a 1-line-per-category summary + totals. Skip the per-file listings.

### Step 6 — Return

Return exactly the structured markdown from Step 5. Do not add narrative. Do not speculate about which session wrote what. The caller (main agent, daily-wrap, etc.) will:

- Cross-reference against its own tool-call history to flag authored-by-me vs sibling-session
- Compare against `## Active Session Claims` block for cross-session attribution
- Add a day-arc narrative over the categorized list

## Integration points

**Inside `/daily-wrap` Step 1.5 (broader-day scan):**

The existing Step 1.5 KB-delta scan can delegate the file-listing to this skill. Daily-wrap then adds narrative + cross-session attribution on top. Replace the ad-hoc `find` with `/kb-recap` + classification annotations by the daily-wrap agent.

**Ad-hoc end-of-session:**

User asks "what did we write today?" → invoke `/kb-recap` directly. Main agent can wrap with a day-arc summary using its session context.

**Audit / pre-commit:**

If the KB ever moves to a git repo, `/kb-recap` output + `git diff --stat` together give a solid pre-commit review surface.

## Rules

- **Read-only.** Never mutates the KB.
- **No narrative.** Mechanical categorization only — the caller owns interpretation.
- **Default exclusions.** Automated-sync files, binaries, `.obsidian/.git/.trash` paths excluded by default.
- **Empty categories hide.** Don't emit zero-count sections; reduces noise.
- **Birth-time classification is best-effort.** ext4 supports it; other filesystems may not. Mark unknowns with 🔄 rather than guessing.

## Known limitations

- **Session-only scoping not supported.** The skill works by mtime, which is day-scoped at best. Session-start time isn't reliably discoverable from the shell.
- **Linter touches look like edits.** A file touched by Obsidian's linter (e.g., frontmatter `updated:` bump) is indistinguishable from a real edit in the output. The caller's session context is the only way to filter those.
- **Auto-sync patterns are hardcoded.** The Automated category matches `*_jira-sync.md` and `*_overnight-check.md` — add new patterns here if other auto-generators appear.

## Related

- [[skill-daily-wrap]] — primary consumer via Step 1.5's broader-day scan
- [[skill-recap]] — complementary "current state of tracked work" skill; focuses on scope/claims/tasks rather than KB deltas
- [[skill-kb-sync]] — the inverse direction (pull external → KB)
- [[skill-kb-lint]] — KB health check; can consume the recap output for a "what changed and is it valid?" audit
