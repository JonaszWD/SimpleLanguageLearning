// Install content packs (deck + audio + shadowing clips) from the server into IndexedDB.
import * as db from "./db.js";
import { newCardState } from "./srs.js";
import { packsUrl } from "./config.js";

export async function mergeDeck({ decks, models, notes, cards }) {
  const haveGuid = new Set((await db.getAll("notes")).map((n) => n.guid));
  const haveDeck = new Set((await db.getAll("decks")).map((d) => d.id));
  const haveModel = new Set((await db.getAll("models")).map((m) => m.id));
  const fresh = notes.filter((n) => !haveGuid.has(n.guid));
  const freshIds = new Set(fresh.map((n) => n.id));
  const freshCards = cards.filter((c) => freshIds.has(c.nid)).map((c) => newCardState(c));
  const usedDecks = new Set(freshCards.map((c) => c.did));
  await db.putMany("models", models.filter((m) => !haveModel.has(m.id)));
  await db.putMany("decks", decks.filter((d) => !haveDeck.has(d.id) && usedDecks.has(d.id)));
  await db.putMany("notes", fresh);
  await db.putMany("cards", freshCards);
  return { notes: fresh.length, cards: freshCards.length, skipped: notes.length - fresh.length };
}

export async function availablePacks() {
  const res = await fetch(packsUrl("/index.json"), { cache: "no-cache" });
  if (!res.ok) throw new Error(`Pack list unavailable (${res.status})`);
  return res.json();
}

export async function installedPacks() {
  return new Map((await db.getAll("library")).filter((i) => i.kind === "clips").map((i) => [i.packId, i]));
}

// Resumable: audio already stored is skipped, so an interrupted install can simply be re-run.
export async function installPack(meta, onProgress) {
  const res = await fetch(packsUrl(`/${meta.id}/manifest.json`));
  if (!res.ok) throw new Error(`Could not download pack (${res.status})`);
  const m = await res.json();

  onProgress({ phase: "Adding cards…" });
  const merged = await mergeDeck(m);

  await db.put("library", { id: `pack:${meta.id}`, packId: meta.id, kind: "clips", title: m.title, clips: m.clips, version: null });
  const have = new Set(await db.getAllKeys("media"));
  const todo = m.audio.filter((n) => !have.has(n));
  let done = 0;
  let failed = 0;
  const total = todo.length;
  const queue = [...todo];

  // Static hosts rate-limit bursts (the reply may even lack CORS headers), so retry with backoff.
  const download = async (name) => {
    for (let attempt = 0; attempt < 5; attempt++) {
      try {
        const r = await fetch(packsUrl(`/${meta.id}/audio/${encodeURIComponent(name)}`));
        if (r.ok) return await r.blob();
        if (r.status !== 429 && r.status < 500) return null; // permanent, e.g. 404
      } catch { /* network or throttled: retry */ }
      await new Promise((res) => setTimeout(res, 500 * 2 ** attempt));
    }
    return null;
  };
  const worker = async () => {
    for (let name; (name = queue.shift()); ) {
      const blob = await download(name);
      if (blob) await db.put("media", { name, blob });
      else failed++;
      onProgress({ phase: "Downloading audio…", done: ++done, total });
    }
  };
  await Promise.all(Array.from({ length: 4 }, worker));
  if (failed) throw new Error(`${failed} audio files failed. They will be retried on the next sync.`);

  await db.put("library", { id: `pack:${meta.id}`, packId: meta.id, kind: "clips", title: m.title, clips: m.clips, version: meta.version });
  return merged;
}
