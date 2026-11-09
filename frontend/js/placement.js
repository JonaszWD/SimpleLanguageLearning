// Placement test for new accounts: four questions per CEFR level, easiest first. A level is passed
// with 3 of 4 right; the test stops at the first level that isn't, so beginners answer only a few.
// The result decides where the grammar syllabus (B1 → B2) starts. It is a rough estimate, not an exam.
import { h } from "./util.js";
import * as db from "./db.js";
import { startAtWeek } from "./grammar.js";

export const LEVELS = ["A1", "A2", "B1", "B2", "C1"];
export const PASS_MARK = 3;
// First syllabus week for each placed level (see content/grammar/syllabus.json: 17 = first B2 topic).
const START_WEEK = { A1: 1, A2: 1, B1: 1, B2: 17, C1: 23 };

// [sentence with ____, [options], index of the right one]
export const QUESTIONS = {
  A1: [
    ["Yo ____ de Inglaterra.", ["soy", "estoy", "tengo", "hay"], 0],
    ["¿Cómo ____ llamas?", ["te", "tu", "ti", "tú"], 0],
    ["Mi casa es muy ____.", ["grande", "grandes", "grando", "grandas"], 0],
    ["Ella ____ en una oficina.", ["trabajo", "trabajas", "trabaja", "trabajan"], 2],
  ],
  A2: [
    ["Ayer ____ al cine con mis amigos.", ["voy", "fui", "iré", "vaya"], 1],
    ["Mañana ____ a visitar a mi abuela.", ["voy", "fui", "iba", "he ido"], 0],
    ["Me gusta ____ música.", ["el", "la", "los", "las"], 1],
    ["Mi hermano es ____ alto que yo.", ["más", "tanto", "muy", "mucho"], 0],
  ],
  B1: [
    ["Cuando era niño, ____ en el campo.", ["vivo", "viví", "vivía", "viviré"], 2],
    ["Ya ____ la cena cuando llegaste.", ["preparé", "había preparado", "preparo", "prepararé"], 1],
    ["Quiero que tú ____ conmigo.", ["vienes", "vengas", "vendrás", "venías"], 1],
    ["Es el libro ____ me recomendaste.", ["que", "quien", "cual", "cuyo"], 0],
  ],
  B2: [
    ["Si tuviera más tiempo, ____ un idioma nuevo.", ["aprendo", "aprenderé", "aprendería", "aprendí"], 2],
    ["Me alegro de que ____ aprobado el examen.", ["has", "hayas", "habías", "hubieras"], 1],
    ["No creo que ____ razón.", ["tiene", "tendrá", "tenga", "tuvo"], 2],
    ["El informe ____ por el director ayer.", ["presentó", "fue presentado", "estuvo presentando", "fue presentando"], 1],
  ],
  C1: [
    ["De haber sabido la verdad, no ____ nada.", ["digo", "habría dicho", "diré", "dije"], 1],
    ["Aunque ____ mucho, nunca lograría convencerlo.", ["insisto", "insistiera", "insistiré", "he insistido"], 1],
    ["Cuanto más lo pienso, ____ me convence.", ["menos", "tanto", "mucho", "nada"], 0],
    ["No es que no ____ ayudarte, sino que no puedo.", ["quiero", "quiera", "querré", "quise"], 1],
  ],
};

/** `scores` = right answers per level asked, in LEVELS order. Returns the highest level passed in a row. */
export function placeLevel(scores) {
  let placed = LEVELS[0];
  for (const [i, level] of LEVELS.entries()) {
    if ((scores[i] ?? 0) < PASS_MARK) break;
    placed = level;
  }
  return placed;
}

const shuffle = (a) => { a = [...a]; for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; };

export async function applyLevel(level) {
  const s = await db.getSettings();
  await db.saveSettings({ ...s, level });
  await startAtWeek(START_WEEK[level]);
}

/** Full-screen test. Resolves with the placed level, or null if skipped. */
export function runPlacement() {
  return new Promise((resolve) => {
    const frozen = [...document.body.children].filter((el) => el.tagName !== "SCRIPT");
    const box = h("div", { class: "lock-box stack" });
    const screen = h("div", { class: "lock-screen", role: "dialog", "aria-modal": "true", "aria-label": "Placement test" }, box);
    const close = (level) => { frozen.forEach((el) => el.removeAttribute("inert")); screen.remove(); resolve(level); };
    const total = LEVELS.length * QUESTIONS.A1.length;
    const scores = [];
    let li = 0, qi = 0, asked = 0, items = [], right = 0;

    const intro = () => {
      box.replaceChildren(
        h("h1", { class: "display-lg" }, "Find your level"),
        h("p", { class: "body-sm muted" }, "Up to 20 short questions, from easy to hard. It sets where your grammar course starts. If you don't know an answer, pick “I don't know” instead of guessing."),
        h("button", { class: "btn btn-primary btn-block", onClick: nextLevel }, "Start"),
        h("button", { class: "btn btn-outline btn-block", onClick: () => close(null) }, "Skip for now"));
    };

    const finish = () => {
      const level = placeLevel(scores);
      box.replaceChildren(
        h("span", { class: "caption-uppercase muted" }, "Your level"),
        h("h1", { class: "display-lg" }, level),
        h("p", { class: "body-sm muted" }, level === "A1" || level === "A2"
          ? "Your grammar course starts at week 1. You can retake this test any time in Settings."
          : "Your grammar course starts where it fits your level. You can retake this test any time in Settings."),
        h("button", { class: "btn btn-primary btn-block", onClick: () => close(level) }, "Continue"));
    };

    const nextLevel = () => {
      if (li >= LEVELS.length) return finish();
      items = shuffle(QUESTIONS[LEVELS[li]]);
      qi = 0; right = 0;
      ask();
    };

    const ask = () => {
      const [text, options, answer] = items[qi];
      const order = shuffle(options.map((o, i) => [o, i === answer]));
      const pick = (ok) => {
        if (ok) right++;
        asked++;
        if (++qi < items.length) return ask();
        scores[li++] = right;
        if (right < PASS_MARK) return finish();
        nextLevel();
      };
      box.replaceChildren(
        h("div", { class: "progress", role: "progressbar", "aria-valuemin": 0, "aria-valuemax": total, "aria-valuenow": asked }, h("i", { style: `width:${(asked / total) * 100}%` })),
        h("span", { class: "caption muted" }, `Question ${asked + 1}`),
        h("p", { class: "title-sm", style: "font-weight:400" }, text),
        ...order.map(([o, ok]) => h("button", { class: "btn btn-outline btn-block", onClick: () => pick(ok) }, o)),
        h("button", { class: "btn btn-text", onClick: () => pick(false) }, "I don't know"));
    };

    frozen.forEach((el) => el.setAttribute("inert", ""));
    document.body.append(screen);
    intro();
  });
}
