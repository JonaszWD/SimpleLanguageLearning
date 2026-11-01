import { h, icon, toast, addDays, startOfDay, dateKey } from "../util.js";
import * as db from "../db.js";
import * as media from "../media.js";
import * as P from "../podcast.js";
import { apiUrl } from "../config.js";
import { topNav, timerFor, empty } from "./shared.js";

const SPEEDS_EXT = [0.75, 1, 1.25, 1.5, 1.75];
const SPEEDS_INT = [0.75, 0.9, 1];
const tomorrow = () => new Date(addDays(startOfDay(new Date()), 1));
const keep = (ctx) => (ctx.query.task ? `&task=${ctx.query.task}` : "");
const speedSelect = (speeds, onChange, value = 1) =>
  h("select", { class: "select-pill", "aria-label": "Speed", style: "width:auto", onChange: (e) => onChange(Number(e.target.value)) },
    speeds.map((v) => h("option", { value: v, selected: v === value }, `${v}×`)));
const levelBadge = (l) => h("span", { class: "badge-pill" }, l || "?");
const source = (meta, st) => (meta?.link || st?.link)
  ? h("a", { class: "caption src-link", href: meta?.link || st.link, target: "_blank", rel: "noopener" }, `Source: ${st?.show || meta?.show || "episode page"}`)
  : h("span", { class: "caption muted" }, `Source: ${st?.show || meta?.show || ""}`);

function ratingRow(epId, onDone) {
  const row = h("div", { class: "stack" },
    h("span", { class: "caption-uppercase muted" }, "How was the level?"),
    h("div", { class: "row" }, ["too easy", "right", "too hard"].map((r) =>
      h("button", { class: "btn btn-outline grow", onClick: async () => { await P.rateEpisode(epId, r); toast("Thanks. This shapes what's picked next."); onDone?.(r); } }, r))));
  return row;
}

