# Custom type presets

[Русская версия](../ru/presets.md)

A preset is a YAML file with a set of types. When a notebook is created it picks a preset (`--preset`) and gets its types.
There is one built-in preset, `core` (`Project`, `Decision`, `Playbook`, `Term`). It cannot be overridden.

## 1. Create a directory and point the config at it

```yaml
# config.yaml
presets_dir: ./presets
```

The directory is read on every access, no server restart needed. `*.yaml` / `*.yml` files are picked up.

## 2. Describe the preset

`presets/ops.yaml`:

```yaml
name: ops                       # optional: defaults to the file name without extension
description: Operations: incidents, runbooks, decisions
types:
  - name: Incident
    description: Incident review: timeline, cause, actions
    dir: incidents              # subdirectory; defaults to the plural slug of the type name
    fields: [description, tags, sources, stale_after, severity]
    required: [severity]        # fields without which a write is rejected
    stale_after: 365d
  - name: Runbook
    description: Step-by-step instructions for the on-call engineer
    dir: runbooks
    fields: [description, tags, sources, stale_after]
    stale_after: 90d
  - name: Decision
    description: A decision taken and the alternatives considered
```

**The preset's `description` answers "what is it for"**. The agent sees it in the `presets_list` tool and chooses a
preset for `notebook_create` by it, so say which notebooks the preset suits and which it does not ("Suited for …
Not for …"). Without a description the agent sees only the name and the types.

Accepted forms of `types`: a list of names (`- Decision`), a list of mappings (as above) or a mapping
`Name: {…}`. `required` and `stale_after` can be moved into a nested `template:`.

Rules:

- a type must have a description (for notebooks created with `types:` directly);
- type names and directories in a preset must not collide (two types in one directory is an error);
- a notebook has at most **12** types;
- `stale_after` is a period like `90d`; if it is invalid, the **whole preset is skipped** and a warning goes to the log;
- broken or empty YAML is skipped as well, the other presets stay available.

## 3. Create a notebook from the preset

```bash
uv run okf-notebooks notebook create runbooks \
  --description "Operations notes: incidents, runbooks and production decisions" \
  --scope "Durable operations knowledge; no drafts of incident reviews" \
  --preset ops
```

An agent over MCP does the same: it looks at the available presets with `presets_list`, then calls `notebook_create`
with `preset: "ops"` (under the `proposal` policy the request goes to the approval queue, see
[the lifecycle](notebook-lifecycle.md)).

The description is 40–300 characters, `scope` is required: the agent chooses a notebook by it.

## Types without a preset

A one-off set of types can be passed as a file (`--preset` and `--types-file` are mutually exclusive):

```bash
uv run okf-notebooks notebook create demo --description "…" --scope "…" --types-file types.yaml
```

`types.yaml` is a list of types in the same format as in a preset.

## What happens to a notebook when the preset changes

`notebook.yaml` of the notebook stores the type names and a reference to the preset. The description, fields and
`stale_after` that the notebook did not set itself are pulled from the preset on read. Editing the preset changes
those values in already created notebooks; it does not change the notebook's set of types. Adding and renaming
types in an existing notebook goes through `notebook_type_define` and `okf-notebooks type …`.
