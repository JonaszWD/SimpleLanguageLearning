// Background content sync: the deck pack (cards + audio) and the daily articles appear on their
// own. Everything is resumable, so closing the app mid-download is fine.
import * as db from "./db.js";
import { availablePacks, installPack, installedPacks } from "./packs.js";

const listeners = new Set();
let status = null; // { phase, done?, total? } while syncing
let running = false;
let lastRun = 0;

export const subscribe = (fn) => { listeners.add(fn); fn(status); return () => listeners.delete(fn); };
const set = (s) => { status = s; listeners.forEach((fn) => fn(status)); };

async function syncDecks() {
  const metas = await availablePacks();
  const installed = await installedPacks();
  const haveAudio = (await db.getAllKeys("media")).length;
  const wantAudio = metas.reduce((n, m) => n + m.audioFiles, 0);
  for (const m of metas) {
    const it = installed.get(m.id);
    if (it?.version === m.version && haveAudio >= wantAudio) continue;
    await installPack(m, (p) => set({ phase: `${m.title}: ${p.phase.replace("…", "")}`, done: p.done, total: p.total }));
  }
}

const DISMISSED = "articles:dismissed";
const KEEP_AUTO = 20;

export async function dismissArticle(id) {
  const v = new Set((await db.get("settings", DISMISSED))?.value || []);
  v.add(id);
  await db.put("settings", { key: DISMISSED, value: [...v] });
}

async function syncArticles() {
  const index = await (await fetch("/api/articles/daily")).json();
  const items = await db.getAll("library");
  const have = new Set(items.map((i) => i.id));
  const dismissed = new Set((await db.get("settings", DISMISSED))?.value || []);
  const fresh = index.filter((a) => !have.has(`article:${a.id}`) && !dismissed.has(`article:${a.id}`));
  for (const [n, a] of fresh.entries()) {
    set({ phase: "Fetching articles", done: n, total: fresh.length });
    const res = await fetch(`/api/articles/daily/${a.id}`);
    if (!res.ok) continue;
    const art = await res.json();
    await db.put("library", {
      id: `article:${a.id}`, kind: "article", auto: true, title: art.title, source: art.source,
      url: art.url, text: art.text, words: art.words, glossary: art.glossary, added: Date.parse(a.published) || Date.now(),
    });
  }
  // keep the newest KEEP_AUTO synced articles
  const autos = (await db.getAll("library")).filter((i) => i.auto).sort((a, b) => b.added - a.added);
  await db.delMany("library", autos.slice(KEEP_AUTO).map((i) => i.id));
}

export async function syncAll({ force = false } = {}) {
  if (running || !navigator.onLine) return;
  if (!force && (!(await db.getSettings()).autoSync || Date.now() - lastRun < 30 * 60_000)) return;
  running = true;
  try {
    // Articles first: small and quick. The deck audio can take a while.
    for (const step of [syncArticles, syncDecks]) {
      try { await step(); } catch (e) { console.warn("sync step failed", e); }
    }
    lastRun = Date.now();
  } finally {
    running = false;
    set(null);
  }
}

export function initSync() {
  syncAll();
  document.addEventListener("visibilitychange", () => { if (!document.hidden) syncAll(); });
  addEventListener("online", () => syncAll());
}
