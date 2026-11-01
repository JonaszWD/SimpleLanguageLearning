import { h, dateKey, addDays, startOfDay, toast, icon } from "../util.js";
import * as db from "../db.js";
import { allTasks } from "../plan.js";
import { mergeDeck, installPack, installedPacks, availablePacks } from "../packs.js";
import { topNav } from "./shared.js";
import { checkNow, runningVersion } from "../update.js";
import { syncAll } from "../sync.js";
import { stats as grammarStats } from "../grammar.js";
import { weekSummary } from "../podcast.js";
import { setListenMap } from "../plan.js";
import { apiUrl } from "../config.js";
import { setMixing } from "../media.js";

const isDone = async (d) => {
  const day = await db.get("days", dateKey(d));
  const tasks = allTasks(d);
  return !!day && tasks.every((t) => day.tasks[t.id]?.done);
};

async function listeningSection() {
  let w;
  try { w = await weekSummary(); } catch { return null; }
  const total = w.weeks.at(-1).minutes;
  const max = Math.max(60, ...w.weeks.map((x) => x.minutes));
  return h("div", { class: "feature-card stack" },
    h("span", { class: "caption-uppercase muted" }, "Listening this week"),
    h("div", { class: "title-md" }, `${total} min · ${w.phrases} phrase${w.phrases === 1 ? "" : "s"} saved`),
    w.follow != null ? h("p", { class: "body-sm" }, `Followed on average ${w.follow.toFixed(1)} / 5 (${w.followN} intensive session${w.followN === 1 ? "" : "s"})`) : h("p", { class: "caption muted" }, "No intensive sessions rated yet."),
    Object.keys(w.byLevel).length ? h("p", { class: "body-sm" }, "By level: " + Object.entries(w.byLevel).sort().map(([l, m]) => `${l} ${Math.round(m)} min`).join(" · ")) : null,
    h("div", { class: "trend", style: "grid-template-columns:repeat(5,1fr)" }, w.weeks.map((x) => h("div", { class: "col" },
      h("span", { class: "caption" }, x.minutes),
      h("div", { class: "bar" }, h("i", { style: `height:${Math.round((x.minutes / max) * 100)}%` })),
      h("span", { class: "caption muted" }, new Date(x.from).toLocaleDateString(undefined, { day: "numeric", month: "numeric" }))))));
}

async function grammarSection() {
  let g;
  try { g = await grammarStats(); } catch { return null; }
  if (!g.rows.length) return h("div", { class: "feature-card stack" }, h("span", { class: "caption-uppercase muted" }, "Grammar"), h("p", { class: "muted" }, "No grammar data yet. It appears after the first sync."));
  const pct = (a) => (a == null ? "–" : `${Math.round(a * 100)}%`);
  const total = g.rows.reduce((n, r) => n + r.attempts, 0);
  return h("div", { class: "stack", style: "gap:16px" },
    g.flagged.length ? h("div", { class: "feature-card stack" },
      h("span", { class: "title-sm" }, "Needs extra practice"),
      h("p", { class: "body-sm" }, "Under 70% after two weeks. These are mixed into your grammar sessions. Consider repeating them."),
      g.flagged.map((r) => h("a", { class: "list-row", href: `#/grammar?focus=${r.id}`, style: "min-height:48px" },
        h("span", { class: "grow" }, h("span", { class: "title-sm", style: "display:block" }, r.title), h("span", { class: "caption muted" }, `${pct(r.acc)} · ${r.attempts} answers`)),
        h("span", { class: "btn btn-outline" }, "Practise")))) : null,
    h("div", { class: "feature-card stack" },
      h("span", { class: "caption-uppercase muted" }, "Grammar trend · accuracy by week"),
      h("div", { class: "trend" }, g.trend.map((w) => h("div", { class: "col" },
        h("span", { class: "caption" }, pct(w.acc)),
        h("div", { class: "bar" }, h("i", { style: `height:${w.acc == null ? 0 : Math.round(w.acc * 100)}%` })),
        h("span", { class: "caption muted" }, `${w.from ? new Date(w.from).toLocaleDateString(undefined, { day: "numeric", month: "numeric" }) : ""}`))))),
    h("div", { class: "feature-card stack" },
      h("span", { class: "caption-uppercase muted" }, `Grammar by topic · ${total} answers`),
      g.weakest.length ? h("p", { class: "body-sm" }, "Weakest: " + g.weakest.map((r) => `${r.title} (${pct(r.acc)})`).join(", ")) : null,
      g.rows.map((r) => h("div", { class: "acc-row" },
        h("div", { class: "row between" }, h("span", { class: "body-sm" }, `${r.week}. ${r.title}`), h("span", { class: "caption" }, r.attempts ? `${pct(r.acc)} · ${r.attempts}` : "–")),
        h("div", { class: "progress" }, h("i", { style: `width:${r.acc == null ? 0 : Math.round(r.acc * 100)}%` }))))));
}

