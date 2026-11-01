import { h, icon, fmtClock } from "../util.js";
import { currentTopic } from "../grammar.js";
import { startTalk, talkStatus } from "../talk.js";
import { topNav, timerFor, empty } from "./shared.js";

const STATE_TEXT = { connecting: "Connecting…", listening: "Your turn", speaking: "Partner speaking", ended: "" };

// Saturday talking unit: free conversation with an AI partner. Needs the server (it holds the ElevenLabs key).
export async function talk(ctx) {
  const timer = await timerFor(ctx);
  const status = await talkStatus();
  const nav = topNav("Talk");
  if (!status) return h("div", {}, nav, h("div", { class: "page has-top" }, empty("Needs the server", "Open the app from your Docker server.")));
  if (!status.available) return h("div", {}, nav, h("div", { class: "page has-top" }, empty("ElevenLabs key missing", "Add ELEVENLABS_API_KEY to .env and restart.")));

  const gTopic = await currentTopic(new Date()).catch(() => null);
  const focus = gTopic ? gTopic.title.es || gTopic.title.en : "ninguna en particular";
  let sc = status.scenarios[Math.floor(Math.random() * status.scenarios.length)];

  // English guidance for the chosen scenario: the goal and a few things to try saying.
  const guide = h("div", { class: "stack talk-guide" });
  const paintGuide = () => guide.replaceChildren(
    h("p", { class: "title-sm" }, sc.goal),
    h("ul", { class: "body-sm talk-starters" }, sc.starters.map((x) => h("li", {}, x))));
  // Native <select>: opens the platform picker (iOS wheel sheet).
  const topicSel = h("select", { class: "select-pill", name: "topic", "aria-label": "Topic", onChange: (e) => { sc = status.scenarios.find((x) => x.id === e.target.value); paintGuide(); } },
    status.scenarios.map((x) => h("option", { value: x.id, selected: x.id === sc.id }, x.title)));
  const stateEl = h("p", { class: "talk-state title-sm", role: "status", "aria-live": "polite" });
  const log = h("div", { class: "talk-log", "aria-label": "Transcript" });
  const err = h("p", { class: "error", role: "alert", hidden: true });
  const clock = h("span", { class: "caption muted" });
  const main = h("button", { class: "btn btn-primary btn-lg btn-block" });
  const mute = h("button", { class: "btn btn-outline", hidden: true, "aria-pressed": "false" }, icon("mic"), "Mute");
  const options = h("div", { class: "stack" }, topicSel);

  let session = null, secs = 0, tick = null, muted = false, live = false;
  const setMain = () => {
    main.replaceChildren(icon("mic"), live ? "End conversation" : "Start talking");
    main.className = `btn btn-lg btn-block ${live ? "btn-outline" : "btn-primary"}`;
    options.hidden = live;
    mute.hidden = !live;
  };
  const addLine = ({ who, text }) => {
    log.append(h("p", { class: `talk-line ${who}` }, h("span", { class: "sr-only" }, who === "you" ? "You: " : "Partner: "), text));
    log.lastChild.scrollIntoView({ block: "end", behavior: "smooth" });
  };
  const finish = () => {
    live = false; clearInterval(tick); session = null; setMain();
    if (timer && secs > 0) clock.textContent = fmtClock(secs);
  };
  const stop = () => session?.stop();

  main.addEventListener("click", async () => {
    if (live) return stop();
    live = true; err.hidden = true; log.replaceChildren(); secs = 0; muted = false; setMain();
    tick = setInterval(() => { if (!document.hidden) { secs++; clock.textContent = fmtClock(secs); } }, 1000);
    session = await startTalk({
      variables: { topic: sc.topic, goal: sc.goal, focus },
      onState: (s) => { stateEl.textContent = STATE_TEXT[s] || ""; stateEl.dataset.state = s; if (s === "ended") finish(); },
      onLine: addLine,
      onError: (e) => { err.textContent = e.message; err.hidden = false; },
    });
  });
  mute.addEventListener("click", () => {
    muted = !muted; session?.mute(muted);
    mute.setAttribute("aria-pressed", String(muted));
    mute.replaceChildren(icon("mic"), muted ? "Unmute" : "Mute");
  });
  ctx.onLeave(stop);
  paintGuide();
  setMain();

  const done = timer && h("button", { class: "btn btn-outline btn-block", onClick: async () => { await timer.markDone(); ctx.go("/today"); } }, "Mark done");
  return h("div", {}, nav,
    h("div", { class: "page has-top" },
      timer && h("div", { class: "feature-card" }, timer.el),
      h("div", { class: "feature-card stack talk-card" }, options, guide, stateEl, clock, err, h("div", { class: "row" }, main), mute),
      log, done));
}
