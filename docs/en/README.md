# okf-notebooks documentation

[Русская версия](../ru/README.md)

Usage scenarios. Installation, quick start and the config reference are in the [root README](../../README.md);
an example config with every option is in [config.example.yaml](../../config.example.yaml).

| Scenario | When you need it |
|---|---|
| [Notebook format (OKF)](okf-format.md) | what a notebook looks like on disk |
| [Custom type presets](presets.md) | your notebooks need their own vocabulary of note types (ADR, Runbook, Incident…) |
| [The dev-project preset](dev-project-preset.md) | running a project: glossary, ADRs, specs, tickets, research, bugs |
| [Several agents](multi-agent.md) | Claude Code, opencode and others write to the same notebooks |
| [Notebook and type lifecycle](notebook-lifecycle.md) | an agent asks for a new notebook or type, a human decides |
| [Notes and verification](notes-and-verification.md) | writing, editing, `etag` conflicts, `verified`, `stale_after` |
| [Adopting an existing bundle](adopt-existing.md) | you already have an OKF directory of notes |
| [Network access and subnets](network-access.md) | the server is not on localhost: LAN, Tailscale, reverse proxy |
| [Review UI](review-ui.md) | a human reads and verifies notes and looks at diffs in the browser |
| [Git publishing and backup](git-and-backup.md) | edit history, push to a private repository, `doctor` |
| [Glossary](glossary.md) | the project's domain terms |

## Core model

- **Notebook**: a directory `notebooks/<slug>/` with Markdown notes and metadata in `.okf/notebook.yaml`.
- **Type**: a kind of note (`Decision`, `Playbook`…). Each type has a subdirectory, a set of frontmatter fields,
  required fields and an aging period `stale_after`.
- **Preset**: a ready-made set of types a notebook takes its vocabulary from at creation.
- **Actor**: who writes: `claude-code`, `opencode`, `external-harness` (by token) or `human` (CLI and Review UI only).
  Identity and permissions come from the token alone; an agent does not choose them.
- **Creation policy** (`off` / `proposal` / `direct`): whether an agent may create notebooks and types by itself.
