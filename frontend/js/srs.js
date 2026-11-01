// Anki v2-style scheduler: learning steps, SM-2 ease, lapses, daily limits.
import { addDays, startOfDay } from "./util.js";

const MIN = 60_000;
const LEARN_AHEAD = 20 * MIN;

export function newCardState(c, now = Date.now()) {
  return { kind: "new", step: 0, due: null, ivl: 0, ease: null, reps: 0, lapses: 0, suspended: false, ...c };
}

function reviewDue(ivl, now) {
  return addDays(startOfDay(new Date(now)), ivl);
}

function stepDue(mins, now) {
  return now + mins * MIN;
}

function hardDelay(steps, step) {
  if (step === 0 && steps.length > 1) return (steps[0] + steps[1]) / 2;
  if (step === 0) return steps[0] * 1.5;
  return steps[step];
}

// Pure: returns the card as it would be after answering. rating: 1 again, 2 hard, 3 good, 4 easy
export function answer(card, rating, s, now = Date.now()) {
  const c = { ...card, reps: card.reps + 1 };

  if (c.kind === "new") {
    c.kind = "learning";
    c.step = 0;
    c.ease = s.startEase;
  }

  if (c.kind === "learning" || c.kind === "relearn") {
    const steps = c.kind === "learning" ? s.learnSteps : s.relearnSteps;
    const graduate = (ivl) => {
      c.kind = "review";
      c.ivl = ivl;
      c.step = 0;
      c.due = reviewDue(ivl, now);
    };
    if (steps.length === 0) {
      graduate(c.kind === "learning" ? s.graduatingIvl : Math.max(c.ivl, 1));
    } else if (rating === 1) {
      c.step = 0;
      c.due = stepDue(steps[0], now);
    } else if (rating === 2) {
      c.due = stepDue(hardDelay(steps, c.step), now);
    } else if (rating === 3) {
      if (c.step + 1 >= steps.length) graduate(c.kind === "learning" ? s.graduatingIvl : Math.max(c.ivl, 1));
      else { c.step += 1; c.due = stepDue(steps[c.step], now); }
    } else {
      graduate(c.kind === "learning" ? s.easyIvl : Math.max(c.ivl, 1) + 1);
    }
    return c;
  }

  // review
  const mod = s.intervalModifier;
  if (rating === 1) {
    c.lapses += 1;
    c.ease = Math.max(1.3, c.ease - 0.2);
    c.ivl = 1;
    if (s.relearnSteps.length) {
      c.kind = "relearn";
      c.step = 0;
      c.due = stepDue(s.relearnSteps[0], now);
    } else {
      c.due = reviewDue(c.ivl, now);
    }
    return c;
  }
  const hard = Math.max(c.ivl + 1, Math.round(c.ivl * s.hardFactor * mod));
  const good = Math.max(hard + 1, Math.round(c.ivl * c.ease * mod));
  const easy = Math.max(good + 1, Math.round(c.ivl * c.ease * s.easyBonus * mod));
  if (rating === 2) { c.ease = Math.max(1.3, c.ease - 0.15); c.ivl = hard; }
  else if (rating === 3) { c.ivl = good; }
  else { c.ease += 0.15; c.ivl = easy; }
  c.due = reviewDue(c.ivl, now);
  return c;
}

export function fmtInterval(ms) {
  const mins = ms / MIN;
  if (mins < 1) return "<1m";
  if (mins < 60) return `${Math.round(mins)}m`;
  if (mins < 1440) return `${Math.round(mins / 60)}h`;
  const days = mins / 1440;
  if (days < 30) return `${Math.round(days)}d`;
  if (days < 365) return `${(days / 30).toFixed(1).replace(/\.0$/, "")}mo`;
  return `${(days / 365).toFixed(1).replace(/\.0$/, "")}y`;
}

export function previews(card, s, now = Date.now()) {
  return [1, 2, 3, 4].map((r) => {
    const after = answer(card, r, s, now);
    return fmtInterval(after.kind === "review" ? after.ivl * 86_400_000 : after.due - now);
  });
}

/**
 * How many new cards to show today. About `grammarShare` (15%) of the daily new cards are grammar or
 * mistake cards; if there aren't enough of them, vocabulary fills the rest (and vice versa).
 */
export function newAllowance(availGrammar, availOther, s, day) {
  const total = Math.max(0, s.newPerDay - day.newDone);
  const quota = Math.max(0, Math.round(s.newPerDay * (s.grammarShare ?? 0.15)) - (day.newGrammarDone || 0));
  const g = Math.min(availGrammar, quota, total);
  const o = Math.min(availOther, total - g);
  return { grammar: g, other: o, total: g + o };
}

export function countsFor(cards, s, day, now = Date.now()) {
  const endToday = addDays(startOfDay(new Date(now)), 1);
  let ng = 0, no = 0, l = 0, r = 0;
  for (const c of cards) {
    if (c.suspended) continue;
    if (c.kind === "new") (c.grammar ? ng++ : no++);
    else if (c.kind === "review") { if (c.due < endToday) r++; }
    else if (c.due <= now + LEARN_AHEAD) l++;
  }
  return {
    new: newAllowance(ng, no, s, day).total,
    learn: l,
    review: Math.min(r, Math.max(0, s.reviewsPerDay - day.revDone)),
  };
}

// In-memory study queue for one session over a set of cards.
export class Session {
  constructor(cards, s, day, now = Date.now()) {
    this.s = s;
    const endToday = addDays(startOfDay(new Date(now)), 1);
    const live = cards.filter((c) => !c.suspended);
    this.learning = live.filter((c) => c.kind === "learning" || c.kind === "relearn");
    this.reviews = shuffle(live.filter((c) => c.kind === "review" && c.due < endToday))
      .slice(0, Math.max(0, s.reviewsPerDay - day.revDone));
    const order = (a, b) => (a.pos ?? -1) - (b.pos ?? -1) || a.id - b.id;
    const fresh = live.filter((c) => c.kind === "new");
    const allow = newAllowance(fresh.filter((c) => c.grammar).length, fresh.filter((c) => !c.grammar).length, s, day);
    this.fresh = [
      ...fresh.filter((c) => !c.grammar).sort(order).slice(0, allow.other),
      ...fresh.filter((c) => c.grammar).sort(order).slice(0, allow.grammar),
    ];
  }

  next(now = Date.now()) {
    const due = this.learning.filter((c) => c.due <= now + LEARN_AHEAD).sort((a, b) => a.due - b.due)[0];
    if (due && due.due <= now) return due;
    return this.reviews[0] || this.fresh[0] || due || null;
  }

  // Apply a rating; returns { before, after } for persistence.
  apply(card, rating, now = Date.now()) {
    const after = answer(card, rating, this.s, now);
    for (const q of [this.learning, this.reviews, this.fresh]) {
      const i = q.indexOf(card);
      if (i >= 0) q.splice(i, 1);
    }
    if (after.kind === "learning" || after.kind === "relearn") this.learning.push(after);
    return { before: card, after };
  }

  get remaining() {
    return { new: this.fresh.length, learn: this.learning.length, review: this.reviews.length };
  }
}

function shuffle(a) {
  a = [...a];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}
