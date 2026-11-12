import { createContext, useContext, type ReactNode } from "react";
import { api, type NotebookTypes, type NoteItem, type Status } from "./api";
import { useAsync, type Async } from "./useAsync";

export const ALL_STATUSES: Status[] = ["draft", "stable", "deprecated"];

export interface NbData {
  notebook: string;
  proposed: boolean;
  types: Async<NotebookTypes>;
  notes: Async<NoteItem[]>;
  reload: () => void;
}

const NbContext = createContext<NbData | null>(null);

/** One fetch of the notebook's types and all its notes (every status), shared by the tree, type pages and notes. */
export function NotebookProvider({ notebook, proposed, children }: { notebook: string; proposed: boolean; children: ReactNode }) {
  const types = useAsync(() => api.types(notebook), [notebook]);
  const notes = useAsync(() => api.notes(notebook, ALL_STATUSES), [notebook]);
  const reload = () => {
    types.reload();
    notes.reload();
  };
  return <NbContext.Provider value={{ notebook, proposed, types, notes, reload }}>{children}</NbContext.Provider>;
}

export function useNb(): NbData {
  const v = useContext(NbContext);
  if (!v) throw new Error("useNb outside NotebookProvider");
  return v;
}
