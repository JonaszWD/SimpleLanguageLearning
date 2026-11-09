// App-wide playback gain, 0-300 %. iOS ignores HTMLAudioElement.volume (and music in another app is
// often louder than a phone speaker), so the boost goes through Web Audio: gain, then a limiter so
// loud speech is lifted without clipping. No DOM access here: media.js and talk.js build the nodes.
export const MIN = 0;
export const MAX = 3;

let vol = 1;
const subs = new Set();

export const getVolume = () => vol;
export const clampVolume = (v) => Math.min(MAX, Math.max(MIN, Number.isFinite(v) ? v : 1));

export function setVolume(v) {
  vol = clampVolume(v);
  subs.forEach((f) => f(vol));
}

export function onVolume(f) {
  subs.add(f);
  return () => subs.delete(f);
}

/** gain → limiter → speakers, on the given AudioContext. Connect sources to `.input`. */
export function makeBus(ctx) {
  const input = ctx.createGain();
  const limiter = ctx.createDynamicsCompressor();
  limiter.threshold.value = -6;
  limiter.knee.value = 6;
  limiter.ratio.value = 20;
  limiter.attack.value = 0.003;
  limiter.release.value = 0.15;
  input.gain.value = vol;
  input.connect(limiter).connect(ctx.destination);
  const off = onVolume((v) => { input.gain.value = v; });
  return { input, close: off };
}
