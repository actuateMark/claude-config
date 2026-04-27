# dashboard-check skill

Local static HTML operational dashboard — the forcing function for **regression prevention + fastest-possible detection, every launch**. See `SKILL.md` for the procedure contract, `/home/mork/.claude/plans/clever-tickling-swing.md` for the plan, and `topics/operational-health/notes/syntheses/2026-04-23_dashboard-sketch.md` for the design sketch.

## Directory layout

```
~/.claude/skills/dashboard-check/
├── SKILL.md              # procedure contract (Claude executes this step-by-step)
├── README.md             # this file
├── run.sh                # entry wrapper (ensures venv + dispatches)
├── render.py             # Python orchestrator: classify, regress, render, exit-code
├── sink.py               # stdlib helper; write_observation() + read_recent()
├── requirements.txt      # jinja2==3.1.*
├── config/
│   ├── signals.json      # signal catalog (~60 entries; enabled=true controls execution)
│   └── baselines.json    # static baselines (phase 1; rolling-window in phase 3)
├── render/
│   ├── index.html.j2     # top-level dashboard page
│   ├── component.html.j2 # per-component drill-down
│   ├── regressions.html.j2
│   └── macros.j2         # shared template bits (status badge, signal row)
├── css/
│   └── dashboard.css     # self-contained (inlined at render time)
├── tests/
│   └── test_signal_classification.py
└── .venv/                # created on first run; jinja2 lives here
```

Output:
```
~/Documents/worklog/dashboard/
├── latest -> 2026-04-23/
├── 2026-04-23/
│   ├── index.html
│   ├── data.json
│   ├── regressions.html
│   └── components/*.html
└── sink/
    ├── observations.jsonl  # append-only record of every check across all skills
    └── .schema.md
```

## Quick start

```bash
# one-off render against already-collected results in a tempdir
~/.claude/skills/dashboard-check/run.sh render \
  --tempdir /tmp/dashboard-xyz \
  --output-root ~/Documents/worklog/dashboard \
  --snapshot-date "$(date -u +%Y-%m-%d)"

# read recent sink entries
~/.claude/skills/dashboard-check/run.sh sink-recent 24

# write a sink observation (from another skill)
~/.claude/skills/dashboard-check/run.sh sink-write '{
  "component":"vms-connector","signal_id":"fleet_oomkills_24h",
  "value":423,"status":"red","source_skill":"daily-scope.fan-out",
  "notes":"4x baseline"
}'
```

For the full morning-routine invocation, use the Claude skill — trigger phrase `/dashboard-check` or "run dashboard". Claude executes the full `SKILL.md` procedure: preflight → NR MCP queries → CW/gh CLI bash → tempdir JSON → `run.sh render` → open.

## Phase 1a scope (this session — 2026-04-23)

Full plan in `/home/mork/.claude/plans/clever-tickling-swing.md`. Phase 1a delivers:
- Full ~60-signal catalog (most `enabled: false`; wired in 1b)
- Sink schema + helper
- Skill scaffold + Python orchestrator + Jinja templates + CSS
- One end-to-end signal wired: `onboarder_activity_us` × `onboarder_lambda_invocations_us` (Rule 5 anti-pattern — the canonical acceptance test against the 2026-04-23 incident)

Phase 1b (next session) enables the remaining ~19 signals + full drill-downs + `/daily-scope` integration + fan-out sink writes.

## Exit codes

- `0` — all enabled signals green. Launch verified.
- `1` — at least one yellow, no red. Follow-up required.
- `2` — at least one red. **Release skills BLOCK on this.**
