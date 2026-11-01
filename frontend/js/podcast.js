// Podcasts: today's/tomorrow's plan from the server, offline copies in IndexedDB, listening log,
// phrase cards, ratings and the shadowing queue. Audio is kept on this phone only (personal use).
import * as db from "./db.js";
import { apiUrl } from "./config.js";
import { newCardState } from "./srs.js";
import { addDays, dateKey, startOfDay, uid } from "./util.js";

const api = (path) => apiUrl(`/podcasts${path}`);
export const epKey = (id) => `ep:${id}`;
const esc = (s) => String(s ?? "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
export const fmtTime = (t) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;
const ISO_DAY = (d) => d.getDay() || 7;

export function mapToParam(map) {
  const code = { extensive: "e", intensive: "i", none: "n" };
  return Object.entries(map).map(([d, m]) => `${d}:${code[m] || "n"}`).join(",");
}

// ── plan + readiness ────────────────────────────────────────────────────────
export async function serverUp() {
  try { return (await fetch(api("/status"), { cache: "no-store" })).ok; } catch { return false; }
}

export async function loadPlan(date) {
  const s = await db.getSettings();
  const key = dateKey(date);
  try {
    const q = new URLSearchParams({ date: key, start: s.grammarStart || key, map: mapToParam(s.listenMap) });
    const r = await fetch(api(`/plan?${q}`), { cache: "no-store" });
    if (r.ok) {
      const plan = await r.json();
      await db.put("podcast", { key: `plan:${key}`, value: plan, at: Date.now() });
      return plan;
    }
  } catch { /* offline: use the copy from the last sync */ }
  return (await db.get("podcast", `plan:${key}`))?.value || null;
}

export const cachedPlan = async (date) => (await db.get("podcast", `plan:${dateKey(date)}`))?.value || null;

export async function localEpisode(id) {
  const [rec, media, state] = await Promise.all([db.get("podcast", `ep:${id}`), db.get("media", epKey(id)), db.get("epstate", id)]);
  return { meta: rec?.value?.meta || null, transcript: rec?.value?.transcript || null, hasAudio: !!media, state: state || { id } };
}

/** "Ready for offline": every episode of that day's plan has its audio (and transcript, for intensive). */
export async function readiness(date) {
  const plan = await cachedPlan(date);
  if (!plan || !plan.items.length) return { planned: 0, ready: 0, all: false, plan };
  let ready = 0;
  for (const it of plan.items) {
    const e = await localEpisode(it.episode);
    if (e.hasAudio && (it.mode !== "intensive" || e.transcript?.timed)) ready++;
  }
  return { planned: plan.items.length, ready, all: ready === plan.items.length, plan };
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function downloadEpisode(item, onProgress) {
  const id = item.episode;
  const meta = await (await fetch(api(`/episodes/${id}`))).json();
  onProgress?.({ phase: `Podcast: ${item.show}` });
  const audio = await fetch(api(`/episodes/${id}/audio`));
  if (!audio.ok) return false;
  await db.put("media", { name: epKey(id), blob: await audio.blob() });
  let transcript = null;
  const tr = await fetch(api(`/episodes/${id}/transcript`));
  if (tr.ok) transcript = await tr.json();
  await db.put("podcast", { key: `ep:${id}`, value: { meta: { ...meta, ...pick(item, ["show", "level", "accent"]) }, transcript } });
  const st = (await db.get("epstate", id)) || { id };
  await db.put("epstate", { ...st, feed: meta.feed, level: item.level, title: meta.title, show: item.show, link: meta.link });
  return true;
}
const pick = (o, ks) => Object.fromEntries(ks.map((k) => [k, o[k]]));

/** Open any episode on demand: server downloads + transcribes it, then it is copied to the phone. */
export async function fetchEpisode(ep, mode, onProgress) {
  const local = await localEpisode(ep.id);
  if (local.hasAudio && (mode !== "intensive" || local.transcript?.timed)) return true;
  if (!(await serverUp())) return false;
  const item = { episode: ep.id, show: ep.show, level: ep.level, accent: ep.accent };
  let e = await (await fetch(api(`/episodes/${ep.id}`))).json();
  if (!(e.ready && (mode !== "intensive" || e.transcript?.timed))) {
    await fetch(api("/prepare"), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ episodes: [ep.id] }) });
    for (let i = 0; i < 60; i++) {
      onProgress?.(i < 2 ? "Downloading and transcribing on the server…" : `Still transcribing… ${i * 5}s`);
      await sleep(5000);
      e = await (await fetch(api(`/episodes/${ep.id}`))).json();
      if (e.ready && (mode !== "intensive" || e.transcript?.timed)) break;
    }
  }
  if (!e.ready) return false;
  return downloadEpisode(item, (p) => onProgress?.(p.phase));
}

/** Download what today's and tomorrow's plans need. The server prepares it (audio, transcript) first. */
export async function syncPodcasts(onProgress) {
  if (!(await serverUp())) return false;
  for (const day of [new Date(), new Date(addDays(startOfDay(new Date()), 1))]) {
    const plan = await loadPlan(day);
    for (const it of plan?.items || []) {
      const local = await localEpisode(it.episode);
      if (local.hasAudio && (it.mode !== "intensive" || local.transcript?.timed)) continue;
      let ready = it.ready;
      if (!ready) {
        await fetch(api("/prepare"), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ episodes: [it.episode] }) });
        for (let i = 0; i < 24 && !ready; i++) {          // up to ~2 minutes; the server keeps going in the background
          onProgress?.({ phase: `Preparing ${it.show} on the server…` });
          await sleep(5000);
          const e = await (await fetch(api(`/episodes/${it.episode}`))).json();
          ready = e.ready && (it.mode !== "intensive" || e.transcript?.timed);
        }
      }
      if (ready) await downloadEpisode(it, onProgress);
    }
  }
  await cleanupLocal();
  return true;
}

