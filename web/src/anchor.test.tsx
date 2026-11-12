import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { buildIndex, collapse, completeMention, findQuote, mentionQuery } from "./anchor";
import { SafeMarkdown } from "./Safe";

const page = (md: string) => render(<article><SafeMarkdown notebook="kube" text={md} /></article>).container;

describe("anchoring a quote in the rendered note", () => {
  it("finds a phrase across inline markup", () => {
    const root = page("Roll **back** with `ArgoCD` now.");
    const r = findQuote(buildIndex(root), "Roll back with ArgoCD now.");
    expect(r?.toString()).toBe("Roll back with ArgoCD now.");
  });
  it("spans blocks the way a selection does", () => {
    const root = page("First paragraph.\n\nSecond paragraph.");
    const r = findQuote(buildIndex(root), "First paragraph. Second paragraph.");
    expect(r).not.toBeNull();
  });
  it("tells a repeated phrase apart by its context", () => {
    const root = page("alpha target omega\n\nbeta target gamma");
    const r = findQuote(buildIndex(root), "target", "beta", "gamma");
    expect(r?.startContainer.textContent).toBe("beta target gamma");
  });
  it("detaches when the text is gone", () => {
    const root = page("Totally rewritten.");
    expect(findQuote(buildIndex(root), "Roll back")).toBeNull();
  });
  it("collapses whitespace", () => {
    expect(collapse("  a \n b\t c ")).toBe("a b c");
  });
});

describe("mentions while typing", () => {
  it("sees the @name at the end", () => {
    expect(mentionQuery("hi @cl")).toBe("cl");
    expect(mentionQuery("hi @")).toBe("");
    expect(mentionQuery("mail a@b")).toBeNull();
    expect(mentionQuery("hi @claude-code done")).toBeNull();
  });
  it("completes it", () => {
    expect(completeMention("hi @cl", "claude-code")).toBe("hi @claude-code ");
  });
});
