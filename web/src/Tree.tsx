import { useEffect, useState } from "react";
import { useT } from "./i18n";
import { typeGroups } from "./notes";
import { useNb } from "./notebookData";
import { noteHref, notesHref, type Route } from "./route";

/** Left panel: the notebook, its types with counts, and each type's notes (alphabetical). */
export function Tree({ route }: { route: Route }) {
  const t = useT();
  const { notebook, types, notes } = useNb();
  const [filter, setFilter] = useState("");
  const [open, setOpen] = useState<Set<string>>(new Set());
  const groups = typeGroups(types.data?.types, notes.data ?? []);
  const q = filter.trim().toLowerCase();

  const expand = (name: string) => setOpen((cur) => (cur.has(name) ? cur : new Set(cur).add(name)));
  const toggle = (name: string) =>
    setOpen((cur) => {
      const next = new Set(cur);
      if (!next.delete(name)) next.add(name);
      return next;
    });

  const currentType =
    route.page === "notes"
      ? route.type
      : route.page === "note"
        ? notes.data?.find((n) => n.id === route.id)?.type
        : undefined;
  useEffect(() => {
    if (currentType) expand(currentType);
  }, [currentType]);

  return (
    <nav className="tree" aria-label={types.data?.name ?? notebook}>
      <input
        type="search"
        className="tree-filter"
        aria-label={t.filterPlaceholder}
        placeholder={t.filterPlaceholder}
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
      />
      <a className={`tree-root${route.page === "notes" && !route.type && !route.tag ? " active" : ""}`} href={notesHref(notebook)}>
        {types.data?.name ?? notebook}
      </a>
      <ul>
        {groups.map((g) => {
          const items = q ? g.items.filter((i) => i.title.toLowerCase().includes(q)) : g.items;
          if (q && !items.length) return null;
          const isOpen = !!q || open.has(g.name);
          return (
            <li key={g.name}>
              <div className={`tree-type${currentType === g.name && route.page === "notes" ? " active" : ""}`}>
                <button
                  className="chev"
                  aria-label={`${t.toggleType}: ${g.name}`}
                  aria-expanded={isOpen}
                  onClick={() => toggle(g.name)}
                >
                  {isOpen ? "▾" : "▸"}
                </button>
                <a href={notesHref(notebook, g.name)} onClick={() => expand(g.name)}>{g.name}</a>
                <span className="count">{g.items.length}</span>
              </div>
              {isOpen && (
                <ul className="tree-notes">
                  {items.map((n) => (
                    <li key={n.id}>
                      <a
                        href={noteHref(notebook, n.id)}
                        className={`${route.page === "note" && route.id === n.id ? "active" : ""}${n.status === "deprecated" ? " dep" : ""}`}
                        title={n.title}
                      >
                        <span className={`dot ${n.status}`} aria-label={n.status} />
                        {n.title}
                      </a>
                    </li>
                  ))}
                </ul>
              )}
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
