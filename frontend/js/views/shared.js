import { h, icon, canGoBack } from "../util.js";
import { taskTimer } from "../timer.js";

export function topNav(title, back = "/today") {
  return h("header", { class: "top-nav" },
    h("a", { class: "icon-btn", href: "#" + back, "aria-label": "Back",
      // Return to wherever the user came from (a tab, Today, a list); the href is the fallback for deep links and reloads.
      onClick: (e) => { if (canGoBack()) { e.preventDefault(); history.back(); } } }, icon("back")),
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
