// Weekly plan. Session 1 / Session 2 are the two columns of the source table.
// `kind` decides where a task opens; `timed` tasks auto-complete when the timer reaches `min`.
export const KINDS = {
  anki:      { label: "Anki",                icon: "cards",      route: "/cards/study", timed: true },
  grammar:   { label: "Grammar",             icon: "video",      route: "/task",        timed: true },
  podcast:   { label: "Podcast",             icon: "headphones", route: "/task",        timed: false, external: true },
  intensive: { label: "Intensive listening", icon: "headphones", route: "/practice/listen", timed: true },
  shadowing: { label: "Shadowing",           icon: "mic",        route: "/practice/shadow", timed: true },
  reading:   { label: "Reading",             icon: "book",       route: "/practice/read",   timed: true },
  phrases:   { label: "Add new phrases",     icon: "plus",       route: "/add",         timed: true },
  notes:     { label: "Review tutor notes",  icon: "note",       route: "/task",        timed: false },
  music:     { label: "Podcast or music",    icon: "music",      route: "/task",        timed: false, external: true },
};

const t = (kind, min, detail = "") => ({ id: kind, kind, min, detail });
const anki = t("anki", 10, "Vocabulary reviews");

// Index = Date#getDay(): 0 Sun … 6 Sat
export const PLAN = {
  1: [ [anki, { ...t("grammar", 20, "Video or app exercises on this week's topic") }],
       [{ ...t("podcast", 30, "Extensive listening, in your podcast app") }] ],
  2: [ [anki, t("intensive", 20, "5–10 min of audio with transcript")],
       [t("reading", 20, "Article on your phone"), t("phrases", 10, "5 new phrases")] ],
  3: [ [anki, t("shadowing", 20, "10–20 s clips: play, pause, repeat aloud")],
       [t("podcast", 30), t("notes", null, "Quick review before your tutor lesson")] ],
  4: [ [anki, t("grammar", 20, "Grammar exercises")],
       [t("intensive", 20, "A different episode"), t("phrases", 10, "New phrases")] ],
  5: [ [anki, t("reading", 20)],
       [t("music", 30, "Podcast or music in Spanish, a relaxed end to the week")] ],
  // Weekends: Anki only, so the review pile never grows.
  6: [ [anki] ],
  0: [ [anki] ],
};

export const ORBS = { 0: "mint", 1: "mint", 2: "peach", 3: "lavender", 4: "sky", 5: "rose", 6: "peach" };

export function sessionsFor(date = new Date()) {
  return PLAN[date.getDay()].map((tasks, i) => ({
    name: `Session ${i + 1}`,
    tasks: tasks.map((task) => ({ ...task, id: `s${i + 1}-${task.id}` })),
  }));
}

export const allTasks = (date) => sessionsFor(date).flatMap((s) => s.tasks);
export const totalMinutes = (date) => allTasks(date).reduce((n, x) => n + (x.min || 0), 0);