export async function stats() {
  const now = new Date();
  const days = [];
  for (let i = 6; i >= 0; i--) {
    const d = new Date(addDays(startOfDay(now), -i));
    days.push({ d, done: await isDone(d) });
  }
  let streak = 0;
  for (let i = days[6].done ? 6 : 5; i >= 0 && days[i].done; i--) streak++;
  const today = await db.getDay(dateKey(now));
  const letters = "SMTWTFS";
  return h("div", { class: "page" },
    h("h1", { class: "display-lg" }, "Stats"),
    h("section", { class: "gradient-orb-card orb-peach stack" },
      h("span", { class: "caption-uppercase muted" }, "Current streak"),
      h("div", { class: "display-lg" }, `${streak} day${streak === 1 ? "" : "s"}`)),
    h("div", { class: "feature-card stack" },
      h("span", { class: "caption-uppercase muted" }, "Last 7 days"),
      h("div", { class: "week" }, days.map(({ d, done }, i) => h("div", { class: "stack", style: "gap:4px" },
        h("div", { class: `dot ${done ? "done" : ""} ${i === 6 ? "today" : ""}` }, done ? icon("check") : null),
        h("span", { class: "caption muted" }, letters[d.getDay()]))))),
    h("div", { class: "feature-card stack" },
      h("span", { class: "caption-uppercase muted" }, "Cards today"),
      h("div", { class: "title-md" }, `${today.newDone} new · ${today.revDone} reviewed`)),
    await listeningSection(),
    await grammarSection());
}

