---
title: "Scenarios"
seo_title: "Use cases: memory for AI agents with okf-notebooks"
description: "Typical ways to use okf-notebooks, each with the steps to set it up and links to the reference pages."
---

Each scenario assumes the server is running and you have a token for your agent: see [Install](/install.md).

## Memory for one agent {#personal-memory}

**When:** you work with Claude Code (or another MCP client) and want it to remember decisions, terms and runbooks
between sessions, in files you can open yourself.

1. Create a notebook with the built-in `core` preset (`Project`, `Decision`, `Playbook`, `Term`). Give it a clear
   `scope`: the agent picks a notebook by what it is for, not by its name.
2. Connect the agent and paste the block from `okf-notebooks print-agent-guide` into your `CLAUDE.md` or `AGENTS.md`.
3. Ask in plain words: "look in my notes", "write it to the notebook". The agent starts with `notebooks_list`, picks
   the notebook by `scope` and searches with `notebook_search`.

Every note lands in `notebooks/<slug>/` as Markdown with frontmatter, one git commit per write.

Read more: [Notebook format (OKF)](/docs/okf-format.md), [Notes and verification](/docs/notes-and-verification.md).

## A project knowledge base {#project-knowledge}

**When:** a team and its agents keep knowledge about a software project: the domain glossary, ADRs, specs, tickets,
research, prototypes, bug diagnosis and retrospectives.

1. Point `presets_dir` in the config at the presets directory and create the notebook with `--preset dev-project`.
2. Agents write each kind of knowledge as its own note type with its own required fields and aging period.
3. Need your own vocabulary (Runbook, Incident…)? Write a preset as a YAML file; it is read on every access, no
   restart needed.

Read more: [The dev-project preset](/docs/dev-project-preset.md), [Custom type presets](/docs/presets.md).

## Several agents, one memory {#multi-agent}

**When:** Claude Code writes notes, opencode reads and extends them, an external harness (for example in CI) only
reads, and a human verifies and approves.

1. Issue one token per agent and machine: `token create --actor claude-code --label laptop`,
   `--actor opencode`, `--actor external-harness`. The actor and its permissions come from the token alone.
2. Adjust permissions in `actors.<name>.allow` if the defaults don't fit (`read`, `write`, `notebook_creation`,
   `comments`).
3. Concurrent edits are safe: `notebook_update` takes an `etag`, and a stale one is rejected instead of overwriting
   someone else's change.

Read more: [Several agents](/docs/multi-agent.md), [Notes and verification](/docs/notes-and-verification.md).

## Human review {#human-review}

**When:** you want to know which notes a person has actually checked.

1. Everything an agent writes is `draft`. A person marks a note `verified` (`okf-notebooks verify`) and sets its
   status to `stable` or `deprecated` (`okf-notebooks mark`), in the CLI or the Review UI.
2. If an agent later edits a verified note, the mark is cleared, so "verified" always refers to the current text.
3. In the Review UI you read notes, browse revision history with diffs and discuss a passage in comment threads that
   agents can answer.
4. Agents can ask for a new notebook or type; under the default `proposal` policy a human approves or rejects the
   request (`okf-notebooks notebook pending`).

Read more: [Review UI](/docs/review-ui.md), [Notebook and type lifecycle](/docs/notebook-lifecycle.md).

## Notes you already have {#adopt-existing}

**When:** you already have a directory of OKF notes, for example a project's docs folder.

1. Run `okf-notebooks notebook adopt <path> --slug <slug>`. The directory is copied into `notebooks/<slug>/`, the
   source is left untouched, and every file is validated; on errors the notebook is not created.
2. Fill in `description` and `scope` in `.okf/notebook.yaml` so agents can choose the notebook.

Read more: [Adopting an existing bundle](/docs/adopt-existing.md).

## Beyond code: finances and agent retros {#more-presets}

**When:** you want the same reviewable memory for something other than a codebase.

- [personal-finance](/docs/personal-finance-preset.md): an agent as a financial assistant for one household.
  Balances and market assumptions age in 30–90 days, so stale numbers are visible; the agent's proposals are kept
  apart from your decisions.
- [agent-retros](/docs/agent-retros-preset.md): one notebook of retrospectives across projects. Session reviews
  roll up into patterns, patterns into concrete changes to skills, `CLAUDE.md` and tools, and the effect is checked.

Both are YAML files in `presets/`: enable `presets_dir` and create the notebook with `--preset`. They are examples:
for anything else, design your own types or [ask an agent to propose them](/docs/presets.md#ask-an-agent).

## Across machines, with backup {#network-and-backup}

**When:** the server runs on a home server or a workstation and agents connect from other machines; you want the
notes' history off the box.

1. By default only loopback `Host` values are accepted. List your LAN or VPN subnets in `server.allowed_hosts`, or
   put the server behind a TLS reverse proxy. Never forward the port on your router.
2. Set `git.remote` to a **private** repository: commits are pushed in the background, `okf-notebooks sync` pushes
   on demand and `okf-notebooks doctor` checks nothing is left uncommitted before a backup.

Read more: [Network access](/docs/network-access.md), [Git publishing and backup](/docs/git-and-backup.md).
