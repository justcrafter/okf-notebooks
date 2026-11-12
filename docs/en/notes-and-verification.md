# Notes: writing, editing, verification

[Русская версия](../ru/notes-and-verification.md)

## Note format

Markdown with YAML frontmatter. Required fields: `type` (set by the server from the notebook's type), `title`,
`description` (one sentence, shown in search); the body must be at least 20 characters. Up to 10 tags (slug strings),
`links` (references to other notes of the notebook such as `/decisions/x.md`), `sources`, `stale_after`.
Fields listed in the notebook type's `required` are mandatory.

An agent cannot change `type`, `generated`, `status` or `verified`: the server or a human sets them.

## A note's life

1. An agent writes a note with `notebook_write`: status `draft`.
2. A human verifies and approves:

   ```bash
   uv run okf-notebooks verify kube-platform /decisions/use-argocd
   uv run okf-notebooks mark   kube-platform /decisions/use-argocd --status stable
   uv run okf-notebooks mark   kube-platform /decisions/old-way    --status deprecated
   ```

3. If an agent changes a verified note, `verified` is cleared and `stable` returns to `draft`
   (the response carries a `verified-reset` / `status-reset` warning). A `deprecated` note stays deprecated:
   that is a human decision.

By default search hides `deprecated` notes; request them explicitly with `status`.

## stale_after

A type can set an aging period (`stale_after: 180d`). The server puts it into a new note unless the author gave another.
An invalid value in a template raises a `stale-after` warning and does not break the type's record.

## Search and reading

- `notebook_search`: full text (bm25, Russian and English), filters: `notebook`, `types`, `tags`, `status`.
- `notebook_list`: a paged list with `cursor`.
- `notebook_read`: the body wrapped in nonce markers, plus the `etag`.

The index (`index.path`, `.index/fts.sqlite` by default) is rebuilt by the server; you can delete it and it will be recreated.

## Auditing hand edits

Files under `data/` can be edited by hand. To check that everything still follows the rules:

```bash
uv run okf-notebooks validate                 # all notebooks
uv run okf-notebooks validate --notebook demo
```

An agent checks a note without writing it through `notebook_validate`.
