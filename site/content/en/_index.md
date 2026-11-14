---
title: "okf-notebooks"
seo_title: "okf-notebooks: persistent memory for AI agents, an MCP server"
description: "Self-hosted MCP server that gives Claude Code, Claude Desktop and opencode persistent, shared memory: Markdown notebooks in the OKF format under git, verified by a human."

hero:
  eyebrow: "MCP server · self-hosted · MIT"
  title: "Memory for your agents that you can **read, diff and verify**"
  lead: "okf-notebooks is an MCP server that gives Claude Code, Claude Desktop, opencode and other MCP clients shared, persistent memory in the form of **notebooks**: plain directories of Markdown files in the [OKF](https://okf.md/) format under one git repository. A human reads and verifies what the agents wrote in a built-in web UI."
  meta: "One ASGI process, Streamable HTTP, no external database: search runs on SQLite FTS5."
  cta_install: "Get started"
  cta_github: "View on GitHub"
  image_alt: "Review UI: a note with its table of contents, links, tags and trust status"

idea:
  title: "The idea"
  lead: "Agents forget everything between sessions, and what they remember lives in a vendor's private store. okf-notebooks puts that memory where you can see and control it."
  items:
    - title: "Plain files"
      text: "Every note is a Markdown file with YAML frontmatter. Read it in any editor, diff it with git, revert a bad write with `git revert`, back it up with `git push`."
    - title: "Shared between agents"
      text: "Claude Code, opencode and an external harness read and write the same notebooks, each under its own token and permissions."
    - title: "A human decides what is trusted"
      text: "Everything an agent writes stays `draft`. Only a person can mark a note `verified`, `stable` or `deprecated`, and any later agent edit clears the mark."
    - title: "Safe by construction"
      text: "Identity and permissions come from the token alone; notebook text reaches the agent as data inside nonce markers; anything that looks like a secret is rejected on write."

how:
  title: "How it works"
  steps:
    - title: "Agents write"
      text: "Through MCP tools: search, read, write and update notes, with `etag` locking for concurrent agents."
    - title: "Git records"
      text: "One commit per write with the actor in the message, optional background push to a private remote."
    - title: "Notebooks stay typed"
      text: "Each notebook has a `scope` and a vocabulary of note types (`Decision`, `Playbook`…) with required fields and an aging period."
    - title: "A human reviews"
      text: "In the Review UI or the CLI: read, mark verified, browse diffs, answer comment threads, approve requests for new notebooks and types."

not:
  title: "What it is not"
  text: "Not a vector database, not a hosted service and not a multi-tenant system. It is a small self-hosted server for one person or one team that wants their agents' knowledge to stay in reviewable files."

screens:
  title: "Review UI"
  lead: "Opt-in and served by the same process: notes with links and backlinks, revision history with diffs, tables and Mermaid diagrams, comment threads that agents can answer."
  items:
    - src: "images/ui-notebook.png"
      alt: "Notebook overview"
    - src: "images/ui-comments.png"
      alt: "A comment thread on a passage"
    - src: "images/ui-type-dark.png"
      alt: "Type page in the dark theme"

quickstart:
  title: "Quick start"
  lead: "Requirements: Docker with Compose. Python 3.11+ with `uv` works too, see the [Install](/install/) page."
  more: "Full installation guide"
  steps:
    - title: "Configure"
      code: |
        git clone https://github.com/justcrafter/okf-notebooks.git
        cd okf-notebooks
        mkdir -p data config
        cat > config/config.yaml <<'EOF'
        root: /data
        server:
          host: 0.0.0.0
          allowed_hosts: ["127.0.0.1:8765", "localhost:8765"]
        EOF
    - title: "Run"
      text: "The password is optional and enables the Review UI on the same port."
      code: |
        export OKF_NOTEBOOKS_UI_PASSWORD='a-long-random-password'
        OKF_NOTEBOOKS_UID=$(id -u) OKF_NOTEBOOKS_GID=$(id -g) docker compose up -d
    - title: "Create a token and a notebook"
      code: |
        docker exec -it okf-notebooks okf-notebooks token create --actor claude-code --label laptop
        docker exec -it okf-notebooks okf-notebooks notebook create demo \
          --description "Notes on the demo project: decisions, terms, runbooks" \
          --scope "Durable facts and decisions about demo; no temporary notes" \
          --preset core
    - title: "Connect Claude Code"
      code: |
        claude mcp add --transport http notebooks http://127.0.0.1:8765/mcp \
          --header "Authorization: Bearer <token>"

scenarios:
  title: "What people use it for"
  more: "All scenarios"
  items:
    - anchor: "personal-memory"
      title: "Memory for one agent"
      text: "Claude Code keeps decisions, terms and runbooks between sessions, and you can open every note in an editor."
    - anchor: "project-knowledge"
      title: "A project knowledge base"
      text: "The `dev-project` preset: glossary, ADRs, specs, tickets, research and bugs in one notebook."
    - anchor: "multi-agent"
      title: "Several agents, one memory"
      text: "Claude Code writes, opencode extends, a CI harness only reads, each under its own token."
    - anchor: "human-review"
      title: "Human review"
      text: "Agents write drafts; a person verifies them, and an agent edit clears the mark."
    - anchor: "adopt-existing"
      title: "Notes you already have"
      text: "Bring an existing OKF directory, such as a project's docs folder, under management."
    - anchor: "network-and-backup"
      title: "Across machines, with backup"
      text: "Reach the server over LAN or Tailscale, push history to a private git remote."
---
