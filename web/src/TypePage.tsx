import { type Status } from "./api";
import { Decision } from "./Decision";
import { useT } from "./i18n";
import { ALL_STATUSES, useNb } from "./notebookData";
import { relativeTime, typeGroups } from "./notes";
import { noteHref, notesHref, type Route } from "./route";

const DEFAULT_SHOWN: Status[] = ["draft", "stable"];

type NotesRoute = Extract<Route, { page: "notes" }>;

function NotebookHome() {
  const t = useT();
  const { notebook, proposed, types, notes, reload } = useNb();
  const d = types.data;
  const groups = typeGroups(d?.types, notes.data ?? []);
  return (
    <>
      <h1>{d?.name ?? notebook}</h1>
      {proposed && (
        <>
          <p className="notice">{t.proposedHint}</p>
          <Decision
            notebook={notebook}
            onDecided={(approved) => {
              if (approved) reload();
              else window.location.hash = "#/";
            }}
          />
        </>
      )}
      {d?.description && <p className="lead">{d.description}</p>}
      {d?.scope && <p className="muted">{d.scope}</p>}
      <h2>{t.typesHeading}</h2>
      <ul className="cards">
        {groups.map((g) => {
          const info = d?.types.find((x) => x.name === g.name);
          return (
            <li key={g.name}>
              <a href={notesHref(notebook, g.name)}>
                <strong>{g.name}</strong> <span className="count">{g.items.length}</span>
                <div className="muted">{info?.description || t.noDescription}</div>
              </a>
            </li>
          );
        })}
      </ul>
      {!!d?.top_tags.length && (
        <>
          <h2>{t.topTags}</h2>
          <p className="chips">
            {d.top_tags.map((x) => (
              <a key={x.tag} className="chip" href={notesHref(notebook, undefined, { tag: x.tag })}>
                #{x.tag} <span className="count">{x.count}</span>
              </a>
            ))}
          </p>
        </>
      )}
    </>
  );
}

export function NotesPage({ route }: { route: NotesRoute }) {
  const t = useT();
  const { notebook, types, notes } = useNb();
  const { type, tag } = route;
  if (!type && !tag) return <NotebookHome />;
  const shown = route.status ?? DEFAULT_SHOWN;
  const info = types.data?.types.find((x) => x.name === type);
  const visible = (notes.data ?? []).filter(
    (n) => (!type || n.type === type) && shown.includes(n.status) && (!tag || n.tags.some((x) => x.toLowerCase() === tag.toLowerCase())),
  );
  const go = (status: Status[]) => {
    const same = status.length === DEFAULT_SHOWN.length && DEFAULT_SHOWN.every((s) => status.includes(s));
    window.location.hash = notesHref(notebook, type, { tag, status: same ? undefined : status });
  };
  const toggle = (s: Status) => go(ALL_STATUSES.filter((x) => (x === s ? !shown.includes(x) : shown.includes(x))));
  return (
    <>
      <h1>{type ?? t.allNotes}</h1>
      {type && <p className="lead">{info?.description || t.noDescription}</p>}
      {!!info?.fields.length && (
        <details className="schema">
          <summary>{t.schema}</summary>
          <p className="chips">
            {info.fields.map((f) => <code key={f}>{f}</code>)}
          </p>
        </details>
      )}
      <div className="filters">
        {ALL_STATUSES.map((s) => (
          <label key={s}>
            <input type="checkbox" checked={shown.includes(s)} onChange={() => toggle(s)} /> {t[s]}
          </label>
        ))}
        {tag && (
          <a className="chip active" href={notesHref(notebook, type, { status: route.status })} title={t.clearTag}>
            {t.tagFilter}: #{tag} ×
          </a>
        )}
      </div>
      {notes.loading && !notes.data && <p>{t.loading}</p>}
      {notes.error && <p className="error">{notes.error.message}</p>}
      {notes.data && !visible.length && <p>{t.noNotes}</p>}
      <ul className="list">
        {visible.map((n) => (
          <li key={n.id}>
            <a href={noteHref(notebook, n.id)}>
              <span className={`badge ${n.status}`}>{t[n.status]}</span> <strong>{n.title}</strong>
              {!type && <span className="muted"> {n.type}</span>}
              {n.stale && <span className="badge stale"> {t.stale}</span>}{" "}
              <span className="muted" title={n.last_revised ? new Date(n.last_revised).toLocaleString(t.locale) : t.notCommitted}>
                {n.last_revised ? relativeTime(n.last_revised, Date.now(), t.locale, t.justNow) : ""}
              </span>
              <div className="muted">{n.description}</div>
              {!!n.tags.length && <div className="muted tagline">{n.tags.map((x) => `#${x}`).join(" ")}</div>}
            </a>
          </li>
        ))}
      </ul>
    </>
  );
}