// ── hub ─────────────────────────────────────────────────────────────────────
export async function podcastHub(ctx) {
  const up = await P.serverUp();
  const today = new Date();
  const [tm, plan, states] = [await P.readiness(tomorrow()), await P.cachedPlan(today), await db.getAll("epstate")];
  const status = h("p", { class: "caption muted" });
  const sync = async () => {
    status.textContent = "Syncing…";
    await P.syncPodcasts((p) => (status.textContent = p.phase)).catch(() => {});
    ctx.go("/podcast");
  };

  const readyCard = h("div", { class: "feature-card stack" },
    h("span", { class: "caption-uppercase muted" }, "Tomorrow's listening"),
    !tm.planned ? h("p", { class: "muted" }, up ? "Nothing planned for tomorrow." : "Plan not downloaded yet.")
      : h("div", { class: "row" },
          h("span", { class: `title-sm ${tm.all ? "success" : ""}` }, tm.all ? "Ready for offline" : `${tm.ready} of ${tm.planned} ready`),
          !tm.all && h("span", { class: "caption muted" }, "Sync on Wi-Fi before you leave")),
    h("button", { class: "btn btn-outline", onClick: sync }, "Sync now"), status);

  const planCard = (day, p) => h("div", { class: "stack" },
    h("span", { class: "caption-uppercase muted" }, `${day} · ${p.mode} · ${p.stage}`),
    p.items.length ? p.items.map((it) => h("div", { class: "feature-card stack" },
      h("div", { class: "row between" }, h("span", { class: "title-sm" }, it.show), levelBadge(it.level)),
      h("p", { class: "body-sm" }, it.title),
      h("p", { class: "caption muted" }, `${it.minutes || "?"} min`),
      h("details", {}, h("summary", { class: "caption" }, "Why this episode?"),
        h("ul", { class: "caption muted", style: "margin:8px 0 0;padding-left:20px" }, it.why.map((w) => h("li", {}, w)))),
      h("a", { class: "btn btn-primary", href: `#/podcast/${it.mode === "intensive" ? "intensive" : "listen"}?ep=${it.episode}` }, "Open")))
      : h("p", { class: "muted" }, p.notes?.join(" ") || "Nothing planned."),
    p.skipped?.length ? h("p", { class: "caption muted" }, "Skipped: " + p.skipped.join("; ")) : null);

  const local = states.filter((s) => s.title);
  let browse = null;
  if (up) {
    const eps = await fetch(apiUrl("/podcasts/episodes?limit=6")).then((r) => (r.ok ? r.json() : [])).catch(() => []);
    const open = async (ep, mode, btn, note) => {
      btn.disabled = true;
      const ok = await P.fetchEpisode(ep, mode, (t) => (note.textContent = t)).catch(() => false);
      if (ok) ctx.go(`/podcast/${mode === "intensive" ? "intensive" : "listen"}?ep=${ep.id}`);
      else { note.textContent = "Could not prepare this episode. Check the server."; btn.disabled = false; }
    };
    browse = h("div", { class: "stack" }, h("span", { class: "caption-uppercase muted" }, "Browse episodes"),
      eps.length ? eps.map((ep) => {
        const note = h("p", { class: "caption muted" }, ep.transcript?.timed ? `Transcript ready (${ep.transcript.source})` : "Transcript is made when you open it");
        const b1 = h("button", { class: "btn btn-primary", onClick: () => open(ep, "intensive", b1, note) }, "Intensive");
        const b2 = h("button", { class: "btn btn-outline", onClick: () => open(ep, "extensive", b2, note) }, "Listen");
        return h("div", { class: "feature-card stack" },
          h("div", { class: "row between" }, h("span", { class: "title-sm" }, ep.show), levelBadge(ep.level)),
          h("p", { class: "body-sm" }, ep.title), h("p", { class: "caption muted" }, `${ep.minutes || "?"} min`),
          h("div", { class: "row" }, b1, b2), note);
      }) : h("p", { class: "muted" }, "No episodes yet. Run a poll on the server."));
  }
  return h("div", {}, topNav("Podcasts", "/practice"), h("div", { class: "page has-top" },
    h("h1", { class: "display-lg" }, "Podcasts"),
    !up && h("p", { class: "caption muted" }, "The podcast server isn't reachable. You can still use what's downloaded."),
    readyCard,
    plan ? planCard("Today", plan) : h("p", { class: "muted" }, "No plan yet. Sync while connected to your server."),
    browse,
    local.length ? h("div", { class: "stack" },
      h("span", { class: "caption-uppercase muted" }, "On this phone"),
      h("div", { class: "feature-card", style: "padding-top:8px;padding-bottom:8px" }, local.map((s) =>
        h("a", { class: "list-row", href: `#/podcast/listen?ep=${s.id}` },
          h("span", { class: "grow" }, h("span", { class: "title-sm", style: "display:block" }, s.title),
            h("span", { class: "caption muted" }, [s.show, s.rating, s.listenedAt ? "listened" : null].filter(Boolean).join(" · "))), icon("chevron"))))) : null));
}

