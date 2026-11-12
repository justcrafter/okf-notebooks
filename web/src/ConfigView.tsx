import { api } from "./api";
import { useT } from "./i18n";
import { notesHref } from "./route";
import { useAsync } from "./useAsync";

// Raw, read-only text of the notebook's `.okf/` files; React escapes it, nothing is interpreted.
export function ConfigView({ notebook }: { notebook: string }) {
  const t = useT();
  const cfg = useAsync(() => api.config(notebook), [notebook]);
  return (
    <>
      <p><a href={notesHref(notebook)}>← {notebook}</a></p>
      <h2>{t.config}: {notebook}</h2>
      <p className="muted">{t.configHint}</p>
      {cfg.loading && <p>{t.loading}</p>}
      {cfg.error && <p className="error">{cfg.error.message}</p>}
      {cfg.data && !cfg.data.files.length && <p>{t.noConfig}</p>}
      {cfg.data?.files.map((f) => (
        <section key={f.path}>
          <h3><code>{f.path}</code>{f.truncated && <span className="muted"> · {t.truncated}</span>}</h3>
          <pre className="file">{f.content}</pre>
        </section>
      ))}
    </>
  );
}
