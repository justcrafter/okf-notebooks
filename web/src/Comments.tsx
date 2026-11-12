import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { api, type CommentItem, type Thread, type ThreadList } from "./api";
import { buildIndex, completeMention, describeSelection, findQuote, mentionQuery, type Selected } from "./anchor";
import { useT } from "./i18n";

type Anchors = Map<number, Range | null>;
interface Point {
  x: number;
  y: number;
}
export type Open = { kind: "threads"; ids: number[]; at: Point } | { kind: "new"; sel: Selected; at: Point } | null;

// The CSS Custom Highlight API paints ranges without touching the DOM React owns.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const highlights = (): any => (typeof CSS !== "undefined" ? (CSS as any).highlights : undefined);

function caretAt(x: number, y: number): { node: Node; offset: number } | null {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const d = document as any;
  if (d.caretPositionFromPoint) {
    const p = d.caretPositionFromPoint(x, y);
    return p ? { node: p.offsetNode, offset: p.offset } : null;
  }
  if (d.caretRangeFromPoint) {
    const r = d.caretRangeFromPoint(x, y);
    return r ? { node: r.startContainer, offset: r.startOffset } : null;
  }
  return null;
}

// Finds every Thread's Quote in the rendered note (null = Detached) and highlights the open ones.
export function useAnchors(ref: RefObject<HTMLElement | null>, threads: Thread[], deps: unknown[]): Anchors {
  const [anchors, setAnchors] = useState<Anchors>(new Map());
  useLayoutEffect(() => {
    const root = ref.current;
    if (!root) {
      setAnchors(new Map());
      return;
    }
    const index = buildIndex(root);
    const found: Anchors = new Map(threads.map((t) => [t.id, findQuote(index, t.quote, t.prefix, t.suffix)]));
    setAnchors(found);
    const hl = highlights();
    const open = threads.filter((t) => t.state === "open").map((t) => found.get(t.id)).filter((r): r is Range => !!r);
    if (hl && typeof Highlight !== "undefined") {
      if (open.length) hl.set("okf-comment", new Highlight(...open));
      else hl.delete("okf-comment");
    }
    return () => hl?.delete("okf-comment");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [threads, ...deps]);
  return anchors;
}

function Tree({ items, parent, onReply, replyTo }: { items: CommentItem[]; parent: number | null; onReply: (c: CommentItem) => void; replyTo: number | undefined }) {
  const t = useT();
  const kids = items.filter((c) => c.parent_id === parent);
  if (!kids.length) return null;
  return (
    <ul className="cm-tree">
      {kids.map((c) => (
        <li key={c.id}>
          <div className="cm-meta">
            <span className="cm-author">{c.author}</span> · {new Date(c.created_at).toLocaleString(t.locale)}
          </div>
          <p className="cm-text">{c.body}</p>
          <div className="cm-actions">
            <button className={replyTo === c.id ? "active" : ""} onClick={() => onReply(c)}>{t.reply}</button>
          </div>
          <Tree items={items} parent={c.id} onReply={onReply} replyTo={replyTo} />
        </li>
      ))}
    </ul>
  );
}

function Compose({ mentionable, placeholder, submit, onCancel, label }: { mentionable: string[]; placeholder: string; label: string; submit: (text: string) => Promise<void>; onCancel?: () => void }) {
  const t = useT();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const q = mentionQuery(text);
  const names = q === null ? [] : mentionable.filter((n) => n.startsWith(q.toLowerCase()));
  const go = async () => {
    if (!text.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await submit(text);
      setText("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="cm-form">
      <textarea
        autoFocus
        aria-label={label}
        placeholder={placeholder}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void go();
        }}
      />
      {!!names.length && (
        <div className="cm-suggest" role="listbox">
          {names.map((n) => (
            <button key={n} role="option" aria-selected={false} onClick={() => setText(completeMention(text, n))}>@{n}</button>
          ))}
        </div>
      )}
      {error && <p className="error" role="alert">{error}</p>}
      <div className="cm-actions">
        <button className="primary" disabled={busy || !text.trim()} onClick={() => void go()}>{t.send}</button>
        {onCancel && <button onClick={onCancel}>{t.cancel}</button>}
      </div>
    </div>
  );
}

function ThreadView({ thread, mentionable, changed }: { thread: Thread; mentionable: string[]; changed: (l?: ThreadList) => void }) {
  const t = useT();
  const [parent, setParent] = useState<CommentItem | null>(null);
  const resolved = thread.state === "resolved";
  const flip = async () => changed(await api.threadState(thread.id, resolved ? "open" : "resolved"));
  const remove = async () => {
    if (!window.confirm(t.confirmDeleteThread)) return;
    changed(await api.deleteThread(thread.id));
  };
  return (
    <section className="cm-thread" aria-label={`${t.comments} #${thread.id}`}>
      <blockquote className="cm-quote">{thread.quote}</blockquote>
      <p className="cm-meta">
        {resolved && <span className="badge">{t.resolvedBadge}</span>} {thread.mentions.length ? thread.mentions.map((m) => `@${m}`).join(" ") : t.everyone}
      </p>
      <Tree items={thread.comments} parent={null} onReply={setParent} replyTo={parent?.id} />
      {parent && <p className="cm-meta">{t.replyingTo} {parent.author} <button className="cm-link" onClick={() => setParent(null)}>{t.cancel}</button></p>}
      <Compose
        key={thread.comments.length}
        mentionable={mentionable}
        label={t.reply}
        placeholder={t.commentPlaceholder}
        submit={async (text) => {
          changed(await api.reply(thread.id, text, parent?.id));
          setParent(null);
        }}
      />
      <div className="cm-actions">
        <button onClick={() => void flip()}>{resolved ? t.reopenThread : t.resolveThread}</button>
        <button className="danger" onClick={() => void remove()}>{t.deleteThread}</button>
      </div>
    </section>
  );
}

function Popover({ at, title, children, onClose }: { at: Point; title: string; children: ReactNode; onClose: () => void }) {
  const t = useT();
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const down = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    const key = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("mousedown", down);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("mousedown", down);
      document.removeEventListener("keydown", key);
    };
  }, [onClose]);
  const left = Math.max(8, Math.min(at.x, window.innerWidth - 376));
  const top = Math.max(8, Math.min(at.y + 14, window.innerHeight * 0.3));
  return (
    <div ref={ref} className="cm-pop" role="dialog" aria-label={title} style={{ left, top }}>
      <div className="cm-pop-head">
        <strong>{title}</strong>
        <button className="cm-link" aria-label={t.close} onClick={onClose}>✕</button>
      </div>
      {children}
    </div>
  );
}

