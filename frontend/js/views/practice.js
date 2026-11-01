// Practice material lives in the `library` store. Schema (content source still TBD):
//   { id, kind: "audio" | "article", title, audio?: Blob,
//     cues?: [{ start, end, text }]   // seconds; transcript for listening / shadowing
//     text?: string }                 // article body, paragraphs split by blank lines
import { h, icon, fmtClock } from "../util.js";
import * as db from "../db.js";
import * as media from "../media.js";
import { topNav, timerFor, empty } from "./shared.js";

const MODES = {
  listen: { title: "Intensive listening", kinds: ["audio"], blurb: "5–10 minutes of audio with transcript." },
  shadow: { title: "Shadowing", kinds: ["audio", "clips"], blurb: "Play 10–20 s, pause, repeat aloud. Whisper or mouth it on a busy train." },
  read:   { title: "Reading", kinds: ["article"], blurb: "An article on your phone." },
};
const keep = (ctx) => (ctx.query.task ? `&task=${ctx.query.task}` : "");

export async function practice() {
  const items = await db.getAll("library");
  const podcastRow = h("a", { class: "list-row", href: "#/podcast" },
    h("span", { class: "plate" }, icon("headphones")),
    h("span", { class: "grow" }, h("span", { class: "title-sm", style: "display:block" }, "Podcasts"),
      h("span", { class: "caption muted", style: "display:block" }, "Today's episodes, offline")), icon("chevron"));
  const n = (kinds) => items.filter((i) => kinds.includes(i.kind)).length;
  return h("div", { class: "page" },
    h("h1", { class: "display-lg" }, "Practice"),
    h("div", { class: "feature-card", style: "padding-top:8px;padding-bottom:8px" },
      podcastRow,
      Object.entries(MODES).map(([k, m]) => h("a", { class: "list-row", href: `#/practice/${k}` },
        h("span", { class: "plate" }, icon(k === "read" ? "book" : k === "shadow" ? "mic" : "headphones")),
        h("span", { class: "grow" },
          h("span", { class: "title-sm", style: "display:block" }, m.title),
          h("span", { class: "caption muted", style: "display:block" }, `${n(m.kinds)} item${n(m.kinds) === 1 ? "" : "s"}`)),
        icon("chevron")))));
}

export async function library(ctx, mode) {
  const m = MODES[mode];
  const timer = await timerFor(ctx);
  const items = (await db.getAll("library")).filter((i) => m.kinds.includes(i.kind)).sort((a, b) => (b.added || 0) - (a.added || 0));
  const target = mode === "read" ? "article" : "play";
  const href = (i) => i.kind === "clips"
    ? `#/practice/clips?item=${encodeURIComponent(i.id)}${keep(ctx)}`
    : `#/practice/${target}?item=${encodeURIComponent(i.id)}&mode=${mode}${keep(ctx)}`;
  // One pack only: skip the list and go straight in.
  const queued = mode === "shadow" ? await db.count("shadowq") : 0;
  if (items.length === 1 && items[0].kind === "clips" && !queued) return clipShadow({ ...ctx, query: { ...ctx.query, item: items[0].id } });
  if (mode === "read") return readingList(ctx, m, timer, items, href);
  return h("div", {}, topNav(m.title, "/practice"),
    h("div", { class: "page has-top" },
      h("p", {}, m.blurb),
      timer && h("div", { class: "feature-card" }, timer.el),
      queued ? h("a", { class: "btn btn-outline btn-block", href: "#/practice/shadow-queue" }, `From podcasts (${queued})`) : null,
      mode === "read" && h("a", { class: "btn btn-primary btn-block", href: `#/practice/article-add${ctx.query.task ? `?task=${ctx.query.task}` : ""}` }, "Add article"),
      items.length
        ? h("div", { class: "feature-card", style: "padding-top:8px;padding-bottom:8px" }, items.map((i) =>
            h("a", { class: "list-row", href: href(i) }, h("span", { class: "grow" }, h("span", { class: "title-sm", style: "display:block" }, i.title), i.source && h("span", { class: "caption muted", style: "display:block" }, i.source)), icon("chevron"))))
        : empty("No material yet", mode === "read" ? "Add an article from El Mundo or El País." : "Learning material hasn't been added. It will show up here.")));
}

