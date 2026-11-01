import { h, icon, trackNav } from "./util.js";
import * as db from "./db.js";
import { initUpdates, isStale } from "./update.js";
import { initSync, subscribe } from "./sync.js";
import { setMixing } from "./media.js";
import { today } from "./views/today.js";
import { decks, study, browse, editNote } from "./views/cards.js";
import { add } from "./views/add.js";
import { practice, library, audioPlayer, clipShadow } from "./views/practice.js";
import { addArticle, reader } from "./views/articles.js";
import { taskPage } from "./views/task.js";
import { grammar, addMistake } from "./views/grammar.js";
import { podcastHub, listen, intensive, shadowQueue } from "./views/podcast.js";
import { talk } from "./views/talk.js";
import { setListenMap } from "./plan.js";
import { stats, settings, importDeck } from "./views/more.js";

const ROUTES = [
  ["/today", today],
  ["/cards", decks],
  ["/cards/study", study],
  ["/cards/browse", browse],
  ["/cards/edit", editNote],
  ["/add", add],
  ["/practice", practice],
  ["/practice/listen", (c) => library(c, "listen")],
  ["/practice/shadow", (c) => library(c, "shadow")],
  ["/practice/read", (c) => library(c, "read")],
  ["/practice/play", audioPlayer],
  ["/practice/clips", clipShadow],
  ["/practice/article", reader],
  ["/practice/article-add", addArticle],
  ["/task", taskPage],
  ["/podcast", podcastHub],
  ["/podcast/listen", listen],
  ["/podcast/intensive", intensive],
  ["/practice/shadow-queue", shadowQueue],
  ["/talk", talk],
  ["/grammar", grammar],
  ["/grammar/mistake", addMistake],
  ["/stats", stats],
  ["/settings", settings],
  ["/import", importDeck],
];

const view = h("main", { id: "view" });
const app = document.getElementById("app");
const syncBar = h("div", { class: "sync-bar", role: "status", hidden: true });
app.append(syncBar, view);
subscribe((s) => {
  syncBar.hidden = !s;
  if (!s) return;
  const pct = s.total ? Math.round((s.done / s.total) * 100) : 0;
  syncBar.replaceChildren(
    h("span", { class: "caption" }, s.total ? `${s.phase} ${s.done} / ${s.total}` : s.phase),
    h("div", { class: "progress" }, h("i", { style: `width:${pct}%` })));
});

let leaveFns = [];
let renderId = 0;

function parseHash() {
  const raw = location.hash.slice(1) || "/today";
  const [path, qs = ""] = raw.split("?");
  return { path, query: Object.fromEntries(new URLSearchParams(qs)) };
}

async function render() {
  if (isStale()) { location.reload(); return; } // a newer build is active: pick it up on navigation
  const id = ++renderId;
  trackNav();
  leaveFns.forEach((f) => f());
  leaveFns = [];
  const { path, query } = parseHash();
  const route = ROUTES.find(([p]) => p === path) || ROUTES[0];
  const ctx = { query, onLeave: (f) => leaveFns.push(f), go };
  let node;
  try {
    node = await route[1](ctx);
  } catch (e) {
    console.error(e);
    node = h("div", { class: "page" }, h("p", { class: "error" }, "Something went wrong: " + e.message));
  }
  if (id !== renderId) return;
  view.replaceChildren(node);
  scrollTo(0, 0);
  markTabs(route[0]);
}

export function go(path) {
  if (location.hash === "#" + path) render();
  else location.hash = path;
}

const TABS = [
  { path: "/today", label: "Today", icon: "today", match: (p) => p === "/today" || p === "/task" },
  { path: "/cards", label: "Cards", icon: "cards", match: (p) => p.startsWith("/cards") || p === "/import" },
  { path: "/practice", label: "Practice", icon: "practice", match: (p) => p.startsWith("/practice") },
];

const sheet = h("dialog", { class: "sheet", "aria-label": "More" },
  h("nav", {},
    ...[["/stats", "Stats", "stats"], ["/grammar/mistake", "Add a mistake", "note"], ["/import", "Import Anki deck", "upload"], ["/settings", "Settings", "gear"]].map(
      ([p, l, i]) => h("a", { class: "list-row", href: "#" + p, onClick: () => sheet.close() }, h("span", { class: "plate" }, icon(i)), h("span", { class: "grow" }, l), icon("chevron")),
    ),
  ),
  h("div", { style: "margin-top:16px" }, h("button", { class: "btn btn-outline btn-block", onClick: () => sheet.close() }, "Close")),
);
sheet.addEventListener("click", (e) => { if (e.target === sheet) sheet.close(); });

const bar = h("nav", { class: "bottom-tab-bar", "aria-label": "Main" },
  ...TABS.map((t) => h("a", { class: "tab", href: "#" + t.path, "data-tab": t.path }, icon(t.icon), t.label)),
  h("button", { class: "tab", id: "more-tab", onClick: () => sheet.showModal() }, icon("more"), "More"),
);
document.body.append(bar, sheet);

function markTabs(path) {
  for (const t of TABS) {
    const el = bar.querySelector(`[data-tab="${t.path}"]`);
    if (t.match(path)) el.setAttribute("aria-current", "page");
    else el.removeAttribute("aria-current");
  }
  const more = ["/stats", "/settings"].includes(path);
  const m = bar.querySelector("#more-tab");
  if (more) m.setAttribute("aria-current", "page"); else m.removeAttribute("aria-current");
}

addEventListener("hashchange", render);

(async () => {
  await db.seed();
  setMixing((await db.getSettings()).mixAudio);
  setListenMap((await db.getSettings()).listenMap);
  navigator.storage?.persist?.();
  initUpdates().catch(console.error);
  initSync();
  render();
})();
