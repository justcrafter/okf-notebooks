export type DiffLineKind = "add" | "del" | "hunk" | "meta" | "ctx";

export interface DiffLine {
  kind: DiffLineKind;
  text: string;
}

// Classifies a unified diff as git prints it; headers before the first hunk are "meta".
export function parseDiff(diff: string): DiffLine[] {
  const out: DiffLine[] = [];
  let inHunk = false;
  for (const text of diff.replace(/\n$/, "").split("\n")) {
    if (text.startsWith("@@")) {
      inHunk = true;
      out.push({ kind: "hunk", text });
    } else if (!inHunk) {
      out.push({ kind: "meta", text });
    } else if (text.startsWith("+")) {
      out.push({ kind: "add", text });
    } else if (text.startsWith("-")) {
      out.push({ kind: "del", text });
    } else {
      out.push({ kind: "ctx", text });
    }
  }
  return out;
}
