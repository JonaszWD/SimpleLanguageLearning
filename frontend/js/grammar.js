// Grammar: weekly syllabus topic, exercises, mistake log, mistake cards and accuracy stats.
// Scheduling reuses the app's Anki-style scheduler (srs.js): grammar items are ordinary cards.
import * as db from "./db.js";
import { grammarUrl } from "./config.js";
import { newCardState } from "./srs.js";
import { addDays, dateKey, startOfDay, uid } from "./util.js";

const DAY = 86_400_000;
export const MIN_ATTEMPTS = 8;      // before a topic's accuracy is judged
export const FLAG_BELOW = 0.7;      // "stays under 70% after two weeks"
export const FLAG_AFTER_DAYS = 14;
const CARDS_PER_TOPIC = 14;         // exercises turned into Anki cards per unlocked topic

const esc = (s) => String(s ?? "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

// ── sync ────────────────────────────────────────────────────────────────────
export async function syncGrammar() {
  const idxRes = await fetch(grammarUrl("/index.json"), { cache: "no-cache" });
  if (!idxRes.ok) return false;
  const index = await idxRes.json();
  const have = (await db.get("grammar", "meta"))?.version;
  if (have !== index.version) {
    const syl = await (await fetch(grammarUrl("/syllabus.json"), { cache: "no-cache" })).json();
    const exercises = [];
    for (const [id, t] of Object.entries(index.topics)) {
      if (!t.file) continue;
      const r = await fetch(grammarUrl(`/${t.file}`), { cache: "no-cache" });
      if (r.ok) exercises.push(...(await r.json()).exercises);
    }
    await db.put("grammar", { key: "syllabus", value: syl });
    await db.putMany("exercises", exercises);
    await db.put("grammar", { key: "meta", version: index.version });
    cache = null;
  }
  await ensureStart();
  await ensureCards();
  return true;
}

// ── syllabus + schedule ─────────────────────────────────────────────────────
let cache = null;
export async function topics(track = "b1-b2") {
  if (!cache) {
    const s = (await db.get("grammar", "syllabus"))?.value;
    cache = s ? s.tracks.find((t) => t.id === track).topics.sort((a, b) => a.week - b.week) : [];
  }
  return cache;
}

const mondayKey = (d) => dateKey(new Date(addDays(startOfDay(d), -((d.getDay() + 6) % 7))));
const parseKey = (k) => { const [y, m, d] = k.split("-").map(Number); return new Date(y, m - 1, d); };

export async function ensureStart() {
  const s = await db.getSettings();
  if (!s.grammarStart) { s.grammarStart = mondayKey(new Date()); await db.saveSettings(s); }
  return s.grammarStart;
}

/** Week number (1-based) of `date` in the syllabus, from the configurable start date. */
export function weekNumber(startKey, date = new Date()) {
  const days = Math.floor((startOfDay(date) - startOfDay(parseKey(startKey))) / DAY);
  return Math.floor(Math.max(0, days) / 7) + 1;
}

export async function currentWeek(date = new Date()) {
  const s = await db.getSettings();
  const t = await topics();
  const w = weekNumber(s.grammarStart || mondayKey(date), date);
  return Math.min(w, t.at(-1)?.week ?? 1);
}

export async function currentTopic(date = new Date()) {
  const t = await topics();
  const w = await currentWeek(date);
  return t.find((x) => x.week === w) || t[0] || null;
}

export async function weekStartOf(week) {
  const s = await db.getSettings();
  return addDays(startOfDay(parseKey(s.grammarStart || mondayKey(new Date()))), 7 * (week - 1));
}

/** Topics that have started (week <= current), excluding review weeks. */
export async function unlocked(date = new Date()) {
  const w = await currentWeek(date);
  return (await topics()).filter((t) => t.week <= w && t.type !== "review");
}

export async function exercisesFor(topic) {
  const ids = topic.type === "review" ? topic.reviews : [topic.id];
  const out = [];
  for (const id of ids) out.push(...(await db.byIndex("exercises", "topic", id)));
  return out;
}

/** Hold the syllabus for a week (repeat the current topic) by moving the start date later. */
export async function repeatCurrentTopic() {
  const s = await db.getSettings();
  s.grammarStart = dateKey(new Date(addDays(startOfDay(parseKey(s.grammarStart)), 7)));
  await db.saveSettings(s);
}

// ── exercises → Anki cards ──────────────────────────────────────────────────
function hash52(str) {
  let h1 = 0x811c9dc5, h2 = 0x1b873593;
  for (let i = 0; i < str.length; i++) {
    const c = str.charCodeAt(i);
    h1 = Math.imul(h1 ^ c, 16777619) >>> 0;
    h2 = Math.imul(h2 ^ c, 0x85ebca6b) >>> 0;
  }
  return (h1 & 0x1fffff) * 4294967296 + h2;
}
const noteIdFor = (exId) => 2_000_000_000_000_000 + (hash52(exId) % 100_000_000_000_000);

const SOURCE = { tatoeba: "Tatoeba", wiktionary: "Wiktionary", llm: "LLM" };

export function exerciseFields(ex, title) {
  let text, answer = ex.answer;
  if (ex.type === "cloze") {
    const hint = ex.hint ? `::${esc(ex.hint)}` : "";
    text = esc(ex.text).replace("____", `{{c1::${esc(ex.answer)}${hint}}}`);
    if (ex.alternatives?.length) answer += ` (also: ${ex.alternatives.join(", ")})`;
  } else {
    const lines = [`<b>${esc(ex.prompt)}</b>`];
    if (ex.hint) lines.push(`(${esc(ex.hint)})`);
    if (ex.text) lines.push(esc(ex.text));
    if (ex.type === "multiple_choice") lines.push(ex.options.map((o, i) => `${String.fromCharCode(65 + i)}) ${esc(o)}`).join(" &nbsp; "));
    text = lines.join("<br>");
    answer = esc(ex.answer) + (ex.alternatives?.length ? `<br>(also: ${esc(ex.alternatives.join("; "))})` : "");
  }
  const sid = Object.entries(ex.source_ids || {}).map(([k, v]) => `${k}:${v}`).join(", ");
  return [text, answer, esc(ex.explanation), title, ex.level, SOURCE[ex.source] || ex.source, `${ex.id}${sid ? ` | ${sid}` : ""}`];
}

/** Create cards for every unlocked topic that doesn't have them yet. Idempotent. */
export async function ensureCards() {
  const have = new Set(await db.getAllKeys("notes"));
  const notes = [], cards = [];
  for (const t of await unlocked()) {
    const exs = (await exercisesFor(t)).sort((a, b) => a.id.localeCompare(b.id));
    // spread over types so a topic's cards aren't all one kind
    const byType = Object.groupBy ? Object.groupBy(exs, (e) => e.type) : exs.reduce((m, e) => ((m[e.type] ??= []).push(e), m), {});
    const order = []; let more = true;
    for (let i = 0; more; i++) {
      more = false;
      for (const list of Object.values(byType)) if (list[i]) { order.push(list[i]); more = true; }
    }
    order.slice(0, CARDS_PER_TOPIC).forEach((ex, i) => {
      const nid = noteIdFor(ex.id);
      if (have.has(nid)) return;
      notes.push({ id: nid, guid: ex.id, mid: ex.type === "cloze" ? db.MODEL_GRAMMAR_CLOZE : db.MODEL_GRAMMAR_BASIC,
                   fields: exerciseFields(ex, t.title.en), tags: ["grammar", t.id, t.level, ex.type.replace("_", "-")] });
      cards.push(newCardState({ id: nid + 1, nid, did: db.GRAMMAR_DECK_ID, ord: 0, grammar: true, pos: (100 - t.week) * 100 + i }));
    });
  }
  if (notes.length) { await db.putMany("notes", notes); await db.putMany("cards", cards); }
  return notes.length;
}

// ── attempts, mistakes, mistake cards ───────────────────────────────────────
export const logAttempt = (a) => db.put("attempts", { ...a, ts: Date.now() });

function clozeFromDiff(wrong, right) {
  // Hide the first word that differs between the wrong and the corrected sentence.
  const w = wrong.split(/\s+/), r = right.split(/\s+/);
  const i = r.findIndex((tok, k) => tok !== w[k]);
  const k = i < 0 ? r.length - 1 : i;
  const bare = (t) => t.replace(/^[¿¡"«(]+|[.,;:!?"»)…]+$/g, "");
  const tok = bare(r[k]);
  r[k] = r[k].replace(tok, `{{c1::${tok}}}`);
  return esc(r.join(" "));
}

