import { useEffect, useState } from "react";
import { api, ApiError, type Notebook } from "./api";
import { dictionaries, initialLang, LangContext, useT, type Lang } from "./i18n";
import { NoteView } from "./NoteView";
import { ThemeToggle } from "./theme";
import { ConfigView } from "./ConfigView";
import { NotebookProvider } from "./notebookData";
import { configHref, notesHref, useRoute } from "./route";
import { NotesPage } from "./TypePage";
import { Tree } from "./Tree";
import { useAsync } from "./useAsync";

function Login({ onDone }: { onDone: () => void }) {
  const t = useT();
  const [pw, setPw] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await api.login(pw);
      onDone();
    } catch (x) {
      setErr(x instanceof ApiError && x.status === 429 ? t.tooMany : t.wrongPassword);
    }
  };
  return (
    <form className="card login" onSubmit={submit}>
      <h1>{t.appTitle}</h1>
      <input
        type="password"
        autoFocus
        aria-label={t.password}
        placeholder={t.password}
        value={pw}
        onChange={(e) => setPw(e.target.value)}
      />
      <button type="submit" className="primary">{t.signIn}</button>
      {err && <p className="error" role="alert">{err}</p>}
    </form>
  );
}

function Shell({ onSignOut, lang, setLang }: { onSignOut: () => void; lang: Lang; setLang: (l: Lang) => void }) {
  const t = useT();
  const route = useRoute();
  const [menu, setMenu] = useState(false);
  const nbs = useAsync(() => api.notebooks(), []);
  const list: Notebook[] = nbs.data ?? [];
  const current = route.page === "notebooks" ? undefined : route.notebook;
  useEffect(() => setMenu(false), [route]);
  useEffect(() => {
    // no notebook in the address: open the first active one
    if (route.page === "notebooks" && list.length) window.location.replace(notesHref((list.find((n) => n.status === "active") ?? list[0]).slug));
  }, [route.page, list.length]);
  const proposed = list.find((n) => n.slug === current)?.status === "proposed";
  const frame = (
    <div className={`app${menu ? " menu-open" : ""}`}>
      <aside className="side">
        <div className="side-head">
          <select
            aria-label={t.switchNotebook}
            value={current ?? ""}
            onChange={(e) => {
              window.location.hash = notesHref(e.target.value);
            }}
          >
            {!current && <option value="">{t.chooseNotebook}</option>}
            {list.map((n) => (
              <option key={n.slug} value={n.slug}>
                {n.name}{n.status === "proposed" ? ` · ${t.proposedBadge}` : ""}
              </option>
            ))}
          </select>
        </div>
        {current && <Tree route={route} />}
        {current && (
          <div className="side-foot">
            <a href={configHref(current)}>{t.config}</a>
          </div>
        )}
      </aside>
      <div className="stage">
        <header className="top">
          <button className="icon-btn burger" aria-label={t.openMenu} onClick={() => setMenu((m) => !m)}>☰</button>
          <a href="#/" className="brand">{t.appTitle}</a>
          <span className="spacer" />
          <select aria-label={t.lang} value={lang} onChange={(e) => setLang(e.target.value as Lang)}>
            <option value="ru">RU</option>
            <option value="en">EN</option>
          </select>
          <ThemeToggle />
          <button onClick={onSignOut}>{t.signOut}</button>
        </header>
        <main>
          {nbs.loading && !nbs.data && <p>{t.loading}</p>}
          {nbs.error && <p className="error">{nbs.error.message}</p>}
          {nbs.data && !list.length && <p>{t.noNotebooks}</p>}
          {route.page === "notes" && <NotesPage route={route} />}
          {route.page === "config" && <ConfigView notebook={route.notebook} />}
          {route.page === "note" && (
            <NoteView key={route.notebook + route.id} notebook={route.notebook} id={route.id} sha={route.sha} />
          )}
        </main>
      </div>
    </div>
  );
  return current ? (
    <NotebookProvider key={current} notebook={current} proposed={proposed}>
      {frame}
    </NotebookProvider>
  ) : (
    frame
  );
}

export function App() {
  const [lang, setLangState] = useState<Lang>(initialLang);
  const setLang = (l: Lang) => {
    setLangState(l);
    try {
      localStorage.setItem("okf-lang", l);
    } catch {
      /* storage unavailable */
    }
  };
  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);
  const session = useAsync(() => api.session(), []);
  const t = dictionaries[lang];
  return (
    <LangContext.Provider value={t}>
      {session.loading ? (
        <p className="center">{t.loading}</p>
      ) : session.data?.authenticated ? (
        <Shell
          lang={lang}
          setLang={setLang}
          onSignOut={() => void api.logout().then(session.reload)}
        />
      ) : (
        <Login onDone={session.reload} />
      )}
    </LangContext.Provider>
  );
}
