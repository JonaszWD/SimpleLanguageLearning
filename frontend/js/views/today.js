import { h, icon, dateKey, addDays, startOfDay, toast } from "../util.js";
import * as db from "../db.js";
import { sessionsFor, KINDS, ORBS, totalMinutes } from "../plan.js";
import { currentTopic } from "../grammar.js";
import { readiness } from "../podcast.js";

const parseKey = (k) => {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(k || "");
  return m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : null;
};

export async function today(ctx) {
  const real = new Date();
  const dev = (await db.getSettings()).devMode;
  // Developer mode: ?d=YYYY-MM-DD previews any day of the plan, read-only.
  const preview = dev ? parseKey(ctx.query.d) : null;
  const now = preview || real;
  const isPreview = !!preview && dateKey(preview) !== dateKey(real);
  const date = dateKey(now);
  const day = await db.getDay(date);
  const sessions = sessionsFor(now);
  const tomorrow = new Date(addDays(startOfDay(real), 1));
  let readinessFailed = false;
  const rd = await readiness(tomorrow).catch(() => { readinessFailed = true; return null; });
  const gTopic = await currentTopic(now).catch(() => null); // optional detail: the row falls back to the plan's own text
  const tasks = sessions.flatMap((s) => s.tasks);
  const isDone = (t) => !!day.tasks[t.id]?.done;
  const doneCount = () => tasks.filter(isDone).length;
  const detailFor = (t) => (t.kind === "grammar" && gTopic ? `Week ${gTopic.week}: ${gTopic.title.en}` : t.detail);
  const metaFor = (t) => [t.min ? `${t.min} min` : null, detailFor(t)].filter(Boolean).join(" · ");

  const bar = h("i");
  const track = h("div", { class: "progress", role: "progressbar", "aria-label": "Tasks done today", "aria-valuemin": 0, "aria-valuemax": tasks.length }, bar);
  const summary = h("p", { class: "body-sm" }, tasks.length ? null : "Nothing planned for this day.");
  const dayName = (d) => d.toLocaleDateString("es", { weekday: "long" });
  const title = h("h1", { class: "display-lg" });
  const nextBar = h("div", { class: "next-bar" });
  const doneCard = h("section", { class: "feature-card done-card", hidden: true });

  // Tomorrow's plan, shown once today is finished.
  const tmrTasks = sessionsFor(tomorrow).flatMap((s) => s.tasks);
  doneCard.append(h("h2", { class: "title-sm" }, "Tomorrow"),
    tmrTasks.length
      ? h("ul", { class: "body-sm" }, tmrTasks.map((t) => h("li", {}, `${KINDS[t.kind].label}${t.min ? ` · ${t.min} min` : ""}`)))
      : h("p", { class: "body-sm" }, "Nothing planned."));

  const paint = () => {
    const n = doneCount();
    const all = tasks.length > 0 && n === tasks.length;
    bar.style.width = tasks.length ? `${(n / tasks.length) * 100}%` : "0%";
    track.setAttribute("aria-valuenow", n);
    track.setAttribute("aria-valuetext", `${n} of ${tasks.length} done, ${totalMinutes(now)} min planned`);
    title.textContent = isPreview ? "Vista previa" : all ? "¡Listo por hoy!" : "Hoy";
    doneCard.hidden = !(all && !isPreview);
    const next = isPreview ? null : tasks.find((t) => !isDone(t));
    nextBar.hidden = !next;
    nextBar.replaceChildren(...(next ? [h("a", { class: "btn btn-primary btn-lg", href: `#${KINDS[next.kind].route}?task=${next.id}` },
      h("span", {}, `${n ? "Continue" : "Start"} ${KINDS[next.kind].label}${next.min ? ` · ${next.min} min` : ""}`), icon("chevron"))] : []));
  };

  // Mon-Sun dots: filled check = all done, half = some done, ring = none. With Developer mode on, tapping a day previews it.
  const monday = addDays(startOfDay(real), -((real.getDay() + 6) % 7));
  const week = await Promise.all([...Array(7)].map(async (_, i) => {
    const d = new Date(addDays(monday, i));
    const key = dateKey(d);
    const rec = (await db.getDay(key)).tasks;
    const list = sessionsFor(d).flatMap((s) => s.tasks);
    const n = list.filter((t) => rec[t.id]?.done).length;
    const state = list.length && n === list.length ? "done" : n ? "part" : "";
    const name = dayName(d);
    const props = {
      class: `wk-day${key === dateKey(real) ? " today" : ""}`,
      ...(key === date ? { "aria-current": "date" } : {}),
      ...(dev ? { href: key === dateKey(real) ? "#/today" : `#/today?d=${key}` } : { role: "listitem" }),
    };
    return h(dev ? "a" : "div", props,
      h("span", { class: "dow", "aria-hidden": "true" }, d.toLocaleDateString("es", { weekday: "narrow" })),
      h("span", { class: `wk-dot ${state}`, "aria-hidden": "true" }, state === "done" ? icon("check") : null),
      h("span", { class: "sr-only" }, `${name}, ${list.length ? `${n} of ${list.length} done` : "nothing planned"}`));
  }));

  const hero = h("section", { class: `gradient-orb-card orb-${ORBS[now.getDay()]} stack` },
    h("div", { class: "row between hero-head" }, title,
      h("div", { class: "hero-day" },
        h("span", { class: "title-sm" }, dayName(now)),
        h("span", { class: "caption muted" }, now.toLocaleDateString("es", { day: "numeric", month: "long" })))),
    tasks.length ? track : summary,
    h("div", { class: "wk", ...(dev ? {} : { role: "list" }), "aria-label": "This week" }, week),
    isPreview && h("a", { class: "btn btn-outline", href: "#/today" }, "Back to today"));
  paint();

  const rowFor = (t) => {
    const k = KINDS[t.kind];
    const meta = metaFor(t);
    const check = h("button", { class: "check", role: "checkbox", "aria-checked": String(isDone(t)), "aria-label": `Mark ${k.label}${meta ? ` (${meta})` : ""} done`, disabled: isPreview, onClick: async (e) => {
      e.stopPropagation();
      const r = (day.tasks[t.id] ??= { secs: 0, done: false });
      const set = async (v) => {
        r.done = v;
        check.setAttribute("aria-checked", String(v));
        await db.saveDay(day);
        paint();
      };
      await set(!r.done);
      if (r.done) toast(`${k.label} marked done`, { label: "Undo", run: () => set(false) });
    } }, icon("check"));
    // Previews open the screens without a task, so no timer can write progress for another day.
    return h("div", { class: "list-row" },
      check,
      h("a", { class: "row grow", href: `#${k.route}${isPreview ? "" : `?task=${t.id}`}` },
        h("span", { class: "plate" }, icon(k.icon)),
        h("span", { class: "grow" },
          h("span", { class: "title-sm", style: "display:block" }, k.label),
          meta && h("span", { class: "caption muted meta" }, meta)),
        icon("chevron")));
  };

  const tomorrowCard = rd?.planned
    ? h("a", { class: "feature-card row between link-card", href: "#/podcast" },
      h("span", { class: "grow" },
        h("span", { class: "title-sm", style: "display:block" }, "Tomorrow's listening"),
        h("span", { class: `caption ${rd.all ? "success" : "muted"}` }, rd.all ? "Ready for offline" : `${rd.ready} of ${rd.planned} ready. Sync on Wi-Fi`)),
      icon("chevron"))
    : readinessFailed
      ? h("p", { class: "caption muted", role: "status" }, "Couldn't check tomorrow's listening. Open Podcast to retry.")
      : null;

  return h("div", { class: `page orb-${ORBS[now.getDay()]}` }, hero,
    ...sessions.map((s) => h("section", {},
      h("h2", { class: "title-sm group-title" }, s.name),
      h("div", { class: "feature-card", style: "padding-top:8px;padding-bottom:8px" }, s.tasks.map(rowFor)))),
    doneCard,
    tomorrowCard,
    nextBar);
}