/** The corrected sentence as a cloze card. Returns false when the daily cap is reached (unless forced). */
export async function createMistakeCard({ topic, level = "B1", wrong, right, note = "", source = "mistake", force = false }) {
  const s = await db.getSettings();
  const day = await db.getDay(dateKey());
  if (!force && (day.mistakeCards || 0) >= s.mistakeCardsPerDay) return false;
  const text = right ? clozeFromDiff(wrong || "", right) : "";
  if (!text.includes("{{c1::")) return false;
  const nid = uid();
  await db.put("notes", { id: nid, guid: `mistake-${nid}`, mid: db.MODEL_GRAMMAR_CLOZE,
    fields: [text, right, esc(note || (wrong ? `You wrote: ${wrong}` : "")), topic || "", level, "Mistake", source],
    tags: ["grammar", "mistake", ...(topic ? [topic] : [])] });
  await db.put("cards", newCardState({ id: nid + 1, nid, did: db.GRAMMAR_DECK_ID, ord: 0, grammar: true, pos: -1 }));
  day.mistakeCards = (day.mistakeCards || 0) + 1;
  await db.saveDay(day);
  return true;
}

/** Log a wrong answer. Auto cards are capped per day; manual ones (tutor corrections) are not. */
export async function logMistake({ ex, topic, type, given, correct, via = "practice", sentence, makeCard = true, force = false }) {
  await db.put("mistakes", { exId: ex ?? null, topic, type, given, correct, via, ts: Date.now() });
  if (!makeCard) return false;
  return createMistakeCard({ topic, wrong: sentence?.wrong ?? "", right: sentence?.right ?? "", force });
}

