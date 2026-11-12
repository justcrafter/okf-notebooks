# Several agents in the same notebooks

[Русская версия](../ru/multi-agent.md)

A typical setup: Claude Code writes notes, opencode reads and extends them, an external harness (`external-harness`)
only reads, and a human verifies and approves.

## One token per agent

```bash
uv run okf-notebooks token create --actor claude-code      --label laptop
uv run okf-notebooks token create --actor opencode         --label workstation
uv run okf-notebooks token create --actor external-harness --label ci-reader
uv run okf-notebooks token list
uv run okf-notebooks token revoke t-1a2b3c4d
```

A token is shown once; only its SHA-256 is stored on disk. The actor and its permissions are determined **by the
token alone**: an agent cannot call itself a different actor. The label (`--label`) is written to the history, so
issue a separate token for each machine or client.

The `human` actor has no token: its actions are available only through the CLI (and the Review UI).

## Permissions

By default:

| Actor | Permissions |
|---|---|
| `claude-code`, `opencode` | `read`, `write`, `comments` |
| `external-harness` | `read`, `comments` |
| `human` (CLI) | everything, including `verify` and `archive` |

Override them in the config (allowed values: `read`, `write`, `notebook_creation`, `comments`):

```yaml
actors:
  claude-code:
    allow: [read, write, notebook_creation, comments]
    notebook_creation: direct    # this agent may create notebooks immediately
  opencode:
    allow: [read, write]
  external-harness:
    allow: [read]
```

Without `allow` an actor gets `comments` along with its other default permissions; an explicit `allow` without
`comments` turns comments off for that actor (see "Comments" in [review-ui.md](review-ui.md)). `verify` and `archive`
cannot be granted to an agent. The creation policy can be set globally (`notebook_creation.default`) and overridden
per actor. Write `off` as `off`; the server also understands a bare `off`, which YAML reads as `false`.

## What agents see

- All agents with `read` see active notebooks and notes.
- Other agents' requests (`proposed`) are not shown to other agents; even when looking for a similar notebook only
  the status is visible, not the content.
- The authorship mark `generated.by` (`<actor>/<client version>`) is set by the server; an agent does not edit it.
  The client version is taken from the MCP `initialize` request.

## Concurrent writes and conflicts

Writes run under file locks with atomic file replacement; each write is its own git commit with the actor and label
in the message (if `git.commit_per_write: true`).

- `notebook_write` creates a new note; the name is made unique, so another note cannot be overwritten.
- `notebook_update` with `body` or `fields` requires `base_etag`, the `etag` received from `notebook_read`.
  If the note was changed in the meantime, a `conflict` error with the current version comes back: the agent re-reads,
  merges its changes and retries.
- `notebook_update` with `append` needs no `etag`: appending to the end is safe under concurrent work.

Practice for two agents working on one note: logs and accumulated facts go through `append`, rewriting text goes
through `read` → `update` with `base_etag`.

## Limits and protection

- Request rate per token: `server.rate_limit_per_token` (`120/min`, also `N/sec`, `N/hour`).
- Request body size: `server.max_body_bytes`.
- At most **3** open requests per actor (notebooks and types together).
- `limits.max_notebooks`, `limits.max_concept_bytes`, `limits.max_search_results` bound the growth of the store.
- Note text is handed to the agent wrapped in markers with a one-time nonce, so content is not mistaken for instructions.
- Anything that looks like a secret (tokens, keys) cannot be written to a note: the write is rejected by the `secret` rule.

## Dividing responsibilities

1. One `scope` per notebook: agents choose a notebook by it, not by name.
2. Paste the block from `okf-notebooks print-agent-guide` into each project's `AGENTS.md` / `CLAUDE.md`.
3. A human reviews: after checking, a note gets `verified` (see [notes and verification](notes-and-verification.md)).
   Any edit by an agent clears the mark, so "verified" always refers to the current text.
