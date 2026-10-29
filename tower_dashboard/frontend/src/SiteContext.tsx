import { createContext, useContext } from "react";

interface SiteState {
  site: string | null;
  setSite: (s: string | null) => void;
}

export const SiteContext = createContext<SiteState>({ site: null, setSite: () => {} });
export const useSite = () => useContext(SiteContext);
