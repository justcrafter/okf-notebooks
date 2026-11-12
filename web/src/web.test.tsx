import { render, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { parseDiff } from "./diff";
import { relativeTime, typeGroups } from "./notes";
import type { NoteItem } from "./api";
import { headings } from "./toc";
import { notesHref, parseHash } from "./route";
import { internalTarget, safeUrl, SafeMarkdown } from "./Safe";

describe("SafeMarkdown", () => {
  it("never renders raw HTML or script", () => {
    const { container } = render(
      <SafeMarkdown notebook="kube" text={'hi <script>alert(1)</script><img src=x onerror=alert(1)> <b onclick="x()">b</b>'} />,
    );
    expect(container.querySelector("script,img,b")).toBeNull();
  });
  it("drops javascript: links and images", () => {
    const { container } = render(<SafeMarkdown notebook="kube" text={"[x](javascript:alert(1)) ![pic](http://e/x.png)"} />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector('a[href^="javascript"]')).toBeNull();
  });
  it("maps internal note links to the UI route and opens externals safely", () => {
    const { container } = render(<SafeMarkdown notebook="kube" text={"[a](/decisions/x.md) [b](https://e.com)"} />);
    const [a, b] = Array.from(container.querySelectorAll("a"));
    expect(a.getAttribute("href")).toBe("#/n/kube/decisions/x");
    expect(b.getAttribute("rel")).toBe("noreferrer noopener");
  });
  it("safeUrl allows only http(s) and local", () => {
    expect(safeUrl("javascript:x")).toBe("");
    expect(safeUrl("data:text/html,x")).toBe("");
    expect(safeUrl("https://a")).toBe("https://a");
    expect(internalTarget("/decisions/x", "kube")).toBe("#/n/kube/decisions/x");
  });
});

describe("routing and diff", () => {
  it("parses hash routes", () => {
    expect(parseHash("")).toEqual({ page: "notebooks" });
    expect(parseHash("#/n/kube")).toEqual({ page: "notes", notebook: "kube" });
    expect(parseHash("#/n/kube/config")).toEqual({ page: "config", notebook: "kube" });
    expect(parseHash("#/n/kube/decisions/x?rev=abc1234")).toEqual({ page: "note", notebook: "kube", id: "/decisions/x", sha: "abc1234" });
  });
  it("classifies diff lines", () => {
    const k = parseDiff("diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1 +1 @@\n-old\n+new\n ctx\n").map((l) => l.kind);
    expect(k).toEqual(["meta", "meta", "meta", "hunk", "del", "add", "ctx"]);
  });
});

describe("notes list helpers", () => {
  const item = (type: string, title = "t"): NoteItem =>
    ({ notebook: "k", id: `/${type}/${title}`, title, type, description: "", status: "draft", stale: false, last_revised: null, tags: [] });
  it("parses type, tag and status filters from the route", () => {
    expect(parseHash("#/n/kube?type=Ticket&tag=k8s&status=draft,bogus")).toEqual({
      page: "notes", notebook: "kube", type: "Ticket", tag: "k8s", status: ["draft"],
    });
    expect(parseHash("#/n/kube")).toEqual({ page: "notes", notebook: "kube" });
  });
  it("builds filter links", () => {
    expect(notesHref("kube", "Bug", { tag: "a b", status: ["draft"] })).toBe("#/n/kube?type=Bug&tag=a+b&status=draft");
    expect(notesHref("kube")).toBe("#/n/kube");
  });
  it("groups notes by declared type first, keeps empty declared types, sorts titles", () => {
    const declared = [
      { name: "Spec", dir: "specs", description: "", fields: [], count: 0 },
      { name: "Bug", dir: "bugs", description: "", fields: [], count: 1 },
    ];
    const g = typeGroups(declared, [item("Bug", "b"), item("Zed", "z"), item("Bug", "a")]);
    expect(g.map((x) => [x.name, x.items.map((i) => i.title)])).toEqual([
      ["Spec", []],
      ["Bug", ["a", "b"]],
      ["Zed", ["z"]],
    ]);
  });
  it("formats relative time", () => {
    const now = Date.parse("2026-11-11T12:00:00Z");
    expect(relativeTime("2026-11-11T11:59:30Z", now, "en", "now")).toBe("now");
    expect(relativeTime("2026-11-11T10:00:00Z", now, "en", "now")).toMatch(/2 hr/);
    expect(relativeTime("2026-11-08T12:00:00Z", now, "en", "now")).toMatch(/3 days/);
  });
});

describe("GFM", () => {
  it("renders tables, strikethrough and task lists", () => {
    const md = "| a | b |\n|---|:-:|\n| 1 | 2 |\n\n~~old~~\n\n- [x] done\n";
    const { container } = render(<SafeMarkdown notebook="kube" text={md} />);
    expect(Array.from(container.querySelectorAll("th")).map((x) => x.textContent)).toEqual(["a", "b"]);
    expect(container.querySelectorAll("td")).toHaveLength(2);
    expect(container.querySelector("del")?.textContent).toBe("old");
    expect(container.querySelector('input[type="checkbox"]')).not.toBeNull();
  });
  it("keeps raw HTML out of table cells", () => {
    const { container } = render(<SafeMarkdown notebook="kube" text={"| x |\n|---|\n| <script>1</script><b>b</b> |\n"} />);
    expect(container.querySelector("script,b")).toBeNull();
  });
  it("footnote links scroll in-page instead of changing the route", () => {
    const { container } = render(<SafeMarkdown notebook="kube" text={"text[^1]\n\n[^1]: note\n"} />);
    expect(container.querySelector('a[href="#user-content-fn-1"]')).not.toBeNull();
    expect(container.querySelector('a[href="#user-content-fn-1"]')?.getAttribute("target")).toBeNull();
  });
});

describe("table of contents", () => {
  it("lists h1-h3 with unique ids and skips fenced code", () => {
    const h = headings("# Суть\n\ntext\n\n```\n# not a heading\n```\n## Грабли\n## Грабли\n#### too deep\n");
    expect(h.map((x) => [x.level, x.text, x.id, x.line])).toEqual([
      [1, "Суть", "суть", 1],
      [2, "Грабли", "грабли", 8],
      [2, "Грабли", "грабли-1", 9],
    ]);
  });
  it("anchors rendered headings by source line", () => {
    const body = "intro\n\n## Links\n";
    const { container } = render(<SafeMarkdown notebook="kube" text={body} toc={headings(body)} />);
    expect(container.querySelector("h2")?.id).toBe("links");
  });
});

const mermaidMock = vi.hoisted(() => ({
  initialize: vi.fn(),
  render: vi.fn(async (_id: string, src: string) => {
    if (src.includes("BAD")) throw new Error("Parse error on line 1");
    return { svg: '<svg data-diagram="ok"></svg>' };
  }),
}));
vi.mock("mermaid", () => ({ default: mermaidMock }));

describe("mermaid fences", () => {
  it("renders a mermaid fence as a diagram with strict security", async () => {
    const { container } = render(<SafeMarkdown notebook="kube" text={"```mermaid\ngraph TD; A-->B\n```\n"} />);
    await waitFor(() => expect(container.querySelector('svg[data-diagram="ok"]')).not.toBeNull());
    expect(container.querySelector("pre")).toBeNull();
    expect(mermaidMock.initialize).toHaveBeenCalledWith(expect.objectContaining({ securityLevel: "strict", startOnLoad: false }));
  });
  it("falls back to the source and the error when the diagram is invalid", async () => {
    const { container } = render(<SafeMarkdown notebook="kube" text={"```mermaid\nBAD\n```\n"} />);
    await waitFor(() => expect(container.querySelector(".mermaid-error")).not.toBeNull());
    expect(container.querySelector(".mermaid-error pre")?.textContent).toBe("BAD");
    expect(container.textContent).toContain("Parse error on line 1");
  });
  it("leaves other code blocks alone", () => {
    const { container } = render(<SafeMarkdown notebook="kube" text={"```python\nprint(1)\n```\n"} />);
    expect(container.querySelector("pre > code")?.textContent).toContain("print(1)");
    expect(container.querySelector(".mermaid")).toBeNull();
  });
});
