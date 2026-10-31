// Audio from the `media` store. One persistent <audio> element: iOS only lets it play
// after it was started from a tap, so callers prepare() ahead and play() inside the tap.
import * as db from "./db.js";

const el = new Audio();

// iOS Safari pauses other apps' audio (music, podcasts) when a page plays sound. The Audio Session
// API lets us mix instead: "ambient" plays alongside other audio and leaves it untouched. Caveat:
// ambient follows the iPhone's silent switch, so "playback" is offered as the opt-out.
let mix = true;
export function setMixing(on) {
  mix = on;
  applySession();
}
function applySession() {
  try {
    if (navigator.audioSession) navigator.audioSession.type = mix ? "ambient" : "playback";
  } catch { /* unsupported value: keep the default */ }
}
applySession();
const urls = new Map(); // name -> object URL
let current = null;

export async function urlFor(name) {
  if (!urls.has(name)) {
    const row = await db.get("media", name);
    if (!row) return null;
    urls.set(name, URL.createObjectURL(row.blob));
  }
  return urls.get(name);
}

export function release() {
  el.pause();
  for (const u of urls.values()) URL.revokeObjectURL(u);
  urls.clear();
  current = null;
}

export async function prepare(name) {
  const u = await urlFor(name);
  if (u && current !== name) { el.src = u; current = name; }
  return !!u;
}

export function play(rate = 1) {
  applySession();
  el.playbackRate = rate;
  el.currentTime = 0;
  return el.play().catch(() => {});
}

export async function playNow(name) {
  if (current === name) return play();
  if (await prepare(name)) return play();
}

// Play a list of sounds back to back. Resolves when finished or cancelled.
export async function playSequence(names, { rate = 1, gap = 400, isCancelled = () => false } = {}) {
  for (let i = 0; i < names.length; i++) {
    if (isCancelled()) return;
    const u = await urlFor(names[i]);
    if (!u) continue;
    el.src = u; current = names[i];
    applySession();
    el.playbackRate = rate;
    await new Promise((res) => {
      const done = () => { el.removeEventListener("ended", done); el.removeEventListener("pause", done); res(); };
      el.addEventListener("ended", done);
      el.addEventListener("pause", done);
      el.play().catch(done);
    });
    if (el.ended === false && isCancelled()) return;
    if (i < names.length - 1) await new Promise((r) => setTimeout(r, gap));
  }
}

export function stop() { el.pause(); }
