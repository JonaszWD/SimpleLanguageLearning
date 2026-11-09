import { h, icon, canGoBack } from "../util.js";
import { taskTimer } from "../timer.js";
import * as db from "../db.js";
import { getVolume, setVolume, MAX } from "../volume.js";

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

// Volume bar, 0-300 %. Above 100 % boosts the app's sound (e.g. to be heard over music playing in another app).
// One shared setting, so every screen that plays sound shows the same level.
export function volumeBar() {
  const pct = () => Math.round(getVolume() * 100);
  const label = h("span", { class: "caption volume-val" });
  const input = h("input", { type: "range", min: 0, max: MAX * 100, step: 10, value: pct(), "aria-label": "Volume" });
  const paint = () => {
    label.textContent = `${input.value}%`;
    input.setAttribute("aria-valuetext", Number(input.value) > 100 ? `${input.value}% (boosted)` : `${input.value}%`);
    input.style.setProperty("--fill", `${(input.value / (MAX * 100)) * 100}%`);
  };
  input.addEventListener("input", () => { setVolume(Number(input.value) / 100); paint(); });
  input.addEventListener("change", async () => db.saveSettings({ ...(await db.getSettings()), volume: getVolume() }));
  paint();
  return h("div", { class: "volume-bar" }, icon("volume"), input, label);
}