export interface CommentsApi {
  threads: Thread[];
  mentionable: string[];
  anchors: Anchors;
  open: Open;
  setOpen: (o: Open) => void;
  reload: () => void;
}

// Wraps the rendered note: selecting text offers "Comment", clicking a highlight opens its threads.
export function CommentedArticle({ innerRef, kit, notebook, id, children }: { innerRef: RefObject<HTMLElement | null>; kit: CommentsApi; notebook: string; id: string; children: ReactNode }) {
  const t = useT();
  const [sel, setSel] = useState<Selected | null>(null);
  const { threads, mentionable, anchors, open, setOpen, reload } = kit;

  useEffect(() => {
    const onChange = () => {
      const root = innerRef.current;
      setSel(root ? describeSelection(root, window.getSelection()) : null);
    };
    document.addEventListener("selectionchange", onChange);
    return () => document.removeEventListener("selectionchange", onChange);
  }, [innerRef]);

  const onClick = (e: React.MouseEvent) => {
    if (window.getSelection()?.isCollapsed === false) return;
    const c = caretAt(e.clientX, e.clientY);
    if (!c) return;
    const ids = threads
      .filter((th) => th.state === "open" && anchors.get(th.id)?.isPointInRange(c.node, c.offset))
      .map((th) => th.id);
    if (ids.length) setOpen({ kind: "threads", ids, at: { x: e.clientX, y: e.clientY } });
  };

  const changed = useCallback(
    (list?: ThreadList) => {
      reload();
      void list;
    },
    [reload],
  );
  const close = useCallback(() => setOpen(null), [setOpen]);
  const shown = open?.kind === "threads" ? threads.filter((th) => open.ids.includes(th.id)) : [];

  return (
    <div className="cm-article">
      <article ref={innerRef} onClick={onClick}>{children}</article>
      {sel && !open && (
        <button
          className="primary cm-add"
          style={{ left: Math.max(8, Math.min(sel.rect.right, window.innerWidth - 120)), top: Math.max(8, sel.rect.bottom + 6) }}
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => setOpen({ kind: "new", sel, at: { x: sel.rect.left, y: sel.rect.bottom } })}
        >
          {t.addComment}
        </button>
      )}
      {open?.kind === "new" && (
        <Popover at={open.at} title={t.addComment} onClose={close}>
          <blockquote className="cm-quote">{open.sel.quote}</blockquote>
          <Compose
            mentionable={mentionable}
            label={t.addComment}
            placeholder={t.commentPlaceholder}
            onCancel={close}
            submit={async (text) => {
              await api.createThread(notebook, id, { quote: open.sel.quote, prefix: open.sel.prefix, suffix: open.sel.suffix, body: text });
              window.getSelection()?.removeAllRanges();
              setOpen(null);
              reload();
            }}
          />
        </Popover>
      )}
      {open?.kind === "threads" && (
        <Popover at={open.at} title={t.comments} onClose={close}>
          {shown.length ? shown.map((th) => <ThreadView key={th.id} thread={th} mentionable={mentionable} changed={changed} />) : <p className="muted">{t.noComments}</p>}
        </Popover>
      )}
    </div>
  );
}

// The rail: every thread of the note, including Detached and resolved ones.
export function CommentsPanel({ kit }: { kit: CommentsApi }) {
  const t = useT();
  const { threads, anchors, setOpen } = kit;
  const [resolved, setResolved] = useState(false);
  const list = threads.filter((th) => resolved || th.state === "open");
  const view = (th: Thread) => {
    const range = anchors.get(th.id);
    const rect = range?.getBoundingClientRect();
    if (rect && rect.height) window.scrollTo({ top: window.scrollY + rect.top - 120, behavior: "smooth" });
    setOpen({ kind: "threads", ids: [th.id], at: { x: Math.max(8, window.innerWidth - 700), y: 80 } });
  };
  return (
    <section className="panel">
      <h3>
        {t.comments}
        <span className="count">{threads.filter((th) => th.state === "open").length}</span>
      </h3>
      <label className="muted">
        <input type="checkbox" checked={resolved} onChange={(e) => setResolved(e.target.checked)} /> {t.showResolved}
      </label>
      {list.length ? (
        <ul className="plain cm-list">
          {list.map((th) => (
            <li key={th.id}>
              <button className={`cm-item ${th.state}`} onClick={() => view(th)}>
                <span>{th.quote.length > 80 ? th.quote.slice(0, 80) + "…" : th.quote}</span>
                <span className="cm-meta">
                  {th.comments[0]?.author} · {th.comments.length}
                  {th.state === "resolved" && ` · ${t.resolvedBadge}`}
                  {anchors.size > 0 && anchors.get(th.id) === null && ` · ${t.detached}`}
                </span>
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">{t.noComments}</p>
      )}
      <p className="muted">{t.commentsHint}</p>
    </section>
  );
}
