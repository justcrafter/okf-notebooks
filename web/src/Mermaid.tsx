import { useEffect, useId, useState } from "react";
import { useT } from "./i18n";

type Mermaid = typeof import("mermaid").default;

// Loaded on first use only: the library and its diagram parsers are separate chunks, so notes without
// diagrams never download them. Served from our own origin (CSP: script-src 'self').
let loading: Promise<Mermaid> | null = null;
const load = () => (loading ??= import("mermaid").then((m) => m.default));

const currentTheme = (): "dark" | "default" => {
  const set = document.documentElement.getAttribute("data-theme");
  const dark = set ? set === "dark" : !!window.matchMedia?.("(prefers-color-scheme: dark)").matches;
  return dark ? "dark" : "default";
};

/**
 * A fenced ```mermaid block. The source is written by agents (untrusted), so Mermaid runs with
 * securityLevel "strict": it sanitises labels and refuses click handlers and raw HTML. A diagram that
 * fails to parse falls back to its source text and the parser's message.
 */
export function MermaidDiagram({ source }: { source: string }) {
  const t = useT();
  const id = "mmd" + useId().replace(/[^a-zA-Z0-9]/g, "");
  const [theme, setTheme] = useState(currentTheme);
  const [out, setOut] = useState<{ svg: string } | { error: string } | null>(null);

  useEffect(() => {
    const mo = new MutationObserver(() => setTheme(currentTheme()));
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => mo.disconnect();
  }, []);

  useEffect(() => {
    let live = true;
    setOut(null);
    load()
      .then(async (mermaid) => {
        mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme });
        return mermaid.render(id, source);
      })
      .then(
        ({ svg }) => live && setOut({ svg }),
        (e: unknown) => {
          // a failed render leaves its error element behind in <body>
          document.getElementById("d" + id)?.remove();
          if (live) setOut({ error: e instanceof Error ? e.message : String(e) });
        },
      );
    return () => {
      live = false;
    };
  }, [source, theme, id]);

  if (out && "error" in out)
    return (
      <div className="mermaid-error" role="alert">
        <p className="error">{t.diagramError}</p>
        <pre className="file">{source}</pre>
        <p className="muted">{out.error}</p>
      </div>
    );
  if (!out) return <div className="mermaid mermaid-pending" aria-busy="true">{t.loading}</div>;
  return <div className="mermaid" role="img" dangerouslySetInnerHTML={{ __html: out.svg }} />;
}
