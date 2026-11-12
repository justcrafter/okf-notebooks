import { useEffect, useState } from "react";
import type { Status } from "./api";

export type Route =
  | { page: "notebooks" }
  | { page: "notes"; notebook: string; type?: string; tag?: string; status?: Status[] }
  | { page: "config"; notebook: string }
  | { page: "note"; notebook: string; id: string; sha?: string };

const STATUSES: Status[] = ["draft", "stable", "deprecated"];

export function parseHash(hash: string): Route {
  const [path, query = ""] = hash.replace(/^#/, "").split("?");
  const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
  const q = new URLSearchParams(query);
  if (parts[0] === "n" && parts.length === 2) {
    const status = (q.get("status") ?? "").split(",").filter((s): s is Status => STATUSES.includes(s as Status));
    return {
      page: "notes",
      notebook: parts[1],
      type: q.get("type") || undefined,
      tag: q.get("tag") || undefined,
      status: status.length ? status : undefined,
    };
  }
  if (parts[0] === "n" && parts.length === 3 && parts[2] === "config") return { page: "config", notebook: parts[1] };
  if (parts[0] === "n" && parts.length === 4) {
    return { page: "note", notebook: parts[1], id: `/${parts[2]}/${parts[3]}`, sha: q.get("rev") ?? undefined };
  }
  return { page: "notebooks" };
}

export interface NotesFilter {
  tag?: string;
  status?: Status[];
}

export const notesHref = (nb: string, type?: string, f: NotesFilter = {}) => {
  const q = new URLSearchParams();
  if (type) q.set("type", type);
  if (f.tag) q.set("tag", f.tag);
  if (f.status?.length) q.set("status", f.status.join(","));
  const s = q.toString();
  return `#/n/${encodeURIComponent(nb)}${s ? `?${s}` : ""}`;
};
export const configHref = (nb: string) => `#/n/${encodeURIComponent(nb)}/config`;
export const noteHref = (nb: string, id: string, sha?: string) =>
  `#/n/${encodeURIComponent(nb)}${id}${sha ? `?rev=${sha}` : ""}`;

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parseHash(window.location.hash));
  useEffect(() => {
    const on = () => setRoute(parseHash(window.location.hash));
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}
