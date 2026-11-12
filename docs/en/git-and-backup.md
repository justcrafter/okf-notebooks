# Git publishing and backup

[Русская версия](../ru/git-and-backup.md)

The `root` directory is a git repository, and the server is its only writer.

## Edit history

```yaml
git:
  enabled: true
  commit_per_write: true    # every agent write is a separate commit
```

The commit message carries the notebook, the action and the actor (`notebook(demo): … [claude-code/laptop]`).
Read the history with plain `git log` inside `root`.

## Publishing to a private repository

```yaml
git:
  remote: git@github.com:you/my-private-notebooks.git
```

Requirements:

- the repository is **private**; the server refuses to start with the public code repository
  (`okf-notebooks`, `mcp-okf-notebooks` and the URLs in `git.public_code_repos`);
- credentials in the URL are rejected; set them in the process environment instead:
  - `OKF_NOTEBOOKS_GIT_SSH_KEY`: path to a deploy key, or
  - `OKF_NOTEBOOKS_GIT_TOKEN`: a token for HTTPS.

Pushing happens in the background, fast-forward only and best effort: a failed push does not cancel the write.
To push what has accumulated by hand:

```bash
uv run okf-notebooks sync
```

A rejected non-fast-forward push means somebody else writes to that repository; sort it out manually.

## Before a backup

```bash
uv run okf-notebooks doctor
```

It commits leftovers (for example hand edits to files) and checks that the working tree is clean. Back up `root`
as a whole, `.git` included. The `.index/` directory can be rebuilt, tokens in `.auth/` are stored as SHA-256.
The comments database (`.comments/threads.sqlite`) is not in git and cannot be rebuilt, so it must be in the backup.

## Without git

`git.enabled: false` turns commits off; the backup is then a copy of the `root` directory.
