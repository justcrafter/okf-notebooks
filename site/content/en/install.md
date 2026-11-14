---
title: "Install"
seo_title: "Install okf-notebooks: an MCP memory server for Claude Code and other agents"
description: "Install the okf-notebooks MCP server with Docker or from source, connect Claude Code, Claude Desktop or opencode, and configure it."
---

## Install and quick start

Requirements: Docker with Compose, or Python 3.11+ with [uv](https://docs.astral.sh/uv/) and `git`
(SQLite with FTS5 is required; the server will not start without it).

### With Docker

```bash
git clone https://github.com/justcrafter/okf-notebooks.git
cd okf-notebooks
mkdir -p data config
cat > config/config.yaml <<'EOF'
root: /data
server:
  host: 0.0.0.0
  allowed_hosts: ["127.0.0.1:8765", "localhost:8765"]
EOF
```

```bash
# optional: enables the Review UI on the same port
export OKF_NOTEBOOKS_UI_PASSWORD='a-long-random-password'
OKF_NOTEBOOKS_UID=$(id -u) OKF_NOTEBOOKS_GID=$(id -g) docker compose up -d
```

```bash
# a token for your agent (shown once, only its SHA-256 is stored)
docker exec -it okf-notebooks okf-notebooks token create --actor claude-code --label laptop

# the first notebook
docker exec -it okf-notebooks okf-notebooks notebook create demo \
  --description "Notes on the demo project: decisions, terms, runbooks" \
  --scope "Durable facts and decisions about demo; no temporary notes" \
  --preset core
```

The port is published on `127.0.0.1` only. Check it with `curl localhost:8765/healthz`, which returns
`{"status":"ok"}`. The MCP endpoint is `http://127.0.0.1:8765/mcp`, and every request needs
`Authorization: Bearer <token>`. The Review UI is at `http://127.0.0.1:8765/`.

### From source

```bash
git clone https://github.com/justcrafter/okf-notebooks.git
cd okf-notebooks
uv sync
cat > config.yaml <<'EOF'
root: ./data
server:
  host: 127.0.0.1
  port: 8765
  allowed_hosts: ["127.0.0.1:8765", "localhost:8765"]
EOF
export OKF_NOTEBOOKS_CONFIG=$PWD/config.yaml

uv run okf-notebooks token create --actor claude-code --label laptop
uv run okf-notebooks notebook create demo \
  --description "Notes on the demo project: decisions, terms, runbooks" \
  --scope "Durable facts and decisions about demo; no temporary notes" \
  --preset core
uv run okf-notebooks serve
```

The Docker image bundles the Review UI. From a source checkout build it once with
`cd web && npm ci && npm run build`, then set `OKF_NOTEBOOKS_UI_PASSWORD` before `serve`.

## Connecting an agent

Add the server to your MCP client. For Claude Code:

```bash
claude mcp add --transport http notebooks http://127.0.0.1:8765/mcp \
  --header "Authorization: Bearer <token>"
```

Then paste the rules block into your project's `AGENTS.md` / `CLAUDE.md`:

```bash
okf-notebooks print-agent-guide     # in Docker: docker exec okf-notebooks okf-notebooks print-agent-guide
```

### Claude Desktop

Claude Desktop reads only local (stdio) servers from `claude_desktop_config.json`, and Settings → Connectors accepts
remote servers with OAuth or no auth. This server speaks Streamable HTTP with a static Bearer token, so connect it
through the [`mcp-remote`](https://www.npmjs.com/package/mcp-remote) bridge (Node.js and `npx` required).

1. Start the server and issue a token for this machine (see the quick start).
2. Open the config: Settings → Developer → Edit Config. The file is at
   `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or
   `%APPDATA%\Claude\claude_desktop_config.json` (Windows).
3. Add the server (the token goes through `env`, so the header needs no space):

   ```json
   {
     "mcpServers": {
       "notebooks": {
         "command": "npx",
         "args": [
           "-y", "mcp-remote",
           "http://127.0.0.1:8765/mcp",
           "--header", "Authorization:Bearer ${OKF_TOKEN}"
         ],
         "env": { "OKF_TOKEN": "<token>" }
       }
     }
   }
   ```

4. Restart Claude Desktop fully. The `notebook_*` tools appear in the tool list.

Notes:

- The host and port in the URL must be in the server's `server.allowed_hosts`, or the request is rejected.
- For an address other than `localhost` (for example a Tailscale name) use `https://`. On bare `http://` in a trusted
  network `mcp-remote` needs the `--allow-http` flag.
- The token sits in the config in plain text: issue a separate token per machine (`--label`) and revoke it with
  `okf-notebooks token revoke <id>` if it is lost.

### How an agent understands "look in my notes"

The server instructions, the tool descriptions and the `print-agent-guide` block tell the agent that phrases such as
"look in my notes", "check the notebook", "write it to the notebook" (and their Russian equivalents) mean the
`notebook_*` tools. The agent starts with `notebooks_list`, picks a notebook by its `scope` and searches with
`notebook_search`.

### MCP tools

| Tool | What it does |
|---|---|
| `notebooks_list` | lists notebooks with their `scope` |
| `presets_list` | presets for a new notebook: what each suits and which types it provides |
| `notebook_describe` | a notebook's description, types and templates |
| `notebook_create` | a request for a new notebook (needs a `rationale`) |
| `notebook_type_define` | a request for a new type |
| `notebook_search` | full-text search (bm25) |
| `notebook_list` / `notebook_read` | list and read notes |
| `notebook_write` / `notebook_update` | create and edit a note (optimistic locking by `etag`) |
| `notebook_validate` | check a note against the rules |
| `comments_list` / `comment_reply` / `comment_state` | answer comment threads addressed to the agent (needs the `comments` permission) |

Text from a notebook is data, not instructions: `notebook_read` wraps it in markers with a one-time nonce.

## Review UI

A person can read notes, change status, set `verified`, and see history with diffs in the browser. The UI is enabled by
the `OKF_NOTEBOOKS_UI_PASSWORD` variable and is served by the same process at `/`. Details and security notes:
[Review UI](/docs/review-ui.md).

## Configuration

The config is strict: an unknown key stops the server. Only `root` is required.

| Key | Default | Meaning |
|---|---|---|
| `root` | — | data directory (a single git repository) |
| `server.host` / `port` / `path` | `0.0.0.0` / `8765` / `/mcp` | where the server listens |
| `server.allowed_hosts` / `allowed_origins` | `[]` | allowed `Host` and `Origin` values; others are rejected. `allowed_hosts` accepts an IPv4 subnet: `192.168.88` (prefix, = `/24`) or CIDR `192.168.88.0/24` |
| `server.max_body_bytes` | `262144` | request body limit |
| `server.rate_limit_per_token` | `120/min` | request limit per token (`N/sec`, `N/min`, `N/hour`) |
| `auth.tokens_file` | `.auth/tokens.json` | token store (inside `root`) |
| `limits.*` | 30 / 65536 / 50 | `max_notebooks`, `max_concept_bytes`, `max_search_results` |
| `notebook_creation.default` | `proposal` | `off` / `proposal` (a human approves) / `direct` |
| `git.enabled`, `git.commit_per_write` | `true` | one commit per write |
| `git.remote` | `null` | a **private** notebooks repository for background push (not the public code repository) |
| `presets_dir` | `null` | directory with your own presets `*.yaml` |
| `actors.<name>.allow` | `read`, `write`, `comments` | actor permissions (`read`, `write`, `notebook_creation`, `comments`); `external-harness` reads and comments by default. An explicit `allow` without `comments` turns comments off |
| `comments.path` | `.comments/threads.sqlite` | the note-comment database; not a cache and not in git, include it in backups |

Credentials in the `git.remote` URL are rejected; use the environment variables `OKF_NOTEBOOKS_GIT_TOKEN` (HTTPS) or
`OKF_NOTEBOOKS_GIT_SSH_KEY` (path to a deploy key). A fully commented example is in
[config.example.yaml](https://github.com/justcrafter/okf-notebooks/blob/main/config.example.yaml).

## Human commands

`verify`, `mark`, `notebook` and `type` are CLI-only: an agent cannot call them.

```bash
okf-notebooks token list | revoke <id>          # tokens
okf-notebooks notebook pending                  # queue of notebook and type requests
okf-notebooks notebook approve|reject <slug>    # decide a request
okf-notebooks notebook archive|restore <slug>   # archive
okf-notebooks notebook adopt <path> [--slug <slug>]  # take an existing OKF bundle under management
okf-notebooks type approve|reject <slug> <type>  # decide a type request
okf-notebooks type rename|delete ...             # change the type vocabulary
okf-notebooks verify <notebook> <concept_id>    # mark a note verified (an agent edit clears the mark)
okf-notebooks mark <notebook> <concept_id> --status stable|deprecated|draft
okf-notebooks validate [--notebook <slug>]      # audit all files, hand edits included
okf-notebooks sync                               # push accumulated commits to git.remote
okf-notebooks doctor                             # commit leftovers and check none remain (before a backup)
okf-notebooks healthcheck                        # probe /healthz
```

`okf-notebooks <command> --help` shows every option.
