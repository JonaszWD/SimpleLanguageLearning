// Grammar practice (Mondays and Thursdays): explanation (2-3 min read) → exercises → write 5 sentences.
import { h, icon, toast, startOfDay } from "../util.js";
import * as db from "../db.js";
import * as G from "../grammar.js";
import { topNav, timerFor, empty } from "./shared.js";

const SESSION_SIZE = 10;
export const norm = (s) => s.normalize("NFC").toLowerCase().replace(/[¿¡?!.,;:«»“”"'()]/g, "").replace(/\s+/g, " ").trim();
export const isRight = (ex, given) => [ex.answer, ...(ex.alternatives || [])].some((a) => norm(a) === norm(given));
const shuffle = (a) => { a = [...a]; for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; };

/** Current topic ~60%, the rest from topics that need work (below 70%) or earlier topics. */
async function buildSession(focusId) {
  const all = await G.topics();
  const cur = focusId ? all.find((t) => t.id === focusId) : await G.currentTopic();
  const st = await G.stats();
  const attempts = await db.getAll("attempts");
  const seen = new Map();
  for (const a of attempts) seen.set(a.exId, (seen.get(a.exId) || 0) + 1);
  const fresh = (list) => shuffle(list).sort((a, b) => (seen.get(a.id) || 0) - (seen.get(b.id) || 0));

  const main = fresh(await G.exercisesFor(cur));
  const weakIds = st.flagged.map((r) => r.id).filter((id) => id !== cur.id);
  const earlier = (await G.unlocked()).filter((t) => t.id !== cur.id);
  const order = [...weakIds.map((id) => earlier.find((t) => t.id === id)).filter(Boolean),
                 ...earlier.filter((t) => !weakIds.includes(t.id)).sort((a, b) => (st.rows.find((r) => r.id === a.id)?.acc ?? 1) - (st.rows.find((r) => r.id === b.id)?.acc ?? 1))];
  const extra = [];
  for (const t of order) extra.push(...fresh(await G.exercisesFor(t)).slice(0, 4));

  // An explicitly chosen topic (?focus=, e.g. "Practise" in Stats) is practised on its own.
  const nMain = focusId || cur.type === "review" || !extra.length ? SESSION_SIZE : Math.round(SESSION_SIZE * 0.6);
  const picked = [...main.slice(0, nMain)];
  // Extras first (topics under 70% come first in `extra`), leftover current-topic items only as filler.
  const rest = [...extra, ...main.slice(nMain)];
  picked.push(...rest.slice(0, SESSION_SIZE - picked.length));
  return { topic: cur, items: shuffle(picked).slice(0, SESSION_SIZE), flagged: st.flagged };
}

function ruleList(title, items) {
  return h("section", { class: "stack" }, h("span", { class: "caption-uppercase muted" }, title),
    h("ul", { style: "margin:0;padding-left:20px;display:flex;flex-direction:column;gap:8px" }, items.map((r) => h("li", {}, r))));
}

export async function grammar(ctx) {
  const timer = await timerFor(ctx);
  const topics = await G.topics();
  if (!topics.length) {
    return h("div", {}, topNav("Grammar", "/today"),
      h("div", { class: "page has-top" }, empty("Grammar isn't downloaded yet", "Connect once and it syncs by itself. After that it works offline.",
        h("button", { class: "btn btn-outline", onClick: async () => { toast("Syncing…"); await G.syncGrammar().catch(() => {}); ctx.go("/grammar"); } }, "Sync now"))));
  }

  const root = h("div", {});
  const body = h("div", { class: "page has-top" });
  root.append(topNav("Grammar", "/today"), body);
  const show = (...kids) => body.replaceChildren(...kids.flat().filter(Boolean));
  const timerCard = timer && h("div", { class: "feature-card" }, timer.el);

  let session = await buildSession(ctx.query.focus);
  const { topic } = session;
  const week = topic.week;
  const noExercises = !session.items.length;

  // ── 1. explanation ──
  let lang = "en";
  function intro() {
    const expl = h("p", { class: "title-sm", style: "font-weight:400" }, topic.explanation[lang]);
    const langBtn = h("button", { class: "btn btn-text", onClick: () => { lang = lang === "en" ? "es" : "en"; expl.textContent = topic.explanation[lang]; langBtn.textContent = lang === "en" ? "Ver en español" : "Show in English"; } }, "Ver en español");
    const flag = session.flagged.find((r) => r.id === topic.id);
    show(
      timerCard,
      h("section", { class: "gradient-orb-card orb-lavender stack" },
        h("span", { class: "badge-pill", style: "align-self:flex-start" }, `Week ${week} · ${topic.level}`),
        h("h1", { class: "display-md" }, topic.title.en),
        h("p", { class: "caption muted" }, topic.title.es + " · 2–3 min read")),
      session.flagged.length && h("div", { class: "feature-card stack" },
        h("span", { class: "title-sm" }, "Extra practice"),
        h("p", { class: "body-sm" }, `Under 70% after two weeks: ${session.flagged.map((r) => `${r.title} (${Math.round(r.acc * 100)}%)`).join(", ")}. They are mixed into your sessions.`),
        flag && h("button", { class: "btn btn-outline", onClick: async () => { await G.repeatCurrentTopic(); toast("This topic repeats next week"); ctx.go("/grammar"); } }, "Repeat this topic next week")),
      h("div", { class: "stack" }, expl, langBtn),
      ruleList("Key rules", topic.key_rules),
      ruleList("Common mistakes for English speakers", topic.common_mistakes),
      h("button", { class: "btn btn-primary btn-block", onClick: () => (noExercises ? write() : run()) }, noExercises ? "Write sentences" : "Start exercises"),
      h("a", { class: "btn btn-text", href: "#/grammar/mistake" }, "Add a mistake from a tutor"));
  }

  // ── 2. exercises ──
  function run() {
    const items = session.items;
    const results = [];
    let i = 0;
    const next = () => (i >= items.length ? summary(results) : ask(items[i], i, items.length, results, () => { i++; next(); }));
    next();
  }

  function ask(ex, n, total, results, done) {
    const bar = h("div", { class: "progress" }, h("i", { style: `width:${(n / total) * 100}%` }));
    const feedback = h("div", { class: "stack", hidden: true });
    const controls = h("div", { class: "stack" });
    let answered = false;

    const finish = async (given) => {
      if (answered) return;
      answered = true;
      const correct = isRight(ex, given);
      results.push({ ex, given, correct });
      await G.logAttempt({ exId: ex.id, topic: ex.topic, type: ex.type, correct, given, via: "practice" });
      let carded = false;
      if (!correct) carded = await G.logMistake({ ex: ex.id, topic: ex.topic, type: ex.type, given, correct: ex.answer, sentence: G.correctSentence(ex) });
      controls.querySelectorAll("button,input,textarea").forEach((el) => (el.disabled = true));
      feedback.hidden = false;
      feedback.replaceChildren(
        h("div", { class: `feature-card stack` },
          h("span", { class: `title-sm ${correct ? "success" : "error"}` }, correct ? "Correct" : "Not quite"),
          !correct && h("p", {}, h("span", { class: "muted" }, "Answer: "), h("b", {}, ex.answer)),
          !correct && ex.alternatives?.length ? h("p", { class: "caption muted" }, "Also accepted: " + ex.alternatives.join(" · ")) : null,
          ex.explanation && h("p", { class: "body-sm" }, ex.explanation),
          ex.translation && h("p", { class: "caption muted" }, ex.translation),
          ex.confidence !== "high" && h("p", { class: "caption muted" }, "Flagged for review: if this looks wrong, it may be."),
          !correct && carded && h("p", { class: "caption muted" }, "Added to your Anki mistake cards."),
          h("p", { class: "caption muted" }, ex.source === "tatoeba" ? `Sentence: Tatoeba #${ex.source_ids.tatoeba_es} (CC BY 2.0 FR)` : ex.source === "wiktionary" ? "Forms: Wiktionary (CC BY-SA)" : "Generated by Claude")),
        h("button", { class: "btn btn-primary btn-block", onClick: done }, n + 1 === total ? "See results" : "Next"));
      feedback.scrollIntoView({ block: "nearest", behavior: "smooth" });
    };

    const promptLine = h("span", { class: "caption-uppercase muted" }, ex.prompt);
    const hint = ex.hint && ex.type !== "multiple_choice" && h("span", { class: "badge-pill", style: "align-self:flex-start" }, ex.hint);
    if (ex.type === "multiple_choice") {
      controls.append(...ex.options.map((o) => h("button", { class: "btn btn-outline btn-block", onClick: () => finish(o) }, o)));
    } else {
      const long = ex.type === "transformation" || ex.type === "error_correction";
      const input = long
        ? h("textarea", { class: "text-input", rows: 2, autocapitalize: "sentences", spellcheck: "false" }, ex.text)
        : h("input", { class: "text-input", autocapitalize: "none", autocomplete: "off", spellcheck: "false", placeholder: "Your answer" });
      const check = h("button", { class: "btn btn-primary btn-block", onClick: () => input.value.trim() && finish(input.value) }, "Check");
      if (!long) input.addEventListener("keydown", (e) => { if (e.key === "Enter") check.click(); });
      controls.append(input, check);
      queueMicrotask(() => input.focus({ preventScroll: true }));
    }
    show(timerCard, bar,
      h("p", { class: "caption muted" }, `${n + 1} / ${total} · ${topicTitle(ex.topic)}`),
      promptLine, hint,
      ex.type === "cloze" || ex.type === "multiple_choice" ? h("p", { class: "gx-text" }, blankText(ex.text))
        : ex.text ? h("p", { class: "caption muted" }, "Edit the sentence below.") : null,
      controls, feedback);
  }

  const titles = Object.fromEntries(topics.map((t) => [t.id, t.title.en]));
  const topicTitle = (id) => titles[id] || id;
  const blankText = (t) => t.split("____").flatMap((part, k, arr) => (k < arr.length - 1 ? [part, h("span", { class: "gx-blank" }, "      ")] : [part]));

  // ── 3. summary + write 5 sentences ──
  function summary(results) {
    const ok = results.filter((r) => r.correct).length;
    const missed = results.filter((r) => !r.correct);
    show(timerCard,
      h("section", { class: "gradient-orb-card orb-peach stack" },
        h("span", { class: "caption-uppercase muted" }, "Results"),
        h("h1", { class: "display-lg" }, `${ok} / ${results.length}`)),
      missed.length ? h("div", { class: "feature-card stack" },
        h("span", { class: "title-sm" }, "To remember"),
        missed.map((r) => h("p", { class: "body-sm" }, h("b", {}, r.ex.type === "cloze" ? r.ex.text.replace("____", r.ex.answer) : r.ex.answer), r.ex.hint ? ` (${r.ex.hint})` : ""))) : h("p", {}, "No mistakes. Nice."),
      h("button", { class: "btn btn-primary btn-block", onClick: write }, "Write 5 sentences"),
      h("button", { class: "btn btn-outline btn-block", onClick: async () => { session = await buildSession(ctx.query.focus); run(); } }, "More exercises"),
      timer && h("button", { class: "btn btn-text", onClick: async () => { await timer.markDone(); ctx.go("/today"); } }, "Mark task done"));
  }

  async function write() {
    const start = await G.weekStartOf(week);
    const saved = (await db.byIndex("sentences", "topic", topic.id)).filter((x) => x.ts >= start);
    if (saved.length >= 5) {
      show(timerCard, h("div", { class: "feature-card stack" }, h("span", { class: "title-sm" }, "This week's sentences"),
        saved.map((x) => h("p", {}, x.text))),
        h("button", { class: "btn btn-primary btn-block", onClick: () => ctx.go("/today") }, "Done"));
      return;
    }
    const inputs = [...Array(5 - saved.length)].map((_, k) => h("textarea", { class: "text-input", rows: 2, placeholder: `Sentence ${saved.length + k + 1}`, spellcheck: "false" }));
    show(timerCard,
      h("h1", { class: "display-md" }, "Write 5 sentences"),
      h("p", {}, `Make up 5 original sentences about your own life using: ${topic.title.en}. Don't copy the examples.`),
      saved.length ? h("p", { class: "caption muted" }, `${saved.length} saved already this week.`) : null,
      h("div", { class: "stack" }, inputs),
      h("button", { class: "btn btn-primary btn-block", onClick: async () => {
        const texts = inputs.map((x) => x.value.trim()).filter(Boolean);
        if (!texts.length) { toast("Write at least one sentence"); return; }
        await db.putMany("sentences", texts.map((text) => ({ topic: topic.id, week, text, ts: Date.now() })));
        toast(`${texts.length} saved`);
        if (timer) await timer.markDone();
        ctx.go("/today");
      } }, "Save"),
      h("button", { class: "btn btn-text", onClick: () => ctx.go("/today") }, "Later"));
  }

  intro();
  return root;
}

// ── quick "add a mistake" (e.g. from a tutor correction) ────────────────────
export async function addMistake(ctx) {
  const topics = (await G.topics()).filter((t) => t.type !== "review");
  const wrong = h("textarea", { class: "text-input", rows: 2, placeholder: "What I said or wrote", spellcheck: "false" });
  const right = h("textarea", { class: "text-input", rows: 2, placeholder: "The correct version", spellcheck: "false" });
  const sel = h("select", { class: "select-pill", "aria-label": "Topic" },
    h("option", { value: "" }, "Topic: not sure"), topics.map((t) => h("option", { value: t.id }, t.title.en)));
  const save = async () => {
    const w = wrong.value.trim(), r = right.value.trim();
    if (!r) { toast("Add the correct version"); return; }
    const ok = await G.logMistake({ topic: sel.value || null, type: "manual", given: w, correct: r, via: "manual", sentence: { wrong: w, right: r }, force: true });
    toast(ok ? "Saved. Card added." : "Saved");
    wrong.value = right.value = "";
    wrong.focus();
  };
  queueMicrotask(() => wrong.focus());
  return h("div", {}, topNav("Add a mistake", "/today"),
    h("div", { class: "page has-top" },
      h("h1", { class: "display-md" }, "Add a mistake"),
      h("p", { class: "muted" }, "Two fields and Save. The corrected sentence becomes a cloze card."),
      h("div", { class: "stack" }, wrong, right, sel, h("button", { class: "btn btn-primary btn-block", onClick: save }, "Save"))));
}
