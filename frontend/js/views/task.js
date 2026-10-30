import { h } from "../util.js";
import { KINDS } from "../plan.js";
import { topNav, timerFor } from "./shared.js";

// Generic page for tasks done outside the app (podcast, grammar video, tutor notes…).
export async function taskPage(ctx) {
  const timer = await timerFor(ctx);
  if (!timer) return h("div", { class: "page" }, h("p", {}, "Open a task from Today."));
  const k = KINDS[timer.task.kind];
  const done = h("button", { class: "btn btn-primary btn-block", onClick: async () => { await timer.markDone(); ctx.go("/today"); } }, "Mark done");
  return h("div", {}, topNav(k.label),
    h("div", { class: "page has-top" },
      h("h1", { class: "display-lg" }, k.label),
      timer.task.detail && h("p", {}, timer.task.detail),
      k.external && h("p", { class: "muted" }, "Done in your own app. Come back and tick it off."),
      h("div", { class: "feature-card stack" }, timer.task.min ? timer.el : null, done)));
}