export async function settings(ctx) {
  const s = await db.getSettings();
  const num = (k, label, step = 1) => {
    const i = h("input", { class: "text-input", type: "number", min: 0, step, value: s[k], inputmode: "decimal" });
    i.addEventListener("change", () => (s[k] = Number(i.value)));
    return h("div", { class: "field" }, h("label", {}, label), i);
  };
  const steps = (k, label) => {
    const i = h("input", { class: "text-input", value: s[k].join(" "), inputmode: "decimal" });
    i.addEventListener("change", () => (s[k] = i.value.split(/\s+/).map(Number).filter((n) => n > 0)));
    return h("div", { class: "field" }, h("label", {}, label + " (minutes)"), i);
  };
  const save = async () => { await db.saveSettings(s); setListenMap(s.listenMap); toast("Saved"); };

  const exportBackup = async () => {
    const out = {};
    for (const st of ["decks", "models", "notes", "cards", "revlog", "days", "settings"]) out[st] = await db.getAll(st);
    const a = h("a", { href: URL.createObjectURL(new Blob([JSON.stringify(out)], { type: "application/json" })), download: `language-app-${dateKey()}.json` });
    a.click();
  };
  const restore = async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    const data = JSON.parse(await f.text());
    for (const [st, rows] of Object.entries(data)) if (st !== "revlog") await db.putMany(st, rows);
    toast("Backup restored");
    ctx.go("/today");
  };
  const file = h("input", { type: "file", accept: "application/json", onChange: restore });

  const auto = h("select", { class: "select-pill", "aria-label": "Auto-download content" },
    h("option", { value: "on", selected: s.autoSync }, "On"), h("option", { value: "off", selected: !s.autoSync }, "Off"));
  auto.addEventListener("change", () => (s.autoSync = auto.value === "on"));
  const mix = h("select", { class: "select-pill", "aria-label": "Play over other audio" },
    h("option", { value: "on", selected: s.mixAudio }, "On"), h("option", { value: "off", selected: !s.mixAudio }, "Off"));
  mix.addEventListener("change", () => { s.mixAudio = mix.value === "on"; setMixing(s.mixAudio); });
  const dev = h("select", { class: "select-pill", "aria-label": "Developer mode" },
    h("option", { value: "off", selected: !s.devMode }, "Off"), h("option", { value: "on", selected: s.devMode }, "On"));
  dev.addEventListener("change", () => (s.devMode = dev.value === "on"));
  const gStart = h("input", { class: "text-input", type: "date", value: s.grammarStart || "" });
  gStart.addEventListener("change", () => (s.grammarStart = gStart.value || s.grammarStart));
  const share = h("input", { class: "text-input", type: "number", min: 0, max: 50, step: 5, value: Math.round((s.grammarShare ?? 0.15) * 100), inputmode: "numeric" });
  share.addEventListener("change", () => (s.grammarShare = Math.min(0.5, Math.max(0, Number(share.value) / 100))));
  const DAYS = [[1, "Mon"], [2, "Tue"], [3, "Wed"], [4, "Thu"], [5, "Fri"]];
  const listenRows = DAYS.map(([d, label]) => {
    const sel = h("select", { class: "select-pill", "aria-label": `Listening on ${label}`, style: "width:auto" },
      [["extensive", "Extensive"], ["intensive", "Intensive"], ["none", "None"]].map(([v, l]) => h("option", { value: v, selected: (s.listenMap[d] || "none") === v }, l)));
    sel.addEventListener("change", () => { s.listenMap = { ...s.listenMap, [d]: sel.value }; });
    return h("div", { class: "row between" }, h("span", {}, label), sel);
  });
  const syncNow = async () => { toast("Syncing…"); await syncAll({ force: true }); toast("Content is up to date"); };

  const ver = h("p", { class: "caption muted" }, "Version …");
  runningVersion().then((v) => (ver.textContent = v ? `Version ${v}` : "Version unknown (not installed yet)"));
  const checkUpdates = async () => {
    ver.textContent = "Checking…";
    try { await checkNow(); toast("Up to date, or updating now"); } catch { toast("Couldn't reach the server"); }
    ver.textContent = `Version ${(await runningVersion()) || "unknown"}`;
  };

  return h("div", {}, topNav("Settings", "/today"), h("div", { class: "page has-top" },
    h("h1", { class: "display-lg" }, "Settings"),
    h("div", { class: "stack" },
      num("newPerDay", "New cards per day"), num("reviewsPerDay", "Max reviews per day"),
      steps("learnSteps", "Learning steps"), steps("relearnSteps", "Relearning steps"),
      num("graduatingIvl", "Graduating interval (days)"), num("easyIvl", "Easy interval (days)"),
      num("intervalModifier", "Interval modifier", 0.05),
      h("div", { class: "field" }, h("label", {}, "Auto-download deck and articles"), auto),
      h("div", { class: "field" }, h("label", {}, "Listening by weekday"), h("div", { class: "stack", style: "gap:8px" }, listenRows),
        h("p", { class: "caption muted" }, "Extensive: 30 min, no text. Intensive: guided 5–10 min segment. Save to apply.")),
      num("podcastKeepDays", "Keep listened episodes on this phone (days)"),
      h("div", { class: "field" }, h("label", {}, "Grammar syllabus start (week 1)"), gStart),
      h("div", { class: "field" }, h("label", {}, "Grammar share of new cards (%)"), share),
      num("mistakeCardsPerDay", "Mistake cards per day (max)"),
      h("div", { class: "field" },
        h("label", {}, "Developer mode"), dev,
        h("p", { class: "caption muted" }, "Tap any day in the Today calendar to preview how that day looks. Previews are read-only. Save to apply.")),
      h("div", { class: "field" },
        h("label", {}, "Keep other audio playing"), mix,
        h("p", { class: "caption muted" }, "On: your music keeps playing while a card or clip plays. The iPhone silent switch then mutes the app too. Off: the app pauses other audio but ignores the switch.")),
      h("button", { class: "btn btn-primary btn-block", onClick: save }, "Save")),
    h("div", { class: "feature-card stack" },
      h("span", { class: "title-sm" }, "Backup"),
      h("p", { class: "body-sm muted" }, "Data lives on this device. Add the app to your Home Screen and keep a backup: Safari can clear website data."),
      h("div", { class: "row" },
        h("button", { class: "btn btn-outline grow", onClick: exportBackup }, "Export"),
        h("button", { class: "btn btn-outline grow", onClick: () => file.click() }, "Restore"), file)),
    h("div", { class: "feature-card stack" },
      h("span", { class: "title-sm" }, "Content"),
      h("p", { class: "body-sm muted" }, "The Anki deck (about 100 MB of audio) and new articles download in the background. Turn this off to save mobile data."),
      h("button", { class: "btn btn-outline btn-block", onClick: syncNow }, "Sync now")),
    h("div", { class: "feature-card stack" },
      h("span", { class: "title-sm" }, "App updates"),
      h("p", { class: "body-sm muted" }, "The app checks for a new version whenever you open it."),
      ver,
      h("button", { class: "btn btn-outline btn-block", onClick: checkUpdates }, "Check for updates"))));
}

