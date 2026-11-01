// All user data lives in IndexedDB so the app works fully offline.
const NAME = "language-app";
const VERSION = 4;
let dbp;

export function open() {
  dbp ??= new Promise((resolve, reject) => {
    const req = indexedDB.open(NAME, VERSION);
    req.onupgradeneeded = (e) => {
      const db = req.result;
      const old = e.oldVersion;
      if (old < 1) {
        db.createObjectStore("decks", { keyPath: "id" });
        db.createObjectStore("models", { keyPath: "id" });
        const notes = db.createObjectStore("notes", { keyPath: "id" });
        notes.createIndex("guid", "guid");
        const cards = db.createObjectStore("cards", { keyPath: "id" });
        cards.createIndex("did", "did");
        cards.createIndex("nid", "nid");
        db.createObjectStore("revlog", { autoIncrement: true });
        db.createObjectStore("days", { keyPath: "date" });
        db.createObjectStore("settings", { keyPath: "key" });
        // Practice material (listening / shadowing / reading).
        const lib = db.createObjectStore("library", { keyPath: "id" });
        lib.createIndex("kind", "kind");
      }
      if (old < 2) db.createObjectStore("media", { keyPath: "name" }); // audio blobs for content packs
      if (old < 3) {
        // Grammar: syllabus + exercises (synced), and what the learner did with them.
        db.createObjectStore("grammar", { keyPath: "key" });
        const ex = db.createObjectStore("exercises", { keyPath: "id" });
        ex.createIndex("topic", "topic");
        db.createObjectStore("attempts", { autoIncrement: true }).createIndex("topic", "topic");
        db.createObjectStore("mistakes", { autoIncrement: true });
        db.createObjectStore("sentences", { autoIncrement: true }).createIndex("topic", "topic");
      }
      if (old < 4) {
        // Podcasts: plans + per-episode metadata/transcripts (audio lives in "media" as "ep:<id>"),
        // listening log, per-episode state (position, ratings), and sentences queued for shadowing.
        db.createObjectStore("podcast", { keyPath: "key" });
        db.createObjectStore("listens", { autoIncrement: true }).createIndex("day", "day");
        db.createObjectStore("epstate", { keyPath: "id" });
        db.createObjectStore("shadowq", { autoIncrement: true });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
  return dbp;
}

const wrap = (req) => new Promise((res, rej) => { req.onsuccess = () => res(req.result); req.onerror = () => rej(req.error); });

async function store(name, mode = "readonly") {
  return (await open()).transaction(name, mode).objectStore(name);
}

export const get = async (s, key) => wrap((await store(s)).get(key));
export const getAll = async (s) => wrap((await store(s)).getAll());
export const put = async (s, val) => wrap((await store(s, "readwrite")).put(val));
export const getAllKeys = async (s) => wrap((await store(s)).getAllKeys());
export const del = async (s, key) => wrap((await store(s, "readwrite")).delete(key));
export const count = async (s) => wrap((await store(s)).count());
export const byIndex = async (s, index, key) => wrap((await store(s)).index(index).getAll(key));

export async function putMany(s, vals) {
  const db = await open();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(s, "readwrite");
    const st = tx.objectStore(s);
    vals.forEach((v) => st.put(v));
    tx.oncomplete = resolve;
    tx.onerror = () => reject(tx.error);
  });
}

export async function delMany(s, keys) {
  const db = await open();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(s, "readwrite");
    keys.forEach((k) => tx.objectStore(s).delete(k));
    tx.oncomplete = resolve;
    tx.onerror = () => reject(tx.error);
  });
}

export const DEFAULT_SETTINGS = {
  newPerDay: 12,
  reviewsPerDay: 200,
  learnSteps: [1, 10],
  relearnSteps: [10],
  graduatingIvl: 1,
  easyIvl: 4,
  startEase: 2.5,
  easyBonus: 1.3,
  hardFactor: 1.2,
  intervalModifier: 1.0,
  language: "es",
  autoSync: true,
  mixAudio: true,
  devMode: false,
  // Grammar: ~15% of new cards are grammar/mistake cards; the syllabus advances one topic a week.
  grammarShare: 0.15,
  grammarStart: null,          // YYYY-MM-DD of week 1; set on first use to this week's Monday
  mistakeCardsPerDay: 3,
  // Weekday (1 = Monday) → what the listening task is. Extensive = long, no text; intensive = guided.
  listenMap: { 1: "extensive", 2: "intensive", 3: "extensive", 4: "intensive", 5: "extensive" },
  podcastKeepDays: 14,
};

