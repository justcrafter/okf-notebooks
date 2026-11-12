# Review UI

[Русская версия](../ru/review-ui.md)

A browser interface for the **Human**: read notes, change their status (`draft` / `stable` / `deprecated`), set
`verified`, and look at the edit history and the diff of every revision. It runs in the same process and on the same
port as MCP.

## Enabling it

The UI is on only when the Human password is set in the environment (without it the routes `/` and `/api/*` answer 404):

```bash
export OKF_NOTEBOOKS_UI_PASSWORD='a-long-random-password'
uv run okf-notebooks serve
# open http://127.0.0.1:8765/
```

In Docker Compose the variable is passed through from the host environment: `OKF_NOTEBOOKS_UI_PASSWORD=... docker compose up -d`.

## Screen layout

Three areas:

- **Left**: a notebook switcher (requests carry a badge), a title filter and a tree: types with counters, and inside a
  type its notes alphabetically. Clicking a type opens the type page and expands its notes; the arrow only collapses
  and expands. At the bottom is a "Configuration" link.
- **Centre**: a notebook page (description, types, frequent tags), a type page (description, a collapsed "Type schema",
  status and tag filters, notes ordered by **Last revised**) or a note. A note can be viewed rendered or as Markdown:
  the second mode shows the whole file with its frontmatter; the choice is remembered in the browser. Below the note
  is the revision history; clicking a revision expands its diff.
- **Right** (when viewing a note): "On this page" (a table of contents from `#`–`###` headings), **Links to**,
  **Cited by**, **Sources**, **Tags**, the remaining frontmatter fields and a "Trust" block with the status and the
  verify button. Broken links are shown grey and do not navigate.

The address carries the filters: `#/n/<notebook>?type=Decision&tag=k8s&status=draft,stable`. On a narrow screen the
tree slides out from a menu button and the right panel moves under the note.

Cited by is computed when a note is opened, by scanning the notebook; the index was not changed for it.

## Tables and GFM

Markdown is parsed with the GFM extension ([remark-gfm](https://github.com/remarkjs/remark-gfm), MIT): tables,
strikethrough, task lists and footnotes. Raw HTML is still not rendered, including inside cells. A wide table scrolls
horizontally; footnote links scroll the page and do not change the address.

## Mermaid diagrams

A code block with the language `mermaid` is shown as a diagram; other code blocks are unchanged. The
[Mermaid](https://mermaid.js.org) library (npm `mermaid`, MIT) is loaded as separate files from your own origin only
when the first diagram appears, so notes without diagrams do not download it. The diagram theme follows the light or
dark UI theme. Mermaid runs with `securityLevel: "strict"`: note bodies are written by agents, and it lets no HTML in
labels and no `click` handlers through. If a diagram does not parse, its source and the parser message are shown.
In Markdown mode the block is plain text.

## Notebook requests

Notebooks in the `proposed` status are shown in a separate "Pending decision" section: the author, the rationale and
the notes the agent has already put in them. A request's notes are read-only (changing the status or verify returns 409).
A request can be approved or rejected right on the notebook page (both actions ask for confirmation; a reason is
required for rejection). This equals `okf-notebooks notebook approve|reject <slug>`: the notebook becomes active or goes
to `_archive/`, and the commit is made by `human`. Requests for new types are still decided in the CLI.

## Notebook configuration

The "Configuration" link at the bottom of the left panel opens a read-only view of the notebook's `.okf/`
(`notebook.yaml`, `okf-base.yaml`, type templates). Files are shown as plain text, symbolic links and files outside
`.okf/` are skipped, and a file is capped at 64 KB. It works for requests too.

## Security

- The password grants Human rights (verify, deprecate). It is not an agent token: the UI does not accept agent tokens
  and `/mcp` does not accept the password.
- The session is a signed cookie (`HttpOnly`, `SameSite=Strict`, 12 hours); changing the password ends all sessions.
  Sign-in is limited to 10 attempts per minute.
- State-changing requests require an `Origin` equal to `Host`. The `server.allowed_hosts` check applies to the UI too.
- Note bodies are written by agents, so Markdown is shown without raw HTML and images (Mermaid diagrams render in
  strict mode), and links are only `http(s)` and internal ones. UI responses carry a `Content-Security-Policy`.
- Outside loopback use TLS (Tailscale or a reverse proxy): the password travels over the network.

## History and diff

A revision is a git commit that touched the note's file (the author is the actor). The diff shows a commit against its
parent. With `git.enabled: false` or `git.commit_per_write: false` there is no history, and the UI says so.

## Look and themes

The style builds on Miro's open design system [Mirotone](https://mirotone.xyz) (MIT): blue accent, grey scales,
4/6/8 px radii, focus ring, segmented switch. The Open Sans font is bundled locally (`@fontsource/open-sans`, OFL);
there are no external resources, which the CSP requires. Mirotone has no dark theme, so the dark colours are built on
the same scales. The default theme follows the system, a header button switches light and dark, and the choice is
remembered in the browser. Colours are defined as tokens at the top of `web/src/style.css`.

## Development

```bash
cd web && npm ci
npm run dev        # Vite on :5173, /api is proxied to 127.0.0.1:8765
npm test           # vitest
npm run build      # builds into src/okf_notebooks/webui_dist (the wheel packages it)
```

The Docker image builds the UI in a separate Node stage; Node is not needed at runtime.

## Comments

Select text in a rendered note and press "Comment": this starts a **thread**. Places with threads are highlighted in
pale yellow; clicking a highlight opens a popup with the reply tree. In the popup you can reply (the "Reply" button
on a comment chooses the branch), close the thread ("Resolved"), reopen it or delete it entirely. Resolved threads are
not highlighted; the list of all of a note's threads, resolved ones included, is in the "Comments" panel on the right.

- Comments are not part of the note: its body and frontmatter do not change and no revisions are created.
- A Human reply in a resolved thread reopens it; an agent reply does not change the state. A comment cannot be edited,
  a thread is deleted as a whole.
- `@claude-code` in a comment calls the agent (an actor name, not a token label). Only actors with the `comments`
  permission are suggested; the server rejects any other name. A thread without `@` is visible to all agents, with `@`
  only to the named ones (mentions of all comments in the thread add up).
- If an agent rewrites the selected passage, the thread is marked "text changed": it stays in the panel with its quote
  but is not highlighted.
- Text can be selected only in the "Rendered" mode, not in Markdown. Highlighting uses the CSS Custom Highlight API
  (Chrome 105+, Safari 17.2+, Firefox 140+); in an older browser threads are visible in the panel without highlights.
- The data lives in `comments.path` (`.comments/threads.sqlite` in the data root). It is not a cache and does not go
  to git, so include the file in your backup.

### Comments for agents

The `comments` permission in `actors.<name>.allow` opens three MCP tools:

| Tool | What it does |
| --- | --- |
| `comments_list` | Threads addressed to the agent (open by default; `state: resolved\|all`, filters by `notebook` and `id`): the quote, the note `id` and the `resource` to read, and the comment tree. |
| `comment_reply` | A reply in a thread (`thread_id`, `body`, optional `parent_id`). |
| `comment_state` | `resolved` closes the thread, `open` reopens it. |

An agent does not create or delete threads. Comment texts arrive as data, not as instructions. Without the `comments`
permission (an explicit `allow` lacking it) the tools answer `forbidden`.
