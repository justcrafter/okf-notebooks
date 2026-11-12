# okf-notebooks

[Русская версия](../ru/glossary.md)

An MCP server that gives AI clients shared, git-backed notebooks of notes, with a human as the only authority on what is trusted.

## Language

### Identity

**Actor**:
The identity under which a change is made and the permission profile that bounds it. One of a fixed set; each is either an agent actor or the human.
_Avoid_: User, account, role

**Agent actor**:
An Actor identified by a Token (`claude-code`, `opencode`, `external-harness`).
_Avoid_: Agent (as a noun for the identity)

**Human**:
The Actor identified either by access to the host through the CLI or by a Human session in the Review UI; holds no Token and is the only Actor that can verify or archive.
_Avoid_: Operator, admin, owner

**Token**:
A credential bound to exactly one Agent actor, issued per machine or client and carrying a label.
_Avoid_: Key, API key, session

**Client**:
The program that connects with a Token, such as Claude Desktop or Claude Code. Distinct from the Actor: its version is recorded in authorship, but it does not determine permissions.
_Avoid_: Agent, harness (when meaning the program in general)

**Review UI**:
The browser interface served by the same process as the MCP endpoint, through which the Human reads notes, changes their status, and inspects their history. Disabled unless the Human password is set.
_Avoid_: Admin panel, dashboard, web app

**Human session**:
A cookie-backed login to the Review UI, obtained with the Human password. It acts as the Human and is never accepted by the MCP endpoint, just as a Token is never accepted by the Review UI.
_Avoid_: Login token, user session

**Human password**:
The single secret that opens a Human session, supplied by the `OKF_NOTEBOOKS_UI_PASSWORD` environment variable. Not a Token.
_Avoid_: Admin token, API key

**Revision**:
One git commit that touched a Concept's file, with its Actor and time; the Review UI shows a Concept's history as its Revisions and a diff of a Revision against its parent.
_Avoid_: Version, change

**Last revised**:
The time of a Concept's most recent Revision, whatever its Actor and including a status change by the Human. The Review UI orders a type's note list by it, newest first.
_Avoid_: Updated, modified, recent

**Links to**:
The in-notebook Concepts a Concept points at, through `/type/slug` references in its body or frontmatter. A link whose target does not exist is broken.
_Avoid_: Relations, connections, outgoing links

**Cited by**:
The Concepts that have the Concept in their Links to.
_Avoid_: Backlinks, references, incoming links

**Sources**:
The external or in-notebook references a Concept lists in its `sources` field as evidence for what it says. Not a Link to.
_Avoid_: Citations, references

**Tags**:
The free labels a Concept lists in its `tags` field; the Review UI filters a type's notes by one.
_Avoid_: Labels, categories

### Comments

**Thread**:
A discussion attached to a quoted passage of a Concept: a first Comment and the replies to it. It is open or resolved, and lives outside the Concept: it is not part of its body or frontmatter and creates no Revision.
_Avoid_: Conversation, annotation, review

**Comment**:
One message in a Thread, written by the Human or by an Agent actor.
_Avoid_: Note (a Note is a Concept), message, reply (a reply is a Comment that is not the first)

**Quote**:
The passage of a Concept's text a Thread was started on, kept with the Thread. The Review UI highlights it while it can still be found in the Concept.
_Avoid_: Selection, anchor, range

**Detached**:
A Thread whose Quote no longer occurs in its Concept. It stays readable with its Quote and stays visible to agents, but is not highlighted.
_Avoid_: Orphaned, stale, broken

**Mention**:
An `@` followed by an Actor name in a Comment, addressing that Agent actor. The Mentions of a Thread are those of all its Comments.
_Avoid_: Tag (a Tag labels a Concept), assignment

**Open / resolved**:
The state of a Thread. Agents are given open Threads unless they ask for resolved ones; the Human or an Agent actor addressed by the Thread can resolve and reopen it.
_Avoid_: Closed, done, status (that word belongs to Concepts)

## Relationships

- An **Actor** is either an **Agent actor** or the **Human**; there is exactly one **Human**.
- A **Token** belongs to one **Agent actor**; an **Agent actor** may have many **Tokens** (one per machine or **Client**).
- A **Client** connects with one **Token** and so acts as that token's **Agent actor**; Claude Desktop, for example, has no Actor of its own.
- Permissions attach to the **Actor**, never to the **Client** or the **Token**.
- A **Human session** is bound to the **Human**; it never carries a **Token** and a **Token** never opens one.
- A Concept's **Last revised** is the time of its latest **Revision**; a Concept with no Revision has none.
- A Concept's **Cited by** is derived from the other Concepts' **Links to**; it is never stored on the Concept itself.
- A **Thread** belongs to one Concept, never changes it, and is never part of its **Revisions**.
- A **Thread** is visible to an **Agent actor** when it is open and its **Mentions** are empty or include that Actor; the Agent actor then sees the whole Thread.
- A **Mention** names an **Actor**, never a **Token** or **Client**; every Token of that Actor is addressed.
- An **Agent actor** can use Threads only if its permissions include comments.
- The **Review UI** exists only while the **Human password** is set.
