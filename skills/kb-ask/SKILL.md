---
name: kb-ask
description: Query the Obsidian KB across all topics/notes/sources. Trigger: '/kb-ask', 'check kb', 'what does the kb say'.
user-invocable: true
allowed-tools:
  - Read
  - Glob
  - Grep
  - Bash
---

# KB Ask

Search the Obsidian knowledge base at `/home/mork/Documents/worklog/knowledgebase/` to answer a question.

## Arguments

A natural language question, e.g.:
- "Who is working on the EBUS integration?"
- "What models are in production?"
- "What's the architecture of the vms-connector?"
- "What are the current risks?"

## Procedure

### Step 0 — Prefer the Obsidian CLI for vault-wide searches

The CLI at `~/.local/bin/obsidian` returns structured results in a single call instead of forcing N file reads. Probe with `~/.local/bin/obsidian vault 2>&1 | head -1` before relying on it.

| Goal | CLI command |
|---|---|
| Vault-wide phrase search | `obsidian search query="<phrase>"` |
| Phrase search w/ surrounding line context | `obsidian search:context query="<phrase>"` |
| All notes tagged with a topic | `obsidian tag name=#<topic>` |
| Backlinks to a known anchor | `obsidian backlinks file=<slug>` |

Tag-driven discovery (`obsidian tag name=#<topic>`) is usually the cheapest first move when the question maps to a topic — it returns the full file list without scanning bodies.

### Step 1 — Read `_index.md`

Understand KB structure and identify the relevant topics for the question.

### Step 2 — Read relevant `_summary.md` files

Start with topic summaries before diving into notes. They are cheap to read and often answer the question directly.

### Step 3 — Targeted search (if summaries don't suffice)

Prefer `obsidian search:context query="<key phrase>"` over recursive Grep — the CLI returns matches plus surrounding context in one call. If multiple candidate phrasings exist, use the most distinctive one (proper nouns, specific terms).

When the question maps to a tag, `obsidian tag name=#<topic>` returns the file list directly without searching bodies. Pair with `obsidian backlinks file=<anchor>` to find which notes reference an entity.

### Step 4 — Synthesize an answer

Pull the relevant content together. Cite specific KB notes.

### Step 5 — Cite sources & flag staleness

- **Sources:** Which KB notes informed the answer
- **Confluence/Jira links:** Direct links to source-of-truth pages
- **Staleness warning:** If notes are >2 weeks old, suggest `/kb-sync`

## Response Format

Answer concisely, then list sources + Confluence/Jira links + staleness flag.

## Rules

- **Read, don't write.** This skill only queries the KB; it does not modify it.
- **Prefer summaries.** Start with `_summary.md` files before diving into individual notes.
- **Prefer CLI over recursive Grep.** Tag/backlink lookups via `obsidian` are cheaper than scanning files.
- **Cross-reference.** If the answer spans multiple topics, read summaries from all relevant topics.
- **Be honest about gaps.** If the KB doesn't have the answer, say so and suggest what to ingest.