/** Drop audio of episodes listened more than `podcastKeepDays` ago. */
export async function cleanupLocal() {
  const keep = ((await db.getSettings()).podcastKeepDays ?? 14) * 86_400_000;
  for (const st of await db.getAll("epstate")) {
    if (st.listenedAt && Date.now() - st.listenedAt > keep && await db.get("media", epKey(st.id))) {
      await db.del("media", epKey(st.id));
      await db.del("podcast", `ep:${st.id}`);
    }
  }
}

// ── state, ratings, listening log ───────────────────────────────────────────
export async function saveState(id, patch) {
  const st = (await db.get("epstate", id)) || { id };
  const next = { ...st, ...patch };
  await db.put("epstate", next);
  return next;
}

export async function markListened(id) {
  await saveState(id, { listenedAt: Date.now(), position: 0 });
  fetch(api("/listened"), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ episode: id }) }).catch(() => {});
}

export async function rateEpisode(id, rating) {
  await saveState(id, { rating, ratingSynced: false });
  try {
    const r = await fetch(api("/ratings"), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ episode: id, rating }) });
    if (r.ok) await saveState(id, { ratingSynced: true });
  } catch { /* sent on the next sync */ }
}

export async function flushRatings() {
  for (const st of await db.getAll("epstate")) if (st.rating && st.ratingSynced === false) await rateEpisode(st.id, st.rating);
}

export async function logListen({ epId, mode, secs, follow = null }) {
  if (secs < 5 && follow == null) return;
  const st = (await db.get("epstate", epId)) || {};
  await db.put("listens", { day: dateKey(), ts: Date.now(), epId, feed: st.feed, level: st.level || "?", mode, secs: Math.round(secs), follow });
}

// ── phrase cards ────────────────────────────────────────────────────────────
function hash(s) { let h = 0; for (const c of s) h = (Math.imul(31, h) + c.charCodeAt(0)) | 0; return Math.abs(h).toString(36); }

/** Save a word/phrase as a cloze card: the transcript sentence with the phrase blanked, plus a short clip. */
export async function savePhrase({ epId, sentence, phrase, start, end }) {
  const st = (await db.get("epstate", epId)) || {};
  const at = sentence.indexOf(phrase);
  if (at < 0) throw new Error("phrase not in sentence");
  const text = esc(sentence.slice(0, at)) + `{{c1::${esc(phrase)}}}` + esc(sentence.slice(at + phrase.length));
  const sourceId = `${st.feed || "podcast"}|${epId}|${start.toFixed(1)}`;
  const guid = `${sourceId}|${phrase}`;
  if ((await db.byIndex("notes", "guid", guid)).length) return { duplicate: true };
  let audio = "";
  try {
    const r = await fetch(api(`/episodes/${epId}/clip?start=${start}&end=${end}`));
    if (r.ok) {
      const name = `clip-${hash(sourceId)}.mp3`;
      await db.put("media", { name, blob: await r.blob() });
      audio = `[sound:${name}]`;
    }
  } catch { /* offline: card without a clip */ }
  const nid = uid();
  const extra = `${st.show || ""} · ${st.title || ""} · ${fmtTime(start)}`;
  await db.put("notes", { id: nid, guid, mid: db.MODEL_PODCAST, fields: [text, esc(extra), "Podcast", sourceId, audio], tags: ["podcast", st.feed || "podcast", st.level || "?"] });
  await db.put("cards", newCardState({ id: nid + 1, nid, did: db.PODCAST_DECK_ID, ord: 0 }));
  await saveState(epId, { saved: (st.saved || 0) + 1 });
  return { duplicate: false, clip: !!audio };
}

export const sendToShadow = (item) => db.put("shadowq", { ...item, ts: Date.now() });

// ── weekly summary ──────────────────────────────────────────────────────────
export async function weekSummary(now = new Date()) {
  const monday = addDays(startOfDay(now), -((now.getDay() + 6) % 7));
  const listens = await db.getAll("listens");
  const weeks = [];
  for (let i = 4; i >= 0; i--) {
    const from = addDays(monday, -7 * i), to = addDays(from, 7);
    const rows = listens.filter((l) => l.ts >= from && l.ts < to);
    weeks.push({ from, minutes: Math.round(rows.reduce((n, r) => n + r.secs, 0) / 60) });
  }
  const thisWeek = listens.filter((l) => l.ts >= monday);
  const byLevel = {};
  for (const l of thisWeek) byLevel[l.level] = (byLevel[l.level] || 0) + l.secs / 60;
  const notes = (await db.getAll("notes")).filter((n) => n.tags.includes("podcast") && n.id / 1000 >= monday);
  const follows = thisWeek.filter((l) => l.follow != null).map((l) => l.follow);
  return { weeks, byLevel, phrases: notes.length, follow: follows.length ? follows.reduce((a, b) => a + b, 0) / follows.length : null, followN: follows.length };
}
