---
title: "Documentation"
seo_title: "okf-notebooks documentation: notebook format, presets, agents, review"
description: "Reference for okf-notebooks: the OKF notebook format, type presets, several agents, notebook lifecycle, verification, network access, Review UI and git backup."
---

Reference pages by topic. Installation, quick start and the config reference are on the [Install](/install.md) page;
an example config with every option is in [config.example.yaml](https://github.com/justcrafter/okf-notebooks/blob/main/config.example.yaml).

| Scenario | When you need it |
|---|---|
| [Notebook format (OKF)](/docs/okf-format.md) | what a notebook looks like on disk |
| [Custom type presets](/docs/presets.md) | your notebooks need their own vocabulary of note types (ADR, Runbook, Incident…) |
| [The dev-project preset](/docs/dev-project-preset.md) | running a project: glossary, ADRs, specs, tickets, research, bugs |
| [The personal-finance preset](/docs/personal-finance-preset.md) | household money with an agent as a financial assistant: accounts, debts, budget, goals, investments, reports |
| [The agent-retros preset](/docs/agent-retros-preset.md) | retrospectives of agent work across projects: sessions, patterns, environment improvements |
| [Several agents](/docs/multi-agent.md) | Claude Code, opencode and others write to the same notebooks |
| [Notebook and type lifecycle](/docs/notebook-lifecycle.md) | an agent asks for a new notebook or type, a human decides |
| [Notes and verification](/docs/notes-and-verification.md) | writing, editing, `etag` conflicts, `verified`, `stale_after` |
| [Adopting an existing bundle](/docs/adopt-existing.md) | you already have an OKF directory of notes |
| [Network access and subnets](/docs/network-access.md) | the server is not on localhost: LAN, Tailscale, reverse proxy |
| [Review UI](/docs/review-ui.md) | a human reads and verifies notes and looks at diffs in the browser |
| [Git publishing and backup](/docs/git-and-backup.md) | edit history, push to a private repository, `doctor` |
| [Glossary](/docs/glossary.md) | the project's domain terms |

## Core model

- **Notebook**: a directory `notebooks/<slug>/` with Markdown notes and metadata in `.okf/notebook.yaml`.
- **Type**: a kind of note (`Decision`, `Playbook`…). Each type has a subdirectory, a set of frontmatter fields,
  required fields and an aging period `stale_after`.
- **Preset**: a ready-made set of types a notebook takes its vocabulary from at creation.
- **Actor**: who writes: `claude-code`, `opencode`, `external-harness` (by token) or `human` (CLI and Review UI only).
  Identity and permissions come from the token alone; an agent does not choose them.
- **Creation policy** (`off` / `proposal` / `direct`): whether an agent may create notebooks and types by itself.