// ── extensive listening ─────────────────────────────────────────────────────
export async function listen(ctx) {
  const timer = await timerFor(ctx);
  const plan = await P.cachedPlan(new Date());
  const states = await db.getAll("epstate");
  const ids = [...new Set([...(plan?.items || []).filter((i) => i.mode !== "intensive").map((i) => i.episode), ...states.filter((s) => !s.listenedAt).map((s) => s.id)])];
  const queue = [];
  for (const id of ids) { const e = await P.localEpisode(id); if (e.hasAudio) queue.push({ id, ...e }); }
  const wanted = ctx.query.ep && (await P.localEpisode(ctx.query.ep));
  if (wanted?.hasAudio && !queue.some((q) => q.id === ctx.query.ep)) queue.unshift({ id: ctx.query.ep, ...wanted });
  if (!queue.length) {
    return h("div", {}, topNav("Extensive listening", "/today"), h("div", { class: "page has-top" },
      timer && h("div", { class: "feature-card" }, timer.el),
      empty("Nothing downloaded", "Episodes download on Wi-Fi. Open Podcasts and tap Sync now.", h("a", { class: "btn btn-outline", href: "#/podcast" }, "Podcasts"))));
  }
  let idx = Math.max(0, queue.findIndex((q) => q.id === ctx.query.ep));
  const el = media.audioEl();
  ctx.onLeave(() => { flush(); media.release(); });

  const body = h("div", { class: "page has-top" });
  const root = h("div", {}, topNav("Extensive listening", "/today"), body);
  let played = 0, epId = null, tick = null;

  const flush = async () => {
    clearInterval(tick);
    if (!epId) return;
    await P.saveState(epId, { position: el.ended ? 0 : el.currentTime });
    await P.logListen({ epId, mode: "extensive", secs: played });
    played = 0;
  };

  async function show() {
    await flush();
    const q = queue[idx];
    epId = q.id;
    const meta = q.meta || {}, st = q.state || {};
    await media.load(P.epKey(q.id));
    el.currentTime = st.position > 5 ? st.position : 0;
    const seek = h("input", { type: "range", min: 0, max: Math.floor(el.duration || (meta.minutes || 20) * 60), value: 0, "aria-label": "Position", style: "width:100%" });
    const pos = h("span", { class: "caption muted" }, "0:00");
    const playBtn = h("button", { class: "btn btn-primary", "aria-label": "Play" }, icon("play"));
    const sync = () => playBtn.replaceChildren(icon(el.paused ? "play" : "pause"));
    const upd = () => { seek.max = Math.floor(el.duration || seek.max); seek.value = Math.floor(el.currentTime); pos.textContent = `${P.fmtTime(el.currentTime)} / ${P.fmtTime(el.duration || 0)}`; };
    el.onplay = el.onpause = sync; el.ontimeupdate = upd; el.onloadedmetadata = upd;
    el.onended = async () => { await P.markListened(q.id); toast("Marked as listened"); show(); };
    playBtn.onclick = () => (el.paused ? el.play() : el.pause());
    seek.oninput = () => (el.currentTime = Number(seek.value));
    clearInterval(tick);
    tick = setInterval(() => { if (!el.paused) played++; if (played % 5 === 0) P.saveState(q.id, { position: el.currentTime }); }, 1000);
    if ("mediaSession" in navigator) {   // lock-screen controls, keeps playing in the background
      navigator.mediaSession.metadata = new MediaMetadata({ title: meta.title || st.title || "Episode", artist: st.show || meta.show || "Podcast" });
      navigator.mediaSession.setActionHandler("play", () => el.play());
      navigator.mediaSession.setActionHandler("pause", () => el.pause());
      navigator.mediaSession.setActionHandler("seekbackward", () => (el.currentTime -= 15));
      navigator.mediaSession.setActionHandler("seekforward", () => (el.currentTime += 30));
    }
    const rate = Number(localStorage.getItem("podcastRate") || 1);
    el.playbackRate = rate;
    const done = st.listenedAt;
    body.replaceChildren(...[
      timer && h("div", { class: "feature-card" }, timer.el),
      h("section", { class: "gradient-orb-card orb-sky stack" },
        h("div", { class: "row between" }, levelBadge(meta.level || st.level), h("span", { class: "caption muted" }, meta.accent || "")),
        h("h1", { class: "display-sm" }, meta.title || st.title),
        h("p", { class: "caption muted" }, st.show || meta.show || ""), source(meta, st)),
      h("div", { class: "stack" }, seek, h("div", { class: "row between" }, pos,
        speedSelect(SPEEDS_EXT, (v) => { el.playbackRate = v; localStorage.setItem("podcastRate", v); }, rate))),
      h("div", { class: "row", style: "justify-content:center" },
        h("button", { class: "icon-btn", "aria-label": "Back 15 seconds", onClick: () => (el.currentTime = Math.max(0, el.currentTime - 15)) }, icon("skipback")),
        playBtn,
        h("button", { class: "icon-btn", "aria-label": "Forward 30 seconds", onClick: () => (el.currentTime += 30) }, icon("skipfwd"))),
      h("div", { class: "row" },
        h("button", { class: "btn btn-outline grow", onClick: async () => { await P.markListened(q.id); toast("Marked as listened"); body.append(ratingRow(q.id)); } }, "Mark listened"),
        queue.length > 1 && h("button", { class: "btn btn-text", onClick: () => { idx = (idx + 1) % queue.length; show(); } }, "Skip")),
      done && ratingRow(q.id),
      queue.length > 1 && h("div", { class: "stack" }, h("span", { class: "caption-uppercase muted" }, "Queue"),
        h("div", { class: "feature-card", style: "padding-top:8px;padding-bottom:8px" }, queue.map((x, i) =>
          h("button", { class: "list-row", "aria-current": i === idx ? "true" : null, onClick: () => { idx = i; show(); } },
            h("span", { class: "grow" }, h("span", { class: "title-sm", style: "display:block" }, x.meta?.title || x.state?.title || x.id),
              h("span", { class: "caption muted" }, x.state?.listenedAt ? "listened" : x.state?.position > 5 ? `resume at ${P.fmtTime(x.state.position)}` : "new")))))),
    ].filter(Boolean));
    upd(); sync();
  }
  await show();
  return root;
}

