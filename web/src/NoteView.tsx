import { useEffect, useMemo, useRef, useState } from "react";
import { api, type Ref, type Status } from "./api";
import { CommentedArticle, CommentsPanel, useAnchors, type Open } from "./Comments";
import { parseDiff } from "./diff";
import { useT } from "./i18n";
import { useNb } from "./notebookData";
import { noteHref, notesHref } from "./route";
import { internalTarget, SafeMarkdown } from "./Safe";
import { headings, type Heading } from "./toc";
import { useAsync } from "./useAsync";

const STATUSES: Status[] = ["draft", "stable", "deprecated"];
const SHOWN_IN_PANELS = new Set(["title", "description", "tags", "sources", "status", "verified"]);
type Mode = "rendered" | "raw";

function initialMode(): Mode {
  try {
    return localStorage.getItem("okf-view") === "raw" ? "raw" : "rendered";
  } catch {
    return "rendered";
  }
}

const toList = (v: unknown): unknown[] => (Array.isArray(v) ? v : v == null || v === "" ? [] : [v]);
const show = (v: unknown) => (typeof v === "object" && v !== null ? JSON.stringify(v) : String(v));

function DiffView({ notebook, id, sha }: { notebook: string; id: string; sha: string }) {
  const t = useT();
  const d = useAsync(() => api.diff(notebook, id, sha), [notebook, id, sha]);
  if (d.loading) return <p>{t.loading}</p>;
  if (d.error) return <p className="error">{d.error.message}</p>;
  return (
    <pre className="diff" aria-label={t.diff}>
      {parseDiff(d.data?.diff ?? "").map((l, i) => (
        <div key={i} className={`dl ${l.kind}`}>{l.text || " "}</div>
      ))}
    </pre>
  );
}

function Panel({ title, count, children }: { title: string; count?: number; children: React.ReactNode }) {
  return (
    <section className="panel">
      <h3>
        {title}
        {count !== undefined && <span className="count">{count}</span>}
      </h3>
      {children}
    </section>
  );
}

function RefList({ items, notebook }: { items: Ref[]; notebook: string }) {
  const t = useT();
  if (!items.length) return <p className="muted">{t.none}</p>;
  return (
    <ul className="plain">
      {items.map((r) =>
        r.broken ? (
          <li key={r.id} className="broken" title={t.broken}>
            <code>{r.id}</code> <span className="muted">{t.broken}</span>
          </li>
        ) : (
          <li key={r.id}>
            <a href={noteHref(notebook, r.id)}>{r.title ?? r.id}</a>
            {r.status === "deprecated" && <span className="badge deprecated"> {t.deprecated}</span>}
          </li>
        ),
      )}
    </ul>
  );
}

