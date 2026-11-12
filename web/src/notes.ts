import type { NoteItem, TypeInfo } from "./api";

export interface TypeGroup {
  name: string;
  items: NoteItem[];
}

/** Declared types first (registry order), then undeclared ones by name; notes of a type sorted by title. */
export function typeGroups(declared: TypeInfo[] | undefined, items: NoteItem[]): TypeGroup[] {
  const by = new Map<string, NoteItem[]>();
  for (const t of declared ?? []) by.set(t.name, []);
  const extra = new Set<string>();
  for (const i of items) {
    if (!by.has(i.type)) {
      by.set(i.type, []);
      extra.add(i.type);
    }
    by.get(i.type)!.push(i);
  }
  const names = [...(declared ?? []).map((t) => t.name), ...[...extra].sort((a, b) => a.localeCompare(b))];
  return names.map((name) => ({ name, items: by.get(name)!.sort((a, b) => a.title.localeCompare(b.title)) }));
}

const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["year", 365 * 86400],
  ["month", 30 * 86400],
  ["day", 86400],
  ["hour", 3600],
  ["minute", 60],
];

/** "2 hours ago" / "2 ч назад" for an ISO time; `justNow` under a minute. */
export function relativeTime(iso: string, now: number, locale: string, justNow: string): string {
  const secs = Math.round((now - new Date(iso).getTime()) / 1000);
  if (!Number.isFinite(secs) || secs < 60) return justNow;
  const fmt = new Intl.RelativeTimeFormat(locale, { numeric: "auto", style: "short" });
  for (const [unit, size] of UNITS) {
    if (secs >= size) return fmt.format(-Math.floor(secs / size), unit);
  }
  return justNow;
}
