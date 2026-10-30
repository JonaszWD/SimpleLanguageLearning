// All URLs are relative, so the app works at "/" (Docker) and under "/<repo>/" (GitHub Pages).
//
// API_BASE: the backend (article import, daily articles, Anki upload). Static hosting has no
//   backend: those features then say they need a server. Set a full URL to point at one.
// PACKS_BASE: where deck packs are downloaded from. "" = the "packs/" folder next to the app.
export const API_BASE = "api";
export const PACKS_BASE = "";

export const apiUrl = (path = "") => `${API_BASE}${path}`;
export const packsUrl = (path = "") => `${PACKS_BASE || "packs"}${path}`;