function Source({ value, notebook }: { value: unknown; notebook: string }) {
  const s = show(value);
  if (/^https?:\/\//i.test(s)) return <a href={s} target="_blank" rel="noreferrer noopener">{s}</a>;
  const internal = internalTarget(s, notebook);
  return internal ? <a href={internal}>{s}</a> : <span>{s}</span>;
}

function Toc({ toc, active }: { toc: Heading[]; active: string | null }) {
  const t = useT();
  if (!toc.length) return null;
  return (
    <Panel title={t.onThisPage}>
      <ul className="plain toc">
        {toc.map((h) => (
          <li key={h.id} style={{ paddingLeft: (h.level - 1) * 12 }}>
            <a
              href={`#${h.id}`}
              className={h.id === active ? "active" : ""}
              onClick={(e) => {
                e.preventDefault();
                document.getElementById(h.id)?.scrollIntoView({ behavior: "smooth", block: "start" });
              }}
            >
              {h.text}
            </a>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

export function NoteView({ notebook, id, sha }: { notebook: string; id: string; sha?: string }) {
  const t = useT();
  const nb = useNb();
  const note = useAsync(() => api.note(notebook, id), [notebook, id]);
  const rel = useAsync(() => api.relations(notebook, id), [notebook, id]);
  const hist = useAsync(() => api.history(notebook, id), [notebook, id]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ warnings: string[] } | { error: string } | null>(null);
  const [mode, setMode] = useState<Mode>(initialMode);
  const [active, setActive] = useState<string | null>(null);
  const thr = useAsync(() => api.threads(notebook, id), [notebook, id]);
  const articleRef = useRef<HTMLElement>(null);
  const [openThread, setOpenThread] = useState<Open>(null);
  const body = note.data?.body ?? "";
  const threads = useMemo(() => thr.data?.threads ?? [], [thr.data]);
  const anchors = useAnchors(articleRef, threads, [mode, body, note.data?.etag]);
  const kit = { threads, mentionable: thr.data?.mentionable ?? [], anchors, open: openThread, setOpen: setOpenThread, reload: thr.reload };
  const toc = useMemo(() => headings(body), [body]);

  useEffect(() => {
    if (mode !== "rendered" || !toc.length || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(
      (entries) => {
        const hit = entries.find((e) => e.isIntersecting);
        if (hit) setActive(hit.target.id);
      },
      { rootMargin: "0px 0px -70% 0px" },
    );
    for (const h of toc) {
      const el = document.getElementById(h.id);
      if (el) io.observe(el);
    }
    return () => io.disconnect();
  }, [toc, mode, note.data?.etag]);

  const pick = (m: Mode) => {
    setMode(m);
    try {
      localStorage.setItem("okf-view", m);
    } catch {
      /* storage unavailable */
    }
  };

  const act = async (b: { status?: Status; verify?: boolean }) => {
    setBusy(true);
    setMsg(null);
    try {
      const res = await api.mark(notebook, id, b);
      setMsg({ warnings: res.warnings ?? [] });
      note.reload();
      hist.reload();
      nb.reload();
    } catch (e) {
      setMsg({ error: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  if (note.loading && !note.data) return <p>{t.loading}</p>;
  if (note.error || !note.data) return <p className="error">{note.error?.message}</p>;
  const fm = note.data.frontmatter;
  const status = String(fm.status ?? "draft") as Status;
  const type = String(fm.type ?? id.split("/")[1] ?? "");
  const tags = toList(fm.tags).map(String);
  const sources = toList(fm.sources);
  const rows = Object.entries(fm).filter(([k]) => !SHOWN_IN_PANELS.has(k));
  const readOnly = note.data.notebook_status === "proposed";

  return (
    <div className="doc">
      <div className="doc-main">
        <p className="crumbs">
          <a href={notesHref(notebook, undefined)}>{notebook}</a> / <a href={notesHref(notebook, type)}>{type}</a>{" "}
          <span className={`badge ${status}`}>{t[status]}</span>
        </p>
        <div className="doc-head">
          <h1>{String(fm.title ?? id)}</h1>
          <div className="seg" role="group" aria-label={t.viewMode}>
            {(["rendered", "raw"] as const).map((m) => (
              <button key={m} className={m === mode ? "active" : ""} aria-pressed={m === mode} onClick={() => pick(m)}>
                {t[m]}
              </button>
            ))}
          </div>
        </div>
        {!!fm.description && <p className="lead">{String(fm.description)}</p>}
        {!!tags.length && (
          <p className="chips">
            {tags.map((x) => (
              <a key={x} className="chip" href={notesHref(notebook, undefined, { tag: x })}>#{x}</a>
            ))}
          </p>
        )}
        {mode === "raw" ? (
          <pre className="file raw" aria-label={t.raw}>{note.data.raw ?? ""}</pre>
        ) : (
          <CommentedArticle innerRef={articleRef} kit={kit} notebook={notebook} id={id}>
            <SafeMarkdown text={body} notebook={notebook} toc={toc} />
          </CommentedArticle>
        )}
        <section className="history">
          <h3>{t.history}</h3>
          {hist.data && !hist.data.available && <p className="muted">{t.noHistory}</p>}
          {hist.data?.available && !hist.data.revisions.length && <p className="muted">{t.none}</p>}
          <ul className="list revs">
            {hist.data?.revisions.map((r) => (
              <li key={r.sha} className={r.sha === sha ? "sel" : ""}>
                <a href={noteHref(notebook, id, r.sha === sha ? undefined : r.sha)} aria-expanded={r.sha === sha}>
                  <code>{r.sha.slice(0, 7)}</code> {r.subject}
                  <div className="muted">{t.by} {r.actor} · {new Date(r.time).toLocaleString(t.locale)}</div>
                </a>
                {r.sha === sha && <DiffView notebook={notebook} id={id} sha={sha} />}
              </li>
            ))}
          </ul>
        </section>
      </div>
      <aside className="rail">
        {mode === "rendered" && <Toc toc={toc} active={active} />}
        {mode === "rendered" && <CommentsPanel kit={kit} />}
        <Panel title={t.linksTo} count={rel.data?.links_to.length}>
          {rel.data ? <RefList items={rel.data.links_to} notebook={notebook} /> : <p className="muted">{rel.error ? rel.error.message : t.loading}</p>}
        </Panel>
        <Panel title={t.citedBy} count={rel.data?.cited_by.length}>
          {rel.data ? <RefList items={rel.data.cited_by} notebook={notebook} /> : <p className="muted">{t.loading}</p>}
        </Panel>
        <Panel title={t.sources} count={sources.length}>
          {sources.length ? (
            <ul className="plain">
              {sources.map((s, i) => (
                <li key={i}><Source value={s} notebook={notebook} /></li>
              ))}
            </ul>
          ) : (
            <p className="muted">{t.none}</p>
          )}
        </Panel>
        <Panel title={t.tags} count={tags.length}>
          {tags.length ? (
            <p className="chips">
              {tags.map((x) => (
                <a key={x} className="chip" href={notesHref(notebook, undefined, { tag: x })}>#{x}</a>
              ))}
            </p>
          ) : (
            <p className="muted">{t.none}</p>
          )}
        </Panel>
        <Panel title={t.details}>
          <dl className="props">
            <dt>{t.conceptId}</dt>
            <dd><code>{id}</code></dd>
            {rows.map(([k, v]) => (
              <div key={k} className="prop">
                <dt>{k}</dt>
                <dd>{show(v)}</dd>
              </div>
            ))}
          </dl>
        </Panel>
        <Panel title={t.trust}>
          {readOnly ? (
            <p className="notice">{t.readOnly}</p>
          ) : (
            <div className="trust">
              <div className="seg" role="group" aria-label={t.status}>
                {STATUSES.map((s) => (
                  <button key={s} disabled={busy} className={s === status ? "active" : ""} aria-pressed={s === status} onClick={() => s !== status && void act({ status: s })}>
                    {t[s]}
                  </button>
                ))}
              </div>
              <button className="primary" disabled={busy} onClick={() => void act({ verify: true })}>
                {t.verify}
              </button>
            </div>
          )}
          <p className="muted">
            {t.verified}: {fm.verified ? String(fm.verified) : t.notVerified}
          </p>
          {!fm.verified && <p className="muted">{t.unverifiedHint}</p>}
          {msg && (
            <p className={"error" in msg ? "error" : "ok"} role="status">
              {"error" in msg ? msg.error : msg.warnings.length ? `${t.warnings}: ${msg.warnings.join("; ")}` : t.saved}
            </p>
          )}
        </Panel>
      </aside>
    </div>
  );
}
