export type Status = "draft" | "stable" | "deprecated";

export interface Notebook {
  slug: string;
  name: string;
  description: string;
  scope: string;
  types: string[];
  note_count: number;
  last_modified: string | null;
  status: "active" | "proposed";
  author?: string;
  rationale?: string;
  proposed_at?: string;
}

export interface NoteItem {
  notebook: string;
  id: string;
  title: string;
  type: string;
  description: string;
  status: Status;
  stale: boolean;
  last_revised: string | null;
  tags: string[];
}

export interface TypeInfo {
  name: string;
  dir: string;
  description: string;
  fields: string[];
  count: number;
}

export interface NotebookTypes {
  slug: string;
  name: string;
  description: string;
  scope: string;
  status: string;
  note_count: number;
  types: TypeInfo[];
  top_tags: { tag: string; count: number }[];
}

export interface Ref {
  id: string;
  title: string | null;
  type: string | null;
  status: Status | null;
  broken: boolean;
}

export interface Relations {
  links_to: Ref[];
  cited_by: Ref[];
}

export interface Note {
  notebook: string;
  notebook_status: "active" | "proposed";
  id: string;
  frontmatter: Record<string, unknown>;
  body: string;
  etag: string;
  raw?: string;
  warnings?: string[];
}

export interface Revision {
  sha: string;
  actor: string;
  time: string;
  subject: string;
}

export interface History {
  available: boolean;
  revisions: Revision[];
}

export interface SessionInfo {
  authenticated: boolean;
  git: boolean;
}

export interface ConfigFile {
  path: string;
  content: string;
  truncated: boolean;
}

export interface CommentItem {
  id: number;
  parent_id: number | null;
  author: string;
  body: string;
  mentions: string[];
  created_at: string;
}

export interface Thread {
  id: number;
  notebook: string;
  concept: string;
  quote: string;
  prefix: string;
  suffix: string;
  state: "open" | "resolved";
  created_at: string;
  updated_at: string;
  mentions: string[];
  comments: CommentItem[];
}

export interface ThreadList {
  threads: Thread[];
  mentionable: string[];
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { credentials: "same-origin", ...init });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, (data as { error?: string }).error ?? res.statusText);
  return data as T;
}

const post = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

// Concept ids look like `/decisions/use-argo`; the API takes them as path segments.
const noteUrl = (nb: string, id: string) => `/api/notebooks/${encodeURIComponent(nb)}/notes${id}`;

export const api = {
  session: () => request<SessionInfo>("/api/session"),
  login: (password: string) => request<SessionInfo>("/api/login", post({ password })),
  logout: () => request<SessionInfo>("/api/logout", post({})),
  notebooks: () => request<Notebook[]>("/api/notebooks"),
  approve: (nb: string) => request<{ status: string; warnings: string[] }>(`/api/notebooks/${encodeURIComponent(nb)}/approve`, post({})),
  reject: (nb: string, reason: string) =>
    request<{ status: string; warnings: string[] }>(`/api/notebooks/${encodeURIComponent(nb)}/reject`, post({ reason })),
  config: (nb: string) => request<{ files: ConfigFile[] }>(`/api/notebooks/${encodeURIComponent(nb)}/config`),
  notes: (nb: string, status: Status[]) =>
    request<NoteItem[]>(`/api/notebooks/${encodeURIComponent(nb)}/notes?status=${status.join(",")}`),
  types: (nb: string) => request<NotebookTypes>(`/api/notebooks/${encodeURIComponent(nb)}/types`),
  relations: (nb: string, id: string) => request<Relations>(`${noteUrl(nb, id)}/relations`),
  note: (nb: string, id: string) => request<Note>(noteUrl(nb, id)),
  mark: (nb: string, id: string, body: { status?: Status; verify?: boolean }) =>
    request<Note>(`${noteUrl(nb, id)}/mark`, post(body)),
  history: (nb: string, id: string) => request<History>(`${noteUrl(nb, id)}/history`),
  threads: (nb: string, id: string) => request<ThreadList>(`${noteUrl(nb, id)}/threads`),
  createThread: (nb: string, id: string, body: { quote: string; prefix: string; suffix: string; body: string }) =>
    request<ThreadList>(`${noteUrl(nb, id)}/threads`, post(body)),
  reply: (thread: number, body: string, parent_id?: number) =>
    request<ThreadList>(`/api/threads/${thread}/comments`, post({ body, parent_id })),
  threadState: (thread: number, state: "open" | "resolved") =>
    request<ThreadList>(`/api/threads/${thread}/state`, post({ state })),
  deleteThread: (thread: number) => request<ThreadList>(`/api/threads/${thread}/delete`, post({})),
  diff: (nb: string, id: string, sha: string) => request<{ diff: string }>(`${noteUrl(nb, id)}/diff/${sha}`),
};
