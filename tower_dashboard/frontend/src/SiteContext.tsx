import { createContext, useContext } from "react";

export type ViewportFace = "ALL" | "A" | "B" | "C" | "D";

interface SiteState {
  site: string | null;
  setSite: (s: string | null) => void;
  editMode?: boolean;
  setEditMode?: (v: boolean) => void;
  activeFace?: ViewportFace;
  setActiveFace?: (f: ViewportFace) => void;
}

export const SiteContext = createContext<SiteState>({
  site: null,
  setSite: () => {},
  editMode: false,
  setEditMode: () => {},
  activeFace: "ALL",
  setActiveFace: () => {},
});

export const useSite = () => useContext(SiteContext);