/** Corrected sentence for an exercise (what a mistake card should teach). */
export function correctSentence(ex) {
  if (ex.type === "cloze" || ex.type === "multiple_choice") return { wrong: ex.text.replace("____", "___"), right: ex.text.replace("____", ex.answer) };
  if (ex.type === "transformation" || ex.type === "error_correction") return { wrong: ex.text, right: ex.answer };
  return { wrong: "", right: "" };
}

// ── stats ───────────────────────────────────────────────────────────────────
export async function stats(date = new Date()) {
  const [ts, attempts, week] = [await topics(), await db.getAll("attempts"), await currentWeek(date)];
  const today = startOfDay(date);
  const rows = [];
  for (const t of ts.filter((x) => x.type !== "review" && x.week <= week)) {
    const a = attempts.filter((x) => x.topic === t.id);
    const correct = a.filter((x) => x.correct).length;
    const acc = a.length ? correct / a.length : null;
    const age = Math.floor((today - (await weekStartOf(t.week))) / DAY);
    rows.push({ id: t.id, title: t.title.en, week: t.week, attempts: a.length, correct, acc,
                flagged: acc !== null && a.length >= MIN_ATTEMPTS && acc < FLAG_BELOW && age >= FLAG_AFTER_DAYS });
  }
  const weakest = rows.filter((r) => r.attempts >= 3).sort((a, b) => a.acc - b.acc).slice(0, 3);
  // trend: accuracy per calendar week, last 6 weeks
  const trend = [];
  for (let i = 5; i >= 0; i--) {
    const from = addDays(today, -((date.getDay() + 6) % 7) - 7 * i), to = addDays(from, 7);
    const a = attempts.filter((x) => x.ts >= from && x.ts < to);
    trend.push({ from, n: a.length, acc: a.length ? a.filter((x) => x.correct).length / a.length : null });
  }
  return { rows, weakest, trend, flagged: rows.filter((r) => r.flagged) };
}