// Articles split into "To read" and "Read": opening an article moves it to Read (see reader()),
// and Unread moves it back.
function readingList(ctx, m, timer, items, href) {
  const unread = () => items.filter((i) => !i.readAt).sort((a, b) => (b.added || 0) - (a.added || 0));
  const read = () => items.filter((i) => i.readAt).sort((a, b) => b.readAt - a.readAt);
  const lists = h("div", { class: "stack", style: "gap:24px" });

  const info = (i) => h("span", { class: "grow" },
    h("span", { class: "title-sm", style: "display:block" }, i.title),
    i.source && h("span", { class: "caption muted", style: "display:block" }, i.source));

  const draw = () => {
    const todo = unread(), done = read();
    const section = (label, rows) => h("section", { class: "stack" },
      h("span", { class: "caption-uppercase muted" }, `${label} · ${rows.length}`),
      rows.length ? h("div", { class: "feature-card", style: "padding-top:8px;padding-bottom:8px" }, rows) : null);
    lists.replaceChildren(...[
      items.length ? null : empty("No material yet", "Add an article from El Mundo or El País."),
      items.length ? section("To read", todo.map((i) =>
        h("a", { class: "list-row", href: href(i) }, info(i), icon("chevron")))) : null,
      done.length ? section("Read", done.map((i) =>
        h("div", { class: "list-row" },
          h("a", { class: "row grow", style: "text-decoration:none;color:inherit;min-height:44px", href: href(i) }, info(i)),
          h("button", { class: "btn btn-text", "aria-label": `Mark "${i.title}" as unread`, onClick: async () => {
            delete i.readAt;
            await db.put("library", i);
            draw();
          } }, "Unread")))) : null,
    ].filter(Boolean));
  };
  draw();

  return h("div", {}, topNav(m.title, "/practice"),
    h("div", { class: "page has-top" },
      h("p", {}, m.blurb),
      timer && h("div", { class: "feature-card" }, timer.el),
      h("a", { class: "btn btn-primary btn-block", href: `#/practice/article-add${ctx.query.task ? `?task=${ctx.query.task}` : ""}` }, "Add article"),
      lists));
}

// Group cues into clips of roughly 10–20 s for shadowing.
export function clips(cues, min = 10, max = 20) {
  const out = [];
  let cur = null;
  for (const c of cues) {
    if (cur && (c.end - cur.start > max || (cur.end - cur.start >= min))) { out.push(cur); cur = null; }
    cur = cur ? { ...cur, end: c.end, text: cur.text + " " + c.text } : { ...c };
  }
  if (cur) out.push(cur);
  return out;
}

export async function audioPlayer(ctx) {
  const timer = await timerFor(ctx);
  const item = await db.get("library", Number(ctx.query.item));
  const mode = ctx.query.mode === "shadow" ? "shadow" : "listen";
  if (!item?.audio) return h("div", { class: "page" }, empty("Not found", ""));

  const url = URL.createObjectURL(item.audio);
  ctx.onLeave(() => URL.revokeObjectURL(url));
  const audio = h("audio", { src: url, preload: "auto" });
  ctx.onLeave(() => audio.pause());

  const speed = h("select", { class: "select-pill", "aria-label": "Speed", style: "width:auto", onChange: () => (audio.playbackRate = Number(speed.value)) },
    [0.75, 1, 1.25].map((v) => h("option", { value: v, selected: v === 1 }, `${v}×`)));
  const playBtn = h("button", { class: "btn btn-primary", "aria-label": "Play" }, icon("play"));
  const sync = () => playBtn.replaceChildren(icon(audio.paused ? "play" : "pause"));
  audio.addEventListener("play", sync); audio.addEventListener("pause", sync);

  const back = `/practice/${mode}` + (ctx.query.task ? `?task=${ctx.query.task}` : "");
  const head = [topNav(item.title, back), timer && h("div", { class: "feature-card" }, timer.el)];
  const cues = item.cues || [];

  if (mode === "listen") {
    const nodes = cues.map((c) => h("button", { class: "cue", onClick: () => { audio.currentTime = c.start; audio.play(); } }, c.text));
    const hl = () => nodes.forEach((n, i) => n.setAttribute("aria-current", String(audio.currentTime >= cues[i].start && audio.currentTime < cues[i].end)));
    audio.addEventListener("timeupdate", hl);
    playBtn.onclick = () => (audio.paused ? audio.play() : audio.pause());
    return h("div", {}, ...head, audio, h("div", { class: "page" },
      h("div", { class: "row" },
        h("button", { class: "icon-btn", "aria-label": "Back 5 seconds", onClick: () => (audio.currentTime = Math.max(0, audio.currentTime - 5)) }, icon("skipback")),
        playBtn, speed),
      h("div", { class: "feature-card" }, nodes.length ? nodes : h("p", { class: "muted" }, "No transcript for this item."))));
  }

  // shadowing
  const segs = clips(cues);
  let i = 0, guard;
  const info = h("p", { class: "caption muted" });
  const text = h("p", { class: "display-sm", hidden: true });
  const showText = h("button", { class: "btn btn-outline", onClick: () => { text.hidden = !text.hidden; } }, "Show text");
  const load = (n) => { i = Math.max(0, Math.min(segs.length - 1, n)); info.textContent = `Clip ${i + 1} / ${segs.length} · ${fmtClock(segs[i].end - segs[i].start)}`; text.textContent = segs[i].text; text.hidden = true; audio.pause(); audio.currentTime = segs[i].start; };
  const playClip = () => {
    audio.currentTime = segs[i].start; audio.play();
    clearInterval(guard);
    guard = setInterval(() => { if (audio.currentTime >= segs[i].end) { audio.pause(); clearInterval(guard); } }, 50);
  };
  ctx.onLeave(() => clearInterval(guard));
  playBtn.onclick = playClip;
  if (!segs.length) return h("div", {}, ...head, h("div", { class: "page" }, empty("No transcript timing", "Shadowing needs timed cues.")));
  load(0);
  return h("div", {}, ...head, audio, h("div", { class: "page" },
    h("section", { class: "gradient-orb-card orb-sky stack", style: "text-align:center" },
      info, text,
      h("div", { class: "row", style: "justify-content:center" },
        h("button", { class: "icon-btn", "aria-label": "Previous clip", onClick: () => load(i - 1) }, icon("skipback")),
        playBtn,
        h("button", { class: "icon-btn", "aria-label": "Replay clip", onClick: playClip }, icon("repeat")),
        h("button", { class: "icon-btn", "aria-label": "Next clip", onClick: () => load(i + 1) }, icon("skipfwd")))),
    h("div", { class: "row" }, showText, speed)));
}

