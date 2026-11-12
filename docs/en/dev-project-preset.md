# The `dev-project` preset: running a software project

[Русская версия](../ru/dev-project-preset.md)

A ready-made preset for a notebook where a team and its agents keep knowledge about a software project. Its types cover
the domain glossary and ADRs, specs and tickets, research, prototypes, bug diagnosis and retrospectives.
File: [presets/dev-project.yaml](../../presets/dev-project.yaml).

## Enabling it

Point `config.yaml` at the presets directory (in Docker it sits next to the config, for example `/config/presets`):

```yaml
presets_dir: ./presets
```

Create the notebook:

```bash
uv run okf-notebooks notebook create my-project \
  --description "my-project development: glossary, decisions (ADR), specs, tickets, research and bugs" \
  --scope "Durable project knowledge: terms, ADRs, specs, tickets, research, bugs. No personal notes" \
  --preset dev-project
```

The presets directory is read on every access, no restart needed. A preset whose YAML is broken is skipped silently
and `--preset dev-project` then reports "unknown preset": check the file with `yaml.safe_load`.

## Types

| Type | Directory | What it holds | Required fields | `stale_after` |
|---|---|---|---|---|
| `Project` | `projects/` | what the project is, how to run and test it | — | 180d |
| `Term` | `terms/` | a glossary entry: a definition without implementation details, `avoid` lists words to avoid | — | — |
| `Decision` | `decisions/` | an ADR: context, decision, alternatives, consequences | `decided` | — |
| `Spec` | `specs/` | a statement of work: problem, solution, user stories, out of scope | — | 365d |
| `Ticket` | `tickets/` | a task or bug with a brief and blocking tickets | `category`, `triage` | 90d |
| `Research` | `research/` | findings on a question, each fact linked to a primary source | `question` | 180d |
| `Prototype` | `prototypes/` | the question, what was built, what was learned, a verdict | `question` | 90d |
| `Bug` | `bugs/` | symptom, reproduction, cause, fix and regression test | `symptom` | — |
| `Retro` | `retros/` | a session retrospective: what slowed the agent down and what to change | — | — |
| `Playbook` | `playbooks/` | a repeatable procedure: release, deploy, setup | — | 180d |

`Ticket.triage` takes the roles `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`;
`category` is `bug` or `enhancement`.

## How it works with agents

- An agent finds the preset on its own: the `presets_list` tool returns the name, the description ("what it is for")
  and the types of every preset, this one included.
- `status` and `verified` are set by a human (Review UI or CLI): everything an agent writes stays `draft` until you
  verify it. That is why a ticket's state lives in `triage`, not in `status`.
- Aging by `stale_after` marks a note as `stale` in search: research and prototypes lose relevance quickly, ADRs
  and terms do not age on their own.
- Add a line to your project's `AGENTS.md` such as "write decisions, specs and research to the `my-project`
  notebook and choose the type from the type description in `notebook_describe`" (the rules block:
  `okf-notebooks print-agent-guide`).

## Making your own variant

Copy `presets/dev-project.yaml`, rename it and adjust the types. The rules, the 12-type limit and the format are in
[presets.md](presets.md).
