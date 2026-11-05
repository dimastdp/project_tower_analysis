const P = { fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round", strokeLinejoin: "round" } as const;

export const Icon = {
  tower: () => (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden><path {...P} d="M12 2 6.5 22M12 2l5.5 20M8.2 15.5h7.6M9.6 9.5h4.8M8.2 15.5l6.2-6M15.8 15.5l-6.2-6" /></svg>
  ),
  library: () => (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden><path {...P} d="M4 5h4v15H4zM10 5h4v15h-4zM16.5 5.5l3.4-.9 3.1 14.6-3.4.8z" /></svg>
  ),
  inventory: () => (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden><path {...P} d="M4 6h16M4 12h16M4 18h10M18 16v4M16 18h4" /></svg>
  ),
  analysis: () => (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden><path {...P} d="M4 20h16M7 20V10M12 20V4M17 20v-7" /></svg>
  ),
  sda: () => (
    <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden><path {...P} d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M16 13H8M16 17H8M10 9H8" /></svg>
  ),
};
