import type { ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { noteHref } from "./route";
import { MermaidDiagram } from "./Mermaid";
import type { Heading } from "./toc";

// Note bodies are written by agents (untrusted): raw HTML is never rendered (react-markdown's
// default), images are dropped, and only http(s) and note-internal links survive.
export function safeUrl(url: string): string {
  if (/^https?:\/\//i.test(url) || url.startsWith("/") || url.startsWith("#")) return url;
  return "";
}

export function internalTarget(href: string, notebook: string): string | null {
  const m = /^\/([^/]+)\/([^/]+?)(?:\.md)?$/.exec(href);
  return m ? noteHref(notebook, `/${m[1]}/${m[2]}`) : null;
}

function isMermaid(node: unknown): boolean {
  const first = (node as { children?: { properties?: { className?: unknown } }[] } | undefined)?.children?.[0];
  const cls = first?.properties?.className;
  return Array.isArray(cls) && cls.includes("language-mermaid");
}

// `toc` gives h1-h3 their anchor ids (matched by source line) so the "On this page" panel can scroll to them.
export function SafeMarkdown({ text, notebook, toc = [] }: { text: string; notebook: string; toc?: Heading[] }): ReactNode {
  const byLine = new Map(toc.map((h) => [h.line, h.id]));
  const heading = (Tag: "h1" | "h2" | "h3") =>
    function Head({ node, children }: { node?: { position?: { start: { line: number } } }; children?: ReactNode }) {
      return <Tag id={byLine.get(node?.position?.start.line ?? -1)}>{children}</Tag>;
    };
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      urlTransform={safeUrl}
      components={{
        // a ```mermaid fence becomes a diagram (no <pre> wrapper); every other code block is untouched
        pre: ({ node, children }) => (isMermaid(node) ? <>{children}</> : <pre>{children}</pre>),
        code: ({ className, children }) =>
          /\blanguage-mermaid\b/.test(className ?? "") ? (
            <MermaidDiagram source={String(children).replace(/\n$/, "")} />
          ) : (
            <code className={className}>{children}</code>
          ),
        h1: heading("h1"),
        h2: heading("h2"),
        h3: heading("h3"),
        img: ({ alt }) => <span>{alt}</span>,
        a: ({ href, children }) => {
          const internal = href ? internalTarget(href, notebook) : null;
          if (internal) return <a href={internal}>{children}</a>;
          if (!href) return <span>{children}</span>;
          if (href.startsWith("#") && !href.startsWith("#/")) {
            // in-page anchors (footnotes): the address hash is the router's, so scroll instead of navigating
            return (
              <a
                href={href}
                onClick={(e) => {
                  e.preventDefault();
                  document.getElementById(decodeURIComponent(href.slice(1)))?.scrollIntoView({ behavior: "smooth", block: "center" });
                }}
              >
                {children}
              </a>
            );
          }
          return (
            <a href={href} target="_blank" rel="noreferrer noopener">
              {children}
            </a>
          );
        },
      }}
    >
      {text}
    </ReactMarkdown>
  );
}