// ── intensive listening (guided) ────────────────────────────────────────────
const STEPS = ["Listen without text", "Listen with the transcript", "Save words and phrases", "Listen again without text", "Check your understanding"];
const WORD = /\p{L}[\p{L}\p{M}'’-]*/gu;

export async function intensive(ctx) {
  const timer = await timerFor(ctx);
  const plan = await P.cachedPlan(new Date());
  const epId = ctx.query.ep || (plan?.items || []).find((i) => i.mode === "intensive")?.episode;
  const local = epId && (await P.localEpisode(epId));
  const tr = local?.transcript;
  if (!local?.hasAudio || !tr?.timed || !tr.chunks?.length) {
    return h("div", {}, topNav("Intensive listening", "/today"), h("div", { class: "page has-top" },
      timer && h("div", { class: "feature-card" }, timer.el),
      empty("Nothing ready for intensive listening",
        !epId ? "No intensive episode is planned. Open Podcasts and sync." : !local?.hasAudio ? "This episode isn't downloaded yet." : "This episode has no timed transcript yet.",
        h("a", { class: "btn btn-outline", href: "#/podcast" }, "Podcasts"))));
  }
  const meta = local.meta || {}, st = local.state;
  const done = st.chunksDone || [];
  const chunkIdx = ctx.query.chunk != null ? Number(ctx.query.chunk) : Math.max(0, tr.chunks.findIndex((c) => !done.includes(c.index)));
  const chunk = tr.chunks[chunkIdx] || tr.chunks[0];
  const sents = tr.sentences.slice(chunk.first, chunk.last + 1);
  const key = P.epKey(epId);
  let ctl = null, playedSecs = 0;
  const el = media.audioEl();
  const tick = setInterval(() => { if (!el.paused) playedSecs++; }, 1000);
  ctx.onLeave(() => { clearInterval(tick); ctl?.stop(); media.release(); });

  const body = h("div", { class: "page has-top" });
  let bodyClick = null;                         // set by the transcript steps; one listener for the whole flow
  body.addEventListener("click", (e) => bodyClick?.(e));
  const stepper = (n) => h("div", { class: "stack", style: "gap:8px" },
    h("div", { class: "progress" }, h("i", { style: `width:${(n / STEPS.length) * 100}%` })),
    h("span", { class: "caption-uppercase muted" }, `Step ${n + 1} of ${STEPS.length} · ${STEPS[n]}`));
  const header = h("section", { class: "stack" },
    h("div", { class: "row between" }, levelBadge(meta.level || st.level), h("span", { class: "caption muted" }, `Segment ${chunk.index + 1} / ${tr.chunks.length} · ${P.fmtTime(chunk.end - chunk.start)}`)),
    h("h1", { class: "display-sm" }, meta.title || st.title), source(meta, st));
  const show = (...k) => body.replaceChildren(...[timer && h("div", { class: "feature-card" }, timer.el), header, ...k.flat()].filter(Boolean));
  const stop = () => { ctl?.stop(); ctl = null; };

  // steps 1 and 4: no text
  function blindListen(n) {
    stop();
    const bar = h("i"), time = h("span", { class: "caption muted" }, "0:00");
    const playBtn = h("button", { class: "btn btn-primary btn-block" }, icon("play"), "Start");
    const next = h("button", { class: "btn btn-outline btn-block", onClick: () => go(n + 1) }, n === 0 ? "Next: with the transcript" : "Next: check yourself");
    const begin = async () => {
      stop();
      playBtn.replaceChildren(icon("pause"), "Pause");
      ctl = await media.playRange(key, chunk.start, chunk.end, {
        onTime: (t) => { bar.style.width = `${((t - chunk.start) / (chunk.end - chunk.start)) * 100}%`; time.textContent = `${P.fmtTime(t - chunk.start)} / ${P.fmtTime(chunk.end - chunk.start)}`; },
        onEnd: () => { playBtn.replaceChildren(icon("play"), "Play again"); },
      });
    };
    playBtn.onclick = () => (ctl && !el.paused ? (ctl.toggle(), playBtn.replaceChildren(icon("play"), "Resume")) : ctl && el.paused && el.currentTime < chunk.end - 0.2 ? (ctl.toggle(), playBtn.replaceChildren(icon("pause"), "Pause")) : begin());
    show(stepper(n), h("p", {}, n === 0 ? "Just listen. Don't read, don't pause. Get the gist." : "One more time, no text. Notice how much more you catch."),
      h("div", { class: "feature-card stack" }, h("div", { class: "progress thick" }, bar), time, playBtn), next);
  }

  // steps 2 and 3: transcript, sentence controls, tap words to save
  function withText(n) {
    stop();
    let cur = 0, loopA = null, loopB = null, looping = false, rate = 1, pending = null;
    const rows = sents.map((s, i) => {
      const words = [...s.text.matchAll(WORD)];
      let last = 0;
      const line = h("p", { class: "tr-line" });
      words.forEach((m, k) => {
        if (m.index > last) line.append(s.text.slice(last, m.index));
        line.append(h("span", { class: "w", "data-s": i, "data-k": k }, m[0]));
        last = m.index + m[0].length;
      });
      line.append(s.text.slice(last));
      const shadow = h("button", { class: "btn btn-text", onClick: async () => { await P.sendToShadow({ epId, title: meta.title || st.title, start: s.start, end: s.end, text: s.text }); toast("Added to shadowing"); } }, "Shadow");
      const who = s.speaker && s.speaker !== sents[i - 1]?.speaker ? h("span", { class: "caption-uppercase muted" }, `Speaker ${s.speaker}`) : null;
      return { s, words, el: h("div", { class: "tr-row", "data-i": i }, who, line, h("div", { class: "row" }, shadow)) };
    });
    const mark = (i) => { cur = i; rows.forEach((r, k) => r.el.toggleAttribute("aria-current", k === i)); };
    const playFrom = async (i, only = false) => {
      stop(); mark(i);
      ctl = await media.playRange(key, sents[i].start, only ? sents[i].end : chunk.end, {
        rate, loop: false,
        onTime: (t) => {
          if (looping && loopB != null && t >= loopB - 0.05) { ctl.seek(loopA); return; }
          const k = sents.findLastIndex((x) => x.start <= t + 0.05);
          if (k >= 0 && k !== cur) mark(k);
        },
      });
      rows[i].el.scrollIntoView({ block: "center", behavior: "smooth" });
    };
    const abBtn = h("button", { class: "btn btn-outline" }, "A–B");
    const abState = () => { abBtn.textContent = looping ? "A–B on" : loopA != null ? "Set B" : "Set A"; abBtn.classList.toggle("btn-primary", looping); };
    abBtn.onclick = () => {
      if (looping) { looping = false; loopA = loopB = null; ctl?.loop(false); }
      else if (loopA == null) { loopA = sents[cur].start; toast("A set. Move to the end sentence and tap again."); }
      else { loopB = Math.max(sents[cur].end, loopA + 1); looping = true; ctl?.loop(true, loopA, loopB); if (el.currentTime > loopB) ctl?.seek(loopA); }
      abState();
    };
    abState();
    const controls = h("div", { class: "feature-card stack tr-controls" },
      h("div", { class: "row", style: "justify-content:center" },
        h("button", { class: "icon-btn", "aria-label": "Previous sentence", onClick: () => playFrom(Math.max(0, cur - 1)) }, icon("skipback")),
        h("button", { class: "icon-btn", "aria-label": "Repeat sentence", onClick: () => playFrom(cur, true) }, icon("repeat")),
        h("button", { class: "btn btn-primary", "aria-label": "Play or pause", onClick: () => (ctl ? ctl.toggle() : playFrom(cur)) }, icon("play")),
        h("button", { class: "icon-btn", "aria-label": "Next sentence", onClick: () => playFrom(Math.min(sents.length - 1, cur + 1)) }, icon("skipfwd"))),
      h("div", { class: "row between" }, abBtn, speedSelect(SPEEDS_INT, (v) => { rate = v; ctl?.rate(v); }, 1)));

    // tap words: one tap = word, a second tap in the same sentence = the phrase between them
    const saveBar = h("div", { class: "feature-card stack", hidden: true });
    const clearSel = () => { pending = null; saveBar.hidden = true; body.querySelectorAll(".w.sel").forEach((x) => x.classList.remove("sel")); };
    bodyClick = (e) => {
      const w = e.target.closest(".w");
      if (!w) { const r = e.target.closest(".tr-row"); if (r && !e.target.closest("button")) playFrom(Number(r.dataset.i), true); return; }
      const i = Number(w.dataset.s), k = Number(w.dataset.k);
      pending = pending && pending.i === i && pending.a === pending.b ? { i, a: Math.min(pending.a, k), b: Math.max(pending.a, k) } : { i, a: k, b: k };
      body.querySelectorAll(".w.sel").forEach((x) => x.classList.remove("sel"));
      const ws = rows[i].words;
      rows[i].el.querySelectorAll(".w").forEach((x) => { const kk = Number(x.dataset.k); if (kk >= pending.a && kk <= pending.b) x.classList.add("sel"); });
      const phrase = sents[i].text.slice(ws[pending.a].index, ws[pending.b].index + ws[pending.b][0].length);
      saveBar.hidden = false;
      saveBar.replaceChildren(h("span", { class: "title-sm" }, phrase), h("p", { class: "caption muted" }, pending.a === pending.b ? "Tap another word in this sentence to save a phrase." : "Phrase selected."),
        h("div", { class: "row" },
          h("button", { class: "btn btn-primary grow", onClick: async () => {
            try {
              const r = await P.savePhrase({ epId, sentence: sents[i].text, phrase, start: sents[i].start, end: sents[i].end });
              toast(r.duplicate ? "Already saved" : r.clip ? "Saved with audio clip" : "Saved (no audio clip)");
              count.textContent = `${saved += r.duplicate ? 0 : 1} saved`;
              clearSel();
            } catch (err) { toast(err.message); }
          } }, "Save card"), h("button", { class: "btn btn-outline", onClick: clearSel }, "Clear")));
    };
    let saved = 0;
    const count = h("span", { class: "caption muted" }, "0 saved");
    show(stepper(n),
      n === 1 ? h("p", {}, "Follow along. Tap any sentence to hear it again, or tap words you don't know to save them as cards.") : h("p", {}, "Tap words or phrases you didn't know. Each becomes a cloze card with the sentence and a short audio clip."),
      tr.warning && h("p", { class: "caption muted" }, tr.warning),
      controls, h("div", { class: "row between" }, h("span", { class: "caption-uppercase muted" }, `Transcript · ${tr.source}`), count),
      h("div", { class: "feature-card stack" }, rows.map((r) => r.el)), saveBar,
      h("button", { class: "btn btn-primary btn-block", onClick: () => { stop(); go(n === 1 ? 2 : 3); } }, n === 1 ? "Next: save words" : "Next: listen again"));
  }

  // step 5: optional self-check (questions written by Claude, marked as such)
  async function selfCheck() {
    stop();
    show(stepper(4), h("p", { class: "muted" }, "Loading questions…"));
    let qs = null, why = "";
    try {
      const r = await fetch(apiUrl(`/podcasts/episodes/${epId}/questions?chunk=${chunk.index}`));
      if (r.ok) qs = (await r.json()).questions; else why = (await r.json().catch(() => ({}))).detail || "Not available.";
    } catch { why = "Needs a connection to your server."; }
    const finish = () => end();
    if (!qs) { show(stepper(4), h("p", { class: "muted" }, `Questions unavailable: ${why}`), h("button", { class: "btn btn-primary btn-block", onClick: finish }, "Skip")); return; }
    let score = 0, answered = 0;
    const cards = qs.map((q) => {
      const res = h("p", { class: "caption", hidden: true });
      const btns = q.options.map((o, i) => h("button", { class: "btn btn-outline btn-block", onClick: () => {
        if (btns[0].disabled) return;
        btns.forEach((b) => (b.disabled = true));
        const ok = i === q.correct; score += ok; answered++;
        res.hidden = false; res.className = `caption ${ok ? "success" : "error"}`; res.textContent = `${ok ? "Correct. " : `Not quite: "${q.options[q.correct]}". `}${q.explanation}`;
        if (answered === qs.length) setTimeout(() => toast(`${score} / ${qs.length}`), 200);
      } }, o));
      return h("div", { class: "feature-card stack" }, h("span", { class: "title-sm" }, q.question), btns, res);
    });
    show(stepper(4), h("p", { class: "caption muted" }, "Questions written by Claude (source: llm). Answer from memory."), cards,
      h("button", { class: "btn btn-primary btn-block", onClick: finish }, "Finish"));
  }

  async function end() {
    stop();
    let follow = null;
    const row = h("div", { class: "row" }, [1, 2, 3, 4, 5].map((n) => h("button", { class: "btn btn-outline grow", onClick: () => { follow = n; row.querySelectorAll("button").forEach((b, k) => b.classList.toggle("btn-primary", k + 1 === n)); } }, String(n))));
    show(h("h1", { class: "display-md" }, "Done"),
      h("div", { class: "stack" }, h("span", { class: "caption-uppercase muted" }, "How much of it could you follow? (1 = little, 5 = nearly all)"), row),
      ratingRow(epId),
      h("button", { class: "btn btn-primary btn-block", onClick: async () => {
        await P.logListen({ epId, mode: "intensive", secs: playedSecs, follow });
        await P.saveState(epId, { chunksDone: [...new Set([...(st.chunksDone || []), chunk.index])] });
        if (tr.chunks.every((c) => [...(st.chunksDone || []), chunk.index].includes(c.index))) await P.markListened(epId);
        if (timer) await timer.markDone();
        ctx.go("/today");
      } }, "Save and finish"));
  }

  // logical step → screen
  function go(n) { bodyClick = null; if (n === 0 || n === 3) blindListen(n); else if (n === 1 || n === 2) withText(n); else selfCheck(); }
  go(0);
  return h("div", {}, topNav("Intensive listening", "/today"), body);
}

// ── shadowing queue: sentences sent from podcasts ───────────────────────────
export async function shadowQueue(ctx) {
  const items = await db.getAll("shadowq");
  const rows = await Promise.all((await db.getAllKeys("shadowq")).map(async (k, i) => ({ k, ...items[i] })));
  if (!rows.length) return h("div", {}, topNav("From podcasts", "/practice/shadow"), h("div", { class: "page has-top" },
    empty("No sentences yet", "In intensive listening, tap Shadow on a sentence to add it here.")));
  let i = 0, ctl = null, rate = 1;
  ctx.onLeave(() => { ctl?.stop(); media.release(); });
  const info = h("p", { class: "caption muted" }), text = h("p", { class: "display-sm", hidden: true }), src = h("p", { class: "caption muted" });
  const showBtn = h("button", { class: "btn btn-outline", onClick: () => { text.hidden = !text.hidden; showBtn.textContent = text.hidden ? "Show text" : "Hide text"; } }, "Show text");
  const load = async (n) => {
    ctl?.stop(); ctl = null;
    i = Math.max(0, Math.min(rows.length - 1, n));
    const r = rows[i];
    info.textContent = `${i + 1} / ${rows.length} · ${P.fmtTime(r.end - r.start)}`;
    text.textContent = r.text; text.hidden = true; showBtn.textContent = "Show text"; src.textContent = r.title || "";
    await media.load(P.epKey(r.epId));
  };
  const play = async () => { ctl?.stop(); const r = rows[i]; ctl = await media.playRange(P.epKey(r.epId), r.start, r.end, { rate }); if (!ctl) toast("This episode's audio was cleaned up"); };
  await load(0);
  return h("div", {}, topNav("From podcasts", "/practice/shadow"), h("div", { class: "page has-top" },
    h("p", { class: "body-sm" }, "Listen to the sentence, then say it aloud, copying the rhythm and intonation."),
    h("section", { class: "gradient-orb-card orb-sky stack", style: "text-align:center" }, info, text, src,
      h("div", { class: "row", style: "justify-content:center" },
        h("button", { class: "icon-btn", "aria-label": "Previous", onClick: () => load(i - 1) }, icon("skipback")),
        h("button", { class: "btn btn-primary", "aria-label": "Play", onClick: play }, icon("play")),
        h("button", { class: "icon-btn", "aria-label": "Replay", onClick: play }, icon("repeat")),
        h("button", { class: "icon-btn", "aria-label": "Next", onClick: () => load(i + 1) }, icon("skipfwd")))),
    h("div", { class: "row" }, showBtn, speedSelect(SPEEDS_INT, (v) => { rate = v; ctl?.rate(v); }),
      h("button", { class: "btn btn-text", onClick: async () => { await db.del("shadowq", rows[i].k); ctx.go("/practice/shadow-queue"); } }, "Remove"))));
}
