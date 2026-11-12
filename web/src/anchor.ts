// Anchoring a Thread to the rendered note: the Quote is plain text with collapsed whitespace, found again
// by search (not by offsets), so an edited note keeps the highlights that still match and detaches the rest.

const BLOCK = "P,LI,H1,H2,H3,H4,H5,H6,PRE,TD,TH,BLOCKQUOTE,DIV,TR,UL,OL,TABLE";
export const CONTEXT = 40;

export interface TextIndex {
  text: string;
  at: { node: Text; offset: number }[]; // for each character of `text`
}

const blockOf = (n: Node): Element | null => (n.parentElement ? n.parentElement.closest(BLOCK) : null);

export function collapse(s: string): string {
  return s.replace(/\s+/g, " ").trim();
}

// Whitespace collapses to one space; a change of block adds one, as a selection's toString() does.
export function buildIndex(root: Node): TextIndex {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: (n) => (n.parentElement?.closest("svg,script,style") ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
  });
  const at: TextIndex["at"] = [];
  let text = "";
  let lastBlock: Element | null | undefined;
  let prev: Text | null = null;
  const push = (ch: string, node: Text, offset: number) => {
    if (ch === " " && (text === "" || text.endsWith(" "))) return;
    text += ch;
    at.push({ node, offset });
  };
  for (let n = walker.nextNode() as Text | null; n; n = walker.nextNode() as Text | null) {
    const block = blockOf(n);
    if (prev && block !== lastBlock) push(" ", prev, prev.data.length);
    lastBlock = block;
    prev = n;
    for (let i = 0; i < n.data.length; i++) push(/\s/.test(n.data[i]) ? " " : n.data[i], n, i);
  }
  return { text, at };
}

function occurrences(text: string, quote: string): number[] {
  const out: number[] = [];
  for (let i = text.indexOf(quote); i >= 0; i = text.indexOf(quote, i + 1)) out.push(i);
  return out;
}

export function rangeAt(index: TextIndex, start: number, length: number): Range {
  const a = index.at[start];
  const b = index.at[start + length - 1];
  const r = document.createRange();
  r.setStart(a.node, a.offset);
  r.setEnd(b.node, b.offset + 1);
  return r;
}

// The occurrence of the quote that best matches the stored context, or null (the Thread is Detached).
export function findQuote(index: TextIndex, quote: string, prefix = "", suffix = ""): Range | null {
  const q = collapse(quote);
  if (!q) return null;
  const hits = occurrences(index.text, q);
  if (!hits.length) return null;
  const p = collapse(prefix);
  const s = collapse(suffix);
  const score = (i: number) =>
    (p && index.text.slice(0, i).trimEnd().endsWith(p) ? 2 : 0) + (s && index.text.slice(i + q.length).trimStart().startsWith(s) ? 1 : 0);
  const best = hits.reduce((a, b) => (score(b) > score(a) ? b : a), hits[0]);
  return rangeAt(index, best, q.length);
}

export interface Selected {
  quote: string;
  prefix: string;
  suffix: string;
  rect: DOMRect;
}

// What the reader selected inside `root`, with the text around it so a repeated phrase is told apart.
export function describeSelection(root: Node, sel: Selection | null): Selected | null {
  if (!sel || sel.isCollapsed || sel.rangeCount === 0) return null;
  const range = sel.getRangeAt(0);
  if (!root.contains(range.commonAncestorContainer)) return null;
  const quote = collapse(sel.toString());
  if (!quote) return null;
  const index = buildIndex(root);
  const hits = occurrences(index.text, quote);
  if (!hits.length) return null;
  const pick =
    hits.find((i) => range.compareBoundaryPoints(Range.START_TO_START, rangeAt(index, i, quote.length)) <= 0) ?? hits[0];
  return {
    quote,
    prefix: index.text.slice(Math.max(0, pick - CONTEXT), pick),
    suffix: index.text.slice(pick + quote.length, pick + quote.length + CONTEXT),
    rect: range.getBoundingClientRect(),
  };
}

// The `@name` the reader is typing at the end of `text`, if any.
export function mentionQuery(text: string): string | null {
  const m = /(?:^|[\s(])@([\w-]*)$/.exec(text);
  return m ? m[1] : null;
}

export function completeMention(text: string, name: string): string {
  return text.replace(/@([\w-]*)$/, `@${name} `);
}
