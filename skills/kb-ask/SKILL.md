---
name: kb-ask
description: Query the personal Obsidian knowledge base for information. Searches across all topics, notes, and sources to answer questions. Trigger on "kb ask", "check kb", "what does the kb say", "search kb", "look in kb", "knowledge base".
user-invocable: true
allowed-tools:
  - Read
  - Glob
  - Grep
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

1. **Read `_index.md`** to understand KB structure and find relevant topics.
2. **Read relevant `_summary.md` files** for the topics most likely to contain the answer.
3. **If the summary doesn't fully answer the question,** search for specific notes:
   - Use `Grep` to search note content across the KB
   - Use `Glob` to find notes by filename patterns
   - Read specific notes that match
4. **Synthesize an answer** from the KB content.
5. **Cite sources:** Reference the specific KB notes and their Confluence/Jira links.
6. **Flag staleness:** If the notes are older than 2 weeks, note that the information may be outdated and suggest running `/kb-sync` to refresh.

## Response Format

Answer the question concisely, then provide:
- **Sources:** Which KB notes informed the answer
- **Confluence/Jira links:** Direct links to source-of-truth pages
- **Staleness warning:** If relevant notes haven't been updated recently

## Rules

- **Read, don't write.** This skill only queries the KB; it does not modify it.
- **Prefer summaries.** Start with `_summary.md` files before diving into individual notes.
- **Cross-reference.** If the answer spans multiple topics, read summaries from all relevant topics.
- **Be honest about gaps.** If the KB doesn't have the answer, say so and suggest what to ingest.
