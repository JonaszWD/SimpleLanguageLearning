import { h, icon } from "../util.js";
import { taskTimer } from "../timer.js";

export function topNav(title, back = "/today") {
  return h("header", { class: "top-nav" },
    h("a", { class: "icon-btn", href: "#" + back, "aria-label": "Back" }, icon("back")),
    h("span", { class: "title" }, title));
}

// Optional plan-task timer, mounted when the view was opened from Today (?task=…).
export async function timerFor(ctx) {
  if (!ctx.query.task) return null;
  return taskTimer(ctx.query.task, ctx.onLeave);
}

export function empty(title, text, action) {
  return h("div", { class: "feature-card empty" },
    h("h2", { class: "display-sm" }, title),
    h("p", { class: "muted" }, text),
    action);
}
