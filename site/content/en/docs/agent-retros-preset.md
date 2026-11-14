---
title: "The agent-retros preset: retrospectives of agent work"
description: "Agent retrospectives: sessions, recurring patterns, environment improvements"
weight: 34
---

A ready-made preset for one notebook of retrospectives on your work with AI agents across all projects. A session
review becomes a pattern once it repeats, and a pattern becomes a concrete change to the agents' environment
(a skill, `CLAUDE.md`, an MCP tool, a hook) whose effect you then check.
File: [presets/agent-retros.yaml](https://github.com/justcrafter/okf-notebooks/blob/main/presets/agent-retros.yaml).

The [dev-project](/docs/dev-project-preset.md) preset has a `Retro` type too. Use that one for retros that belong to
one project; use this preset when you want to see how agents behave across projects.

## Enabling it

Point `config.yaml` at the presets directory (in Docker it sits next to the config, for example `/config/presets`):

```yaml
presets_dir: ./presets
```

Create the notebook:

```bash
uv run okf-notebooks notebook create agent-retros \
  --description "Retrospectives of work with AI agents: session reviews, recurring patterns, environment improvements" \
  --scope "Session reviews, patterns seen in 2+ sessions, changes to skills, CLAUDE.md and tools. Not the task's content or project decisions" \
  --preset agent-retros
```

## Types

| Type | Directory | What it holds | Required fields | `stale_after` |
|---|---|---|---|---|
| `Session` | `sessions/` | one session: task, outcome, what worked, problems, user corrections | `date`, `outcome` | — |
| `Pattern` | `patterns/` | a recurring anti-pattern or good practice with its signs, cause and sessions | `kind`, `sessions` | 180d |
| `Improvement` | `improvements/` | a change to the environment derived from a pattern, its state and effect | `target`, `state`, `pattern` | 90d |
| `Playbook` | `playbooks/` | how to keep the retros: writing a session, rolling up patterns, categories | — | 180d |

Values the types expect:

- `Session.outcome`: `success`, `partial`, `failed`, `abandoned`;
- `Pattern.kind`: `anti-pattern` or `practice`; `Pattern.state`: `observed`, `confirmed`, `addressed`, `gone`;
- `Improvement.target`: `skill`, `claude-md`, `preferences`, `mcp-tool`, `hook`, `check`;
  `Improvement.state`: `proposed`, `applied`, `verified`, `reverted`.

## How it works with agents

- The loop is session → pattern → improvement → effect. `Session.patterns`, `Pattern.sessions`,
  `Pattern.improvements` and `Improvement.pattern` link the steps, so each one can be traced back.
- A pattern needs two or more sessions. One bad session is a `Session` note, not a pattern.
- An `Improvement` ages in 90 days: by then later sessions should show whether it helped. Record what you saw in
  `effect` and move `state` to `verified` or `reverted`.
- Write the procedures as `Playbook` notes ("how to write a session review", "how to roll sessions up into
  patterns") and point the agent at them from `CLAUDE.md` / `AGENTS.md`, for example: "at the end of a long session
  write a review to the `agent-retros` notebook following its playbook".
- Keep the task itself out: what was built and decided goes into the project's notebook, the retro only links it.

## Making your own variant

Copy `presets/agent-retros.yaml`, rename it and adjust the types. The rules, the 12-type limit and the format are in
[presets.md](/docs/presets.md).
