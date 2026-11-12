# Adopting an existing OKF bundle

[Русская версия](../ru/adopt-existing.md)

If you already have a directory of OKF notes (for example a project's `docs/` folder), you can bring it under management:

```bash
uv run okf-notebooks notebook adopt ~/code/myproject/docs --slug myproject
```

What the command does:

- copies the directory to `notebooks/<slug>/` (`.git` and `.obsidian` are skipped); the source is left untouched;
- creates `.okf/notebook.yaml` if it is missing;
- checks every file against the validator rules; on errors the notebook is **not created** and the violations are printed;
- makes a separate commit `notebook(<slug>): adopt bundle`.

Conditions: the slug matches `slug_pattern` and is neither taken nor reserved; the directory has no symbolic links;
`limits.max_notebooks` is not exceeded. Without `--slug` the directory name is used.

After adopting:

```bash
uv run okf-notebooks validate --notebook myproject
uv run okf-notebooks notebook pending     # no request is created: the notebook is active immediately
```

Fill in `description` and `scope` in `.okf/notebook.yaml`; without them an agent can hardly choose the notebook.
If the types used by the old notes differ from the notebook's vocabulary, fix them with `type rename` or add the missing ones.
