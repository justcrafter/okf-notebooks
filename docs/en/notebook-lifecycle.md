# Notebook and type lifecycle

[Русская версия](../ru/notebook-lifecycle.md)

Notebook states: `proposed` → `active` → `archived`; a rejected request goes to the archive with a reason (`rejected`).
A slug stays taken while the notebook exists in any state, the archive included.

## Creation policies

`notebook_creation.default` (can be overridden per actor in `actors.<name>.notebook_creation`):

| Policy | What the agent does |
|---|---|
| `off` | notebooks and types cannot be created |
| `proposal` (default) | creates a **request**, a human approves it |
| `direct` | the notebook or type is created immediately |

A human creates notebooks directly through the CLI, without the queue.

## An agent asks for a new notebook

The agent calls `notebook_create`:

- `slug`: `^[a-z][a-z0-9-]{1,38}[a-z0-9]$` (the pattern is set by `notebook_creation.slug_pattern`;
  `admin`, `tmp`, `archive`, `proposed` are reserved via `reserved_slugs`);
- `name` 3–80 characters, `description` 40–300, `scope`: what to write and what not to;
- `rationale`: why no existing notebook fits;
- `preset` **or** `types` (up to 12 types).

Before creating, the server looks for similar notebooks (name, description, `scope`). If it finds any, it returns a
`similar_exists` error with a list of candidates. The agent either uses an existing one or repeats the call with
`confirm_distinct: true` and explains the difference in `rationale`; the request is then marked `[confirm_distinct]`.

## A human works through the queue

```bash
uv run okf-notebooks notebook pending                       # requests for notebooks and types
uv run okf-notebooks notebook approve kube-platform         # moves to notebooks/, status active
uv run okf-notebooks notebook reject  kube-platform --reason "duplicates platform-ops"
```

The rejection reason is available to the author through `notebook_describe`. Requests live in `_proposed/`, the limit is 3 per actor.

## A new type in an existing notebook

The agent calls `notebook_type_define` (`notebook`, `name`, `description`, fields, `rationale`).
Under `proposal` a request is created:

```bash
uv run okf-notebooks type approve kube-platform Incident
uv run okf-notebooks type reject  kube-platform Incident --reason "…"
```

A human can also change the vocabulary directly:

```bash
uv run okf-notebooks type rename kube-platform Incident Outage
uv run okf-notebooks type delete kube-platform Outage
```

`rename` and `delete` refuse while the notebook still has notes of that type; `rename` does not rename the type's directory.
Types can be changed only in active notebooks. Options: `okf-notebooks type --help`.

## Archive and restore

```bash
uv run okf-notebooks notebook archive kube-platform    # to _archive/, the slug stays taken
uv run okf-notebooks notebook restore kube-platform
```

An archived notebook is absent from `notebooks_list` and search. `archive` is not available to agents.

## Limits

`limits.max_notebooks` counts active notebooks and pending requests together.
