#!/usr/bin/env python3
"""Curation logic for /repo-scan.

Reads cached gh issue JSONs, scores each issue, and emits:
1. The dated cross-repo scan note (top-5 x 2 buckets).
2. Per-repo concept files with an auto-refresh block (full inventory).

Preserves the hand-maintained "Curated notes" section of per-repo concept
files across re-runs via sentinel-based splicing.

Input: per-repo JSON files at /tmp/repo-scan-<repo>.json (populated by
the skill's Step 1 fetch). Can be overridden via --input-dir.

Usage:
    python3 curate.py [--input-dir /tmp] [--kb-root /home/mork/Documents/worklog/knowledgebase]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPOS = [
    "vms-connector",
    "actuate-libraries",
    "actuate-inference-api",
    "actuate_admin",
    "autopatrol_onboarder",
    "autopatrol-server",
    "camera-ui",
]

CURATED_HEADER = "## Curated notes"
AUTO_BEGIN = "<!-- BEGIN-AUTO-REFRESH repo-scan -->"
AUTO_END = "<!-- END-AUTO-REFRESH repo-scan -->"

NOW = datetime.now(timezone.utc)
TODAY = NOW.date().isoformat()


def iso_to_dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def days_since(s: str) -> int:
    return (NOW - iso_to_dt(s)).days


def label_matches(labels, pat):
    rx = re.compile(pat, re.I)
    return any(rx.search(l.get("name", "")) for l in labels)


def count_reactions(groups):
    return sum(g.get("users", {}).get("totalCount", 0) for g in (groups or []))


def score_high_impact(issue, include_assigned=False):
    s = 0
    labels = issue.get("labels", [])
    if label_matches(labels, r"^(p[01]|critical|high|priority|urgent)"):
        s += 5
    if label_matches(labels, r"^(bug|production|prod-issue|incident|regression)"):
        s += 3
    if label_matches(labels, r"^(security|sev[012])"):
        s += 4
    rxns = count_reactions(issue.get("reactionGroups"))
    s += min(rxns, 5)
    comments = issue.get("comments")
    if isinstance(comments, list):
        c_count = len(comments)
    elif isinstance(comments, int):
        c_count = comments
    else:
        c_count = 0
    s += min(c_count // 2, 4)
    d = days_since(issue["updatedAt"])
    if d <= 7:
        s += 2
    elif d <= 30:
        s += 1
    if issue.get("assignees") and not include_assigned:
        s -= 2
    body = issue.get("body") or ""
    if re.search(r"#\d{2,}", (issue["title"] or "") + " " + body):
        s += 2
    return s


def score_lhf(issue):
    s = 0
    labels = issue.get("labels", [])
    if label_matches(labels, r"^(good-first-issue|help-wanted|chore|docs?|documentation|refactor|test|cleanup)"):
        s += 5
    body = issue.get("body") or ""
    if len(body) > 100 and (re.search(r"- \[[ x]\]", body) or "Steps:" in body):
        s += 2
    if not issue.get("assignees"):
        s += 2
    title = issue.get("title") or ""
    if len(title) < 80:
        s += 1
    if days_since(issue["updatedAt"]) <= 60:
        s += 1
    if label_matches(labels, r"^(epic|complex|needs-design|spike)"):
        s -= 5
    if len(body) < 30:
        s -= 2
    return s


def label_str(labels):
    if not labels:
        return "—"
    return ", ".join(f"`{l['name']}`" for l in labels)


def assignee_str(assignees):
    if not assignees:
        return "—"
    return ", ".join(a.get("login", "?") for a in assignees)


def short_title(title, n=80):
    title = (title or "").strip()
    if len(title) <= n:
        return title.replace("|", "\\|")
    return (title[: n - 1] + "…").replace("|", "\\|")


def age_str(s):
    d = days_since(s)
    if d < 1:
        return "today"
    if d == 1:
        return "1d"
    if d < 30:
        return f"{d}d"
    if d < 365:
        return f"{d//30}mo"
    return f"{d//365}y"


def extract_curated_notes(existing: str) -> str | None:
    """Return the hand-maintained Curated notes body (between the `## Curated notes`
    heading and the AUTO_BEGIN sentinel) from an existing concept file, or None
    if the file is new or lacks the expected structure."""
    if CURATED_HEADER not in existing or AUTO_BEGIN not in existing:
        return None
    after_header = existing.split(CURATED_HEADER, 1)[1]
    before_sentinel = after_header.split(AUTO_BEGIN, 1)[0]
    return before_sentinel.strip("\n")


def build_concept(repo: str, issues: list, existing_curated: str | None) -> str:
    by_label: dict[str, int] = {}
    for issue in issues:
        for l in issue.get("labels") or []:
            by_label[l["name"]] = by_label.get(l["name"], 0) + 1

    high = sorted([i for i in issues if i["_high_score"] > 0], key=lambda x: -x["_high_score"])[:10]
    lhf = sorted([i for i in issues if i["_lhf_score"] > 0], key=lambda x: -x["_lhf_score"])[:10]
    stale = sorted([i for i in issues if i["_idle_days"] >= 180], key=lambda x: -x["_idle_days"])

    def nums(xs):
        return [i["number"] for i in xs]

    lines: list[str] = []
    lines.append("---")
    lines.append(f'title: "{repo} backlog"')
    lines.append("type: concept")
    lines.append("topic: repo-backlog")
    lines.append(f"tags: [backlog, github, {repo}]")
    lines.append(f"repo: aegissystems/{repo}")
    lines.append(f"created: {TODAY}")
    lines.append(f"updated: {TODAY}")
    lines.append("author: kb-bot")
    lines.append(f"issue_count_open: {len(issues)}")
    lines.append(f"issue_count_high_impact: {len(high)}")
    lines.append(f"issue_count_lhf: {len(lhf)}")
    lines.append(f"issue_count_stale: {len(stale)}")
    lines.append(f"high_impact_issue_numbers: {nums(high)}")
    lines.append(f"lhf_issue_numbers: {nums(lhf)}")
    lines.append(f"stale_issue_numbers: {nums(stale)}")
    lines.append(f"full_issue_numbers: {nums(issues)}")
    lines.append("---")
    lines.append("")
    lines.append(f"# {repo} backlog")
    lines.append("")
    lines.append(
        f"Full open-issue inventory for [aegissystems/{repo}]"
        f"(https://github.com/aegissystems/{repo}/issues). "
        "The auto-refresh block is overwritten by [[skill-repo-scan|/repo-scan]]; "
        "**Curated notes** are hand-maintained and preserved across refreshes."
    )
    lines.append("")
    lines.append(CURATED_HEADER)
    lines.append("")
    if existing_curated is not None and existing_curated.strip():
        lines.append(existing_curated.strip())
    else:
        lines.append("*(Free-form hand-maintained section. Themes, patterns, ownership "
                     "context, priority overrides, codebase-scan follow-up plans. Not "
                     "touched by /repo-scan.)*")
        lines.append("")
        lines.append("_(empty — populate on first curation pass)_")
    lines.append("")
    lines.append(AUTO_BEGIN)
    lines.append(f"_Last refreshed: **{TODAY}** by [[skill-repo-scan]] — {len(issues)} open issues._")
    lines.append("")

    lines.append("### 🔥 High-impact (top 10 by score)")
    lines.append("")
    if high:
        lines.append("| # | Title | Labels | Assignee | Score | Idle |")
        lines.append("|--:|-------|--------|----------|------:|------|")
        for i in high:
            lines.append(
                f"| {i['number']} | [{short_title(i['title'])}]({i['url']}) | "
                f"{label_str(i.get('labels'))} | {assignee_str(i.get('assignees'))} | "
                f"{i['_high_score']} | {age_str(i['updatedAt'])} |"
            )
    else:
        lines.append("_(no high-impact candidates — all scored ≤ 0)_")
    lines.append("")

    lines.append("### 🧹 Low-hanging fruit (top 10 by score)")
    lines.append("")
    if lhf:
        lines.append("| # | Title | Labels | Assignee | Score | Idle |")
        lines.append("|--:|-------|--------|----------|------:|------|")
        for i in lhf:
            lines.append(
                f"| {i['number']} | [{short_title(i['title'])}]({i['url']}) | "
                f"{label_str(i.get('labels'))} | {assignee_str(i.get('assignees'))} | "
                f"{i['_lhf_score']} | {age_str(i['updatedAt'])} |"
            )
    else:
        lines.append("_(no LHF candidates)_")
    lines.append("")

    lines.append("### 🔍 Codebase-scan follow-up candidates (idle >180d)")
    lines.append("")
    lines.append("*These are **not** bulk-close candidates — each needs case-by-case review. "
                 "Many may already be addressed by later work; some deserve a bump. "
                 "Walk the codebase for context before commenting.*")
    lines.append("")
    if stale:
        lines.append("| # | Title | Labels | Idle |")
        lines.append("|--:|-------|--------|------|")
        for i in stale[:15]:
            lines.append(
                f"| {i['number']} | [{short_title(i['title'])}]({i['url']}) | "
                f"{label_str(i.get('labels'))} | {i['_idle_days']}d |"
            )
        if len(stale) > 15:
            lines.append("")
            lines.append(
                f"_({len(stale) - 15} more stale issues — full list in "
                f"`stale_issue_numbers` frontmatter property.)_"
            )
    else:
        lines.append("_(none)_")
    lines.append("")

    lines.append("### 📊 Labels")
    lines.append("")
    if by_label:
        lines.append("| Label | Count |")
        lines.append("|-------|------:|")
        for name, cnt in sorted(by_label.items(), key=lambda x: -x[1]):
            lines.append(f"| `{name}` | {cnt} |")
    else:
        lines.append("_(no labeled issues)_")
    lines.append("")

    lines.append("### 🗃️ Full open inventory")
    lines.append("")
    lines.append(
        f"<details><summary>All {len(issues)} open issues "
        "(click to expand — sorted newest first)</summary>"
    )
    lines.append("")
    lines.append("| # | Title | Labels | Assignee | Age | Idle |")
    lines.append("|--:|-------|--------|----------|-----|------|")
    for i in sorted(issues, key=lambda x: -iso_to_dt(x["createdAt"]).timestamp()):
        lines.append(
            f"| {i['number']} | [{short_title(i['title'])}]({i['url']}) | "
            f"{label_str(i.get('labels'))} | {assignee_str(i.get('assignees'))} | "
            f"{age_str(i['createdAt'])} | {age_str(i['updatedAt'])} |"
        )
    lines.append("")
    lines.append("</details>")
    lines.append("")
    lines.append(AUTO_END)
    lines.append("")
    lines.append("## Related")
    lines.append("")
    lines.append("- [[repo-backlog/_summary|repo-backlog topic]]")
    lines.append(f"- Latest scan: [[{TODAY}_scan]]")
    lines.append(f"- GitHub: [aegissystems/{repo}/issues](https://github.com/aegissystems/{repo}/issues)")
    lines.append("")
    return "\n".join(lines)


def build_scan(all_issues: dict, totals: dict) -> str:
    flat = [i for issues in all_issues.values() for i in issues]
    high_top = sorted([i for i in flat if i["_high_score"] > 0],
                      key=lambda x: (-x["_high_score"], -days_since(x["updatedAt"])))[:5]
    lhf_top = sorted([i for i in flat if i["_lhf_score"] > 0],
                     key=lambda x: (-x["_lhf_score"], -days_since(x["updatedAt"])))[:5]

    lines = []
    lines.append("---")
    lines.append(f'title: "Repo Scan: {TODAY}"')
    lines.append("type: concept")
    lines.append("topic: repo-backlog")
    lines.append("tags: [scan, opportunities, github]")
    lines.append(f"created: {TODAY}")
    lines.append(f"updated: {TODAY}")
    lines.append("author: kb-bot")
    lines.append(f"total_issues: {sum(totals.values())}")
    lines.append("---")
    lines.append("")
    lines.append(f"# Repo Scan — {TODAY}")
    lines.append("")
    lines.append("Auto-generated by [[skill-repo-scan|/repo-scan]]. Snapshot at scan time — re-run for fresh data.")
    lines.append("")
    lines.append(f"**Repos surveyed:** {', '.join(REPOS)}")
    lines.append("**Time window:** all open issues (no --since filter; updated-timestamp informs score)")
    lines.append(f"**Total issues surveyed:** {sum(totals.values())}")
    lines.append(f"**Cache:** `~/.cache/repo-scan/{TODAY}.json`")
    lines.append("")
    lines.append("## Per-repo totals")
    lines.append("")
    lines.append("| Repo | Open | Catalog |")
    lines.append("|------|-----:|---------|")
    for repo in REPOS:
        t = totals.get(repo, 0)
        link = f"[[{repo}|catalog]]" if t > 0 else "—"
        lines.append(f"| {repo} | {t} | {link} |")
    lines.append("")
    lines.append("## 🔥 High Impact")
    lines.append("")
    lines.append("| Repo | # | Title | Labels | Assignee | Score |")
    lines.append("|------|--:|-------|--------|----------|------:|")
    for i in high_top:
        lines.append(
            f"| {i['_repo']} | {i['number']} | [{short_title(i['title'])}]({i['url']}) | "
            f"{label_str(i.get('labels'))} | {assignee_str(i.get('assignees'))} | {i['_high_score']} |"
        )
    lines.append("")
    lines.append("## 🧹 Low-Hanging Fruit")
    lines.append("")
    lines.append("| Repo | # | Title | Labels | Assignee | Score |")
    lines.append("|------|--:|-------|--------|----------|------:|")
    for i in lhf_top:
        lines.append(
            f"| {i['_repo']} | {i['number']} | [{short_title(i['title'])}]({i['url']}) | "
            f"{label_str(i.get('labels'))} | {assignee_str(i.get('assignees'))} | {i['_lhf_score']} |"
        )
    lines.append("")
    lines.append("## Picked Up")
    lines.append("")
    lines.append("*(Items promoted to [[mark-todos]] or otherwise acted on. Add rows manually or "
                 "via [[skill-todos-add|/todos-add]] when promoting a scan item.)*")
    lines.append("")
    lines.append("| Issue | Promoted to | Date |")
    lines.append("|-------|-------------|------|")
    lines.append("| *(none yet)* | | |")
    lines.append("")
    lines.append("## Related")
    lines.append("")
    lines.append("- [[skill-repo-scan]] — the skill that wrote this")
    lines.append("- [[repo-backlog/_summary|repo-backlog topic]]")
    lines.append("- [[mark-todos]] — destination for picked items")
    lines.append("")
    return "\n".join(lines), high_top, lhf_top


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-dir", default="/tmp", help="Directory with repo-scan-<repo>.json files")
    ap.add_argument("--kb-root", default=str(Path.home() / "Documents/worklog/knowledgebase"))
    args = ap.parse_args()

    kb_root = Path(args.kb_root) / "topics" / "repo-backlog"
    scans_dir = kb_root / "notes" / "scans"
    concepts_dir = kb_root / "notes" / "concepts"
    concepts_dir.mkdir(parents=True, exist_ok=True)
    scans_dir.mkdir(parents=True, exist_ok=True)

    all_issues: dict[str, list] = {}
    totals: dict[str, int] = {}

    for repo in REPOS:
        path = Path(args.input_dir) / f"repo-scan-{repo}.json"
        if not path.exists():
            print(f"SKIP (missing): {path}", file=sys.stderr)
            continue
        issues = json.loads(path.read_text())
        for issue in issues:
            issue["_repo"] = repo
            issue["_high_score"] = score_high_impact(issue)
            issue["_lhf_score"] = score_lhf(issue)
            issue["_age_days"] = days_since(issue["createdAt"])
            issue["_idle_days"] = days_since(issue["updatedAt"])
        all_issues[repo] = issues
        totals[repo] = len(issues)

    # cache
    cache = Path.home() / ".cache" / "repo-scan" / f"{TODAY}.json"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(all_issues, default=str, indent=2))

    # dated scan
    scan_text, high_top, lhf_top = build_scan(all_issues, totals)
    scan_path = scans_dir / f"{TODAY}_scan.md"
    scan_path.write_text(scan_text)
    print(f"WROTE: {scan_path}")

    # per-repo concepts
    for repo, issues in all_issues.items():
        if not issues:
            continue
        concept_path = concepts_dir / f"{repo}.md"
        existing = concept_path.read_text() if concept_path.exists() else ""
        curated = extract_curated_notes(existing) if existing else None
        content = build_concept(repo, issues, curated)
        concept_path.write_text(content)
        preserved = "preserved" if (curated and curated.strip() and "*(empty" not in curated and "*(Free-form" not in curated) else "fresh/empty"
        stale_n = sum(1 for i in issues if i["_idle_days"] >= 180)
        print(f"WROTE: {concept_path} ({len(issues)} issues, stale={stale_n}, curated={preserved})")

    # digest
    print(f"\nTotal: {sum(totals.values())} issues across {len([r for r,t in totals.items() if t>0])} repos")
    print("\n--- TOP-5 CROSS-REPO HIGH-IMPACT ---")
    for i in high_top:
        print(f"  [{i['_high_score']:2d}] {i['_repo']}#{i['number']} {short_title(i['title'], 70)}")
    print("\n--- TOP-5 CROSS-REPO LHF ---")
    for i in lhf_top:
        print(f"  [{i['_lhf_score']:2d}] {i['_repo']}#{i['number']} {short_title(i['title'], 70)}")


if __name__ == "__main__":
    main()