export async function getSettings() {
  const row = await get("settings", "main");
  return { ...DEFAULT_SETTINGS, ...(row?.value || {}) };
}
export const saveSettings = (value) => put("settings", { key: "main", value });

// Per-day progress: { date, tasks: { [taskId]: { secs, done } }, newDone, revDone }
export async function getDay(date) {
  return (await get("days", date)) || { date, tasks: {}, newDone: 0, revDone: 0 };
}
export const saveDay = (day) => put("days", day);

const BASIC = [
  { id: 1, name: "Basic", cloze: false, css: "", fields: ["Front", "Back"],
    templates: [{ name: "Card 1", qfmt: "{{Front}}", afmt: "{{FrontSide}}<hr>{{Back}}" }] },
  { id: 2, name: "Basic (and reversed card)", cloze: false, css: "", fields: ["Front", "Back"],
    templates: [
      { name: "Card 1", qfmt: "{{Front}}", afmt: "{{FrontSide}}<hr>{{Back}}" },
      { name: "Card 2", qfmt: "{{Back}}", afmt: "{{FrontSide}}<hr>{{Front}}" },
    ] },
  { id: 3, name: "Cloze", cloze: true, css: "", fields: ["Text", "Extra"],
    templates: [{ name: "Cloze", qfmt: "{{cloze:Text}}", afmt: "{{cloze:Text}}<br>{{Extra}}" }] },
];

// Same fields and templates as the exported .apkg decks (backend/app/grammar/export_apkg.py).
export const GRAMMAR_DECK_ID = 7001;
export const MODEL_GRAMMAR_CLOZE = 4;
export const MODEL_GRAMMAR_BASIC = 5;
export const MODEL_PODCAST = 6;
export const PODCAST_DECK_ID = 7002;
const GRAMMAR_FIELDS = ["Text", "Answer", "Explanation", "Topic", "Level", "Source", "SourceID"];
const PODCAST_MODEL = { id: MODEL_PODCAST, name: "Podcast cloze", cloze: true, css: "", fields: ["Text", "Extra", "Source", "SourceID", "Audio"],
  templates: [{ name: "Cloze", qfmt: "{{cloze:Text}}", afmt: "{{cloze:Text}}<br>{{Audio}}<br><span class=\"hint\">{{Extra}}</span>" }] };
const GRAMMAR_MODELS = [
  { id: MODEL_GRAMMAR_CLOZE, name: "Grammar cloze", cloze: true, css: "", fields: GRAMMAR_FIELDS,
    templates: [{ name: "Cloze", qfmt: "{{cloze:Text}}", afmt: "{{cloze:Text}}<br><span class=\"hint\">{{Explanation}}</span>" }] },
  { id: MODEL_GRAMMAR_BASIC, name: "Grammar basic", cloze: false, css: "", fields: GRAMMAR_FIELDS,
    templates: [{ name: "Card 1", qfmt: "{{Text}}", afmt: "{{FrontSide}}<hr>{{Answer}}<br><span class=\"hint\">{{Explanation}}</span>" }] },
];

export async function seed() {
  const have = new Set((await getAll("models")).map((m) => m.id));
  await putMany("models", [...BASIC, ...GRAMMAR_MODELS, PODCAST_MODEL].filter((m) => !have.has(m.id)));
  if (!(await get("decks", 1))) await put("decks", { id: 1, name: "Default" });
  if (!(await get("decks", GRAMMAR_DECK_ID))) await put("decks", { id: GRAMMAR_DECK_ID, name: "Grammar" });
  if (!(await get("decks", PODCAST_DECK_ID))) await put("decks", { id: PODCAST_DECK_ID, name: "Podcasts" });
}
