import { h, icon, dateKey } from "../util.js";
import * as db from "../db.js";
import { sessionsFor, KINDS, ORBS, totalMinutes } from "../plan.js";

export async function today(ctx) {
  const now = new Date();
  const date = dateKey(now);
  const day = await db.getDay(date);
  const sessions = sessionsFor(now);
  const tasks = sessions.flatMap((s) => s.tasks);
  const doneCount = () => tasks.filter((t) => day.tasks[t.id]?.done).length;

  const bar = h("i");
  const summary = h("p", { class: "body-sm" });
  const paint = () => {
    bar.style.width = `${(doneCount() / tasks.length) * 100}%`;
    summary.textContent = `${doneCount()} of ${tasks.length} done · ${totalMinutes(now)} min planned`;
  };

  const hero = h("section", { class: `gradient-orb-card orb-${ORBS[now.getDay()]} stack` },
    h("span", { class: "caption-uppercase muted" }, now.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" })),
    h("h1", { class: "display-lg" }, doneCount() === tasks.length ? "All done for today." : "Today"),
    h("div", { class: "progress" }, bar),
    summary);
  paint();

  const rowFor = (t) => {
    const k = KINDS[t.kind];
    const rec = day.tasks[t.id];
    const check = h("button", { class: "check", role: "checkbox", "aria-checked": String(!!rec?.done), "aria-label": `Mark ${k.label} done`, onClick: async (e) => {
      e.stopPropagation();
      const r = (day.tasks[t.id] ??= { secs: 0, done: false });
      r.done = !r.done;
      check.setAttribute("aria-checked", String(r.done));
      await db.saveDay(day);
      paint();
    } }, icon("check"));
    const meta = [t.min ? `${t.min} min` : null, t.detail].filter(Boolean).join(" · ");
    return h("div", { class: "list-row" },
      check,
      h("a", { class: "row grow", style: "text-decoration:none;color:inherit;min-height:44px", href: `#${k.route}?task=${t.id}` },
        h("span", { class: "plate" }, icon(k.icon)),
        h("span", { class: "grow" },
          h("span", { class: "title-sm", style: "display:block" }, k.label),
          meta && h("span", { class: "caption muted", style: "display:block" }, meta)),
        icon("chevron")));
  };

  return h("div", { class: "page" }, hero,
    ...sessions.map((s) => h("section", { class: "stack" },
      h("span", { class: "caption-uppercase muted" }, s.name),
      h("div", { class: "feature-card", style: "padding-top:8px;padding-bottom:8px" }, s.tasks.map(rowFor)))));
}
