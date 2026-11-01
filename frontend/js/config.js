// All URLs are relative, so the app works at "/" (Docker) and under "/<repo>/" (GitHub Pages).
//
// API_BASE: the backend (article import, daily articles, Anki upload). Static hosting has no
//   backend: those features then say they need a server. Set a full URL to point at one.
// PACKS_BASE: where deck packs are downloaded from. "" = the "packs/" folder next to the app.
export const API_BASE = "api";
export const PACKS_BASE = "";
// ARTICLES_BASE: static copy of the daily articles (published by a scheduled GitHub Action).
//   Used when the backend API isn't there.
export const ARTICLES_BASE = "articles";

export const apiUrl = (path = "") => `${API_BASE}${path}`;
export const articlesUrl = (path = "") => `${ARTICLES_BASE}${path}`;
export const packsUrl = (path = "") => `${PACKS_BASE || "packs"}${path}`;

// GRAMMAR_BASE: syllabus + exercises (content/grammar), published next to the app.
export const GRAMMAR_BASE = "grammar";
export const grammarUrl = (path = "") => `${GRAMMAR_BASE}${path}`;
