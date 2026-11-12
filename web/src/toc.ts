export interface Heading {
  level: number;
  text: string;
  id: string;
  line: number;
}

/** Heading text with the common inline Markdown marks removed. */
const plain = (s: string) =>
  s
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/[`*_~]/g, "")
    .trim();

export const slugify = (s: string) =>
  plain(s)
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s-]/gu, "")
    .replace(/\s+/g, "-") || "section";

/** ATX headings `#`..`###` of a Markdown body (fenced code skipped) with unique ids and 1-based line numbers. */
export function headings(body: string): Heading[] {
  const out: Heading[] = [];
  const seen = new Map<string, number>();
  let fence: string | null = null;
  body.split("\n").forEach((line, i) => {
    const f = /^\s{0,3}(```|~~~)/.exec(line);
    if (f) {
      fence = fence === null ? f[1] : fence === f[1] ? null : fence;
      return;
    }
    if (fence) return;
    const m = /^ {0,3}(#{1,3})\s+(.+?)\s*#*\s*$/.exec(line);
    if (!m) return;
    const base = slugify(m[2]);
    const n = seen.get(base) ?? 0;
    seen.set(base, n + 1);
    out.push({ level: m[1].length, text: plain(m[2]), id: n ? `${base}-${n}` : base, line: i + 1 });
  });
  return out;
}