export async function importDeck(ctx) {
  const status = h("p", { class: "body-sm" });
  const file = h("input", { type: "file", accept: ".apkg,.colpkg", onChange: async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    status.className = "body-sm"; status.textContent = "Importing…";
    try {
      const body = new FormData();
      body.append("file", f);
      const res = await fetch(apiUrl("/anki/import"), { method: "POST", body });
      if ([404, 405, 501].includes(res.status)) throw new Error("Importing needs the backend server. It isn't available on this hosting.");
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `Server error ${res.status}`);
      const data = await res.json();
      const r = await mergeDeck(data);
      status.textContent = `Imported ${r.notes} notes (${r.cards} cards). ${r.skipped} duplicates skipped.`;
      status.className = "body-sm success";
    } catch (err) {
      status.className = "body-sm error";
      status.textContent = err instanceof TypeError ? "Import needs a connection to your server." : err.message;
    }
  } });

  const packBox = h("div", { class: "stack" });
  const drawPacks = async () => {
    let metas = [];
    try { metas = await availablePacks(); } catch { /* offline */ }
    const have = await installedPacks();
    packBox.replaceChildren(...metas.map((m) => {
      const label = h("span", { class: "caption muted" }, `${m.notes} cards · ${m.clips} shadowing clips · ${Math.round(m.audioBytes / 1e6)} MB audio`);
      const bar = h("i");
      const track = h("div", { class: "progress thick", hidden: true }, bar);
      const btn = h("button", { class: have.has(m.id) ? "btn btn-outline btn-block" : "btn btn-primary btn-block" }, have.has(m.id) ? "Re-check audio" : "Download for offline");
      btn.addEventListener("click", async () => {
        btn.disabled = true; track.hidden = false;
        try {
          await installPack(m, ({ phase, done, total }) => {
            label.textContent = total ? `${phase} ${done} / ${total}` : phase;
            if (total) bar.style.width = `${(done / total) * 100}%`;
          });
          label.textContent = "Ready. Works offline.";
          label.className = "caption success";
          btn.textContent = "Installed";
        } catch (err) {
          label.textContent = err.message; label.className = "caption error"; btn.disabled = false;
        }
      });
      return h("div", { class: "feature-card stack" }, h("span", { class: "title-sm" }, m.title), label, track, btn);
    }));
  };
  drawPacks();

  return h("div", {}, topNav("Import Anki deck", "/cards"), h("div", { class: "page has-top" },
    h("h1", { class: "display-lg" }, "Import"),
    h("span", { class: "caption-uppercase muted" }, "Content packs"),
    packBox,
    h("span", { class: "caption-uppercase muted" }, "Anki file"),
    h("p", {}, "Choose an .apkg or .colpkg exported from Anki (tick “Support older Anki versions”). Needs a connection once; afterwards everything works offline."),
    h("button", { class: "btn btn-primary btn-block", onClick: () => file.click() }, "Choose file"), file,
    status,
    h("p", { class: "caption muted" }, "Scheduling is kept. Media (audio, images) is not imported yet.")));
}
