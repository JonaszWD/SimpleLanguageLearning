// All user data lives in IndexedDB so the app works fully offline.
const NAME = "language-app";
const VERSION = 2;
let dbp;

export function open() {
  dbp ??= new Promise((resolve, reject) => {
    const req = indexedDB.open(NAME, VERSION);
    req.onupgradeneeded = (e) => {
      const db = req.result;
      if (e.oldVersion >= 1) {
        // v1 -> v2: audio blobs for content packs
        db.createObjectStore("media", { keyPath: "name" });
        return;
      }
      db.createObjectStore("media", { keyPath: "name" });
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
      // Practice material (listening / shadowing / reading). Empty until content is decided.
      const lib = db.createObjectStore("library", { keyPath: "id" });
      lib.createIndex("kind", "kind");
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
  newPerDay: 20,
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

export async function seed() {
  if ((await getAll("models")).length === 0) await putMany("models", BASIC);
  if ((await getAll("decks")).length === 0) await put("decks", { id: 1, name: "Default" });
}
