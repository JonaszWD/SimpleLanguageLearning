// Weekly plan. Session 1 / Session 2 are the two columns of the source table.
// `kind` decides where a task opens; `timed` tasks auto-complete when the timer reaches `min`.
export const KINDS = {
  anki:      { label: "Anki",                icon: "cards",      route: "/cards/study", timed: true },
  grammar:   { label: "Grammar",             icon: "video",      route: "/grammar",     timed: true },
  podcast:   { label: "Extensive listening", icon: "headphones", route: "/podcast/listen",    timed: true },
  intensive: { label: "Intensive listening", icon: "headphones", route: "/podcast/intensive", timed: true },
  shadowing: { label: "Shadowing",           icon: "mic",        route: "/practice/shadow", timed: true },
  reading:   { label: "Reading",             icon: "book",       route: "/practice/read",   timed: true },
  phrases:   { label: "Add new phrases",     icon: "plus",       route: "/add",         timed: true },
  notes:     { label: "Review tutor notes",  icon: "note",       route: "/task",        timed: false },
  talk:      { label: "Talk",                icon: "mic",        route: "/talk",        timed: true },
  music:     { label: "Podcast or music",    icon: "music",      route: "/task",        timed: false, external: true },
};

const t = (kind, min, detail = "") => ({ id: kind, kind, min, detail });
const anki = t("anki", 10, "Vocabulary reviews");

// Index = Date#getDay(): 0 Sun … 6 Sat
export const PLAN = {
  1: [ [anki, { ...t("grammar", 20, "Video or app exercises on this week's topic") }],
       [t("listen", 30)] ],
  2: [ [anki, t("listen", 20)],
       [t("reading", 20, "Article on your phone"), t("phrases", 10, "5 new phrases")] ],
  3: [ [anki, t("shadowing", 20, "10–20 s clips: play, pause, repeat aloud")],
       [t("listen", 30), t("notes", null, "Quick review before your tutor lesson")] ],
  4: [ [anki, t("grammar", 20, "Grammar exercises")],
       [t("listen", 20), t("phrases", 10, "New phrases")] ],
  5: [ [anki, t("reading", 20)],
       [t("listen", 30)] ],
  // Saturday adds a conversation; Sunday is Anki only, so the review pile never grows.
  6: [ [anki], [t("talk", 15, "Free conversation with an AI partner")] ],
  0: [ [anki] ],
};

export const ORBS = { 0: "coral", 1: "mint", 2: "peach", 3: "lavender", 4: "sky", 5: "rose", 6: "blue" };

// What the listening task is on each weekday (ISO: 1 = Monday). Set from the settings at startup.
const DEFAULT_LISTEN = { 1: "extensive", 2: "intensive", 3: "extensive", 4: "intensive", 5: "extensive" };
let listenMap = DEFAULT_LISTEN;
export const setListenMap = (m) => { listenMap = m || DEFAULT_LISTEN; };
export const listenModeFor = (date) => listenMap[date.getDay() || 7] || "none";

// "listen" is a placeholder: extensive (30 min, no text) or intensive (20 min, guided), or nothing.
function resolve(task, date) {
  if (task.kind !== "listen") return task;
  const mode = listenModeFor(date);
  if (mode === "extensive") return { ...task, kind: "podcast", min: 30, detail: "Podcast, no text. Skip ahead or stop whenever." };
  if (mode === "intensive") return { ...task, kind: "intensive", min: 20, detail: "One 5–10 min segment, three listens" };
  return null;
}

export function sessionsFor(date = new Date()) {
  return PLAN[date.getDay()].map((tasks, i) => ({
    name: `Session ${i + 1}`,
    tasks: tasks.map((task) => resolve(task, date)).filter(Boolean).map((task) => ({ ...task, id: `s${i + 1}-${task.kind}` })),
  })).filter((s) => s.tasks.length);
}

export const allTasks = (date) => sessionsFor(date).flatMap((s) => s.tasks);
export const totalMinutes = (date) => allTasks(date).reduce((n, x) => n + (x.min || 0), 0);