// Shadowing over a pack of sentence clips (10-20 s each, played back to back).
export async function clipShadow(ctx) {
  const timer = await timerFor(ctx);
  const item = await db.get("library", ctx.query.item);
  if (!item?.clips?.length) return h("div", { class: "page" }, empty("Not found", ""));
  const posKey = `shadow:${item.id}`;
  let i = Math.min((await db.get("settings", posKey))?.value ?? 0, item.clips.length - 1);
  let token = 0;
  ctx.onLeave(() => { token++; media.release(); });

  const info = h("p", { class: "caption muted" });
  const text = h("p", { class: "display-sm", hidden: true });
  const english = h("p", { class: "body-sm muted", hidden: true });
  const speed = h("select", { class: "select-pill", "aria-label": "Speed", style: "width:auto" },
    [0.75, 1, 1.25].map((v) => h("option", { value: v, selected: v === 1 }, `${v}×`)));
  const playBtn = h("button", { class: "btn btn-primary", "aria-label": "Play clip" }, icon("play"));
  const showBtn = h("button", { class: "btn btn-outline" }, "Show text");

  const clip = () => item.clips[i];
  const load = async (n) => {
    token++; media.stop();
    i = Math.max(0, Math.min(item.clips.length - 1, n));
    info.textContent = `Clip ${i + 1} / ${item.clips.length} · ${fmtClock(clip().dur)}`;
    text.textContent = clip().text; english.textContent = clip().english;
    text.hidden = english.hidden = true; showBtn.textContent = "Show text";
    db.put("settings", { key: posKey, value: i });
    await Promise.all(clip().sounds.map(media.urlFor)); // ready before the tap, for iOS
  };
  const play = async () => {
    const my = ++token;
    playBtn.replaceChildren(icon("pause"));
    await media.playSequence(clip().sounds, { rate: Number(speed.value), isCancelled: () => my !== token });
    if (my === token) playBtn.replaceChildren(icon("play"));
  };
  playBtn.onclick = () => (playBtn.querySelector("path").getAttribute("d").startsWith("M8 5.5") ? play() : (token++, media.stop(), playBtn.replaceChildren(icon("play"))));
  showBtn.onclick = () => { text.hidden = english.hidden = !text.hidden; showBtn.textContent = text.hidden ? "Show text" : "Hide text"; };
  await load(i);

  const back = ctx.query.task ? "/today" : "/practice";
  return h("div", {}, topNav(item.title, back), h("div", { class: "page has-top" },
    timer && h("div", { class: "feature-card" }, timer.el),
    h("p", { class: "body-sm" }, "Listen, then repeat it aloud. Copy the rhythm and intonation. Whisper or mouth it if you're out."),
    h("section", { class: "gradient-orb-card orb-sky stack", style: "text-align:center" },
      info, text, english,
      h("div", { class: "row", style: "justify-content:center" },
        h("button", { class: "icon-btn", "aria-label": "Previous clip", onClick: () => load(i - 1) }, icon("skipback")),
        playBtn,
        h("button", { class: "icon-btn", "aria-label": "Replay clip", onClick: () => { token++; media.stop(); play(); } }, icon("repeat")),
        h("button", { class: "icon-btn", "aria-label": "Next clip", onClick: () => load(i + 1) }, icon("skipfwd")))),
    h("div", { class: "row" }, showBtn, speed)));
}
