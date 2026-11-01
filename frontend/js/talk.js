// Live conversation with an ElevenLabs Agent. The server only hands out a signed WebSocket URL
// (the API key never reaches the phone); audio goes straight between the phone and ElevenLabs.
// Wire format: mic = 16 kHz mono PCM16 as base64 JSON; agent audio = PCM16 at the rate in its metadata.
import { apiUrl } from "./config.js";

export const MIC_RATE = 16000;
const CHUNK_MS = 100;

// ── pure helpers (tested in Node) ───────────────────────────────────────────
/** Average-downsample mono Float32 audio from `from` Hz to `to` Hz. */
export function resample(input, from, to) {
  if (from === to) return input;
  const ratio = from / to;
  const out = new Float32Array(Math.floor(input.length / ratio));
  for (let i = 0; i < out.length; i++) {
    const a = Math.floor(i * ratio), b = Math.max(a + 1, Math.min(input.length, Math.floor((i + 1) * ratio)));
    let sum = 0;
    for (let j = a; j < b; j++) sum += input[j];
    out[i] = sum / (b - a);
  }
  return out;
}

export function floatToPcm16(f32) {
  const out = new Int16Array(f32.length);
  for (let i = 0; i < f32.length; i++) {
    const s = Math.max(-1, Math.min(1, f32[i]));
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return out;
}

export function pcm16ToFloat(i16) {
  const out = new Float32Array(i16.length);
  for (let i = 0; i < i16.length; i++) out[i] = i16[i] / (i16[i] < 0 ? 0x8000 : 0x7fff);
  return out;
}

export function bytesToBase64(bytes) {
  let s = "";
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(s);
}

export function base64ToInt16(b64) {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new Int16Array(bytes.buffer, 0, bytes.length >> 1);
}

/** "pcm_16000" → 16000; anything else (e.g. ulaw) is unsupported → null. */
export function pcmRate(format) {
  const m = /^pcm_(\d+)$/.exec(format || "");
  return m ? Number(m[1]) : null;
}

/** Turn one server message into what the UI needs. Unknown types are ignored. */
export function interpret(msg) {
  switch (msg?.type) {
    case "conversation_initiation_metadata": {
      const e = msg.conversation_initiation_metadata_event || {};
      return { kind: "ready", outRate: pcmRate(e.agent_output_audio_format) ?? 16000, supported: pcmRate(e.user_input_audio_format) === MIC_RATE || !e.user_input_audio_format };
    }
    case "audio": return { kind: "audio", pcm: msg.audio_event?.audio_base_64 };
    case "user_transcript": return { kind: "line", who: "you", text: msg.user_transcription_event?.user_transcript || "" };
    case "agent_response": return { kind: "line", who: "agent", text: msg.agent_response_event?.agent_response || "" };
    case "interruption": return { kind: "interrupt" };
    case "ping": return { kind: "ping", eventId: msg.ping_event?.event_id };
    default: return { kind: "ignore" };
  }
}

// ── server ──────────────────────────────────────────────────────────────────
export async function talkStatus() {
  try {
    const r = await fetch(apiUrl("/talk/status"), { cache: "no-store" });
    return r.ok ? await r.json() : null;
  } catch { return null; }
}

async function signedUrl() {
  const r = await fetch(apiUrl("/talk/session"), { method: "POST" });
  if (!r.ok) {
    const detail = await r.json().then((d) => d.detail).catch(() => "");
    throw new Error(r.status === 502 && /permission/.test(detail) ? `ElevenLabs key lacks permission. ${detail}` : detail || `Server error ${r.status}`);
  }
  return (await r.json()).signed_url;
}

const MIC_WORKLET = `class Mic extends AudioWorkletProcessor {
  process(inputs) { const c = inputs[0][0]; if (c) this.port.postMessage(c.slice(0)); return true; }
}
registerProcessor("mic", Mic);`;

/**
 * Start a conversation. handlers: { onState(state), onLine({who,text}), onLevel?, onError(err) }.
 * state: "connecting" | "listening" | "speaking" | "ended". Returns { stop(), mute(bool) }.
 */
export async function startTalk({ variables = {}, onState, onLine, onError }) {
  let ws, ctx, stream, node, playhead = 0, ended = false, muted = false;
  const sources = new Set();
  let outRate = 16000;

  const end = (err) => {
    if (ended) return;
    ended = true;
    if (err) onError?.(err);
    try { ws?.close(); } catch {}
    try { node?.disconnect(); } catch {}
    stream?.getTracks().forEach((t) => t.stop());
    stopPlayback();
    ctx?.close().catch(() => {});
    onState("ended");
  };
  const stopPlayback = () => {
    for (const s of sources) { try { s.stop(); } catch {} }
    sources.clear();
    playhead = 0;
  };
  const play = (b64) => {
    const f32 = pcm16ToFloat(base64ToInt16(b64));
    const buf = ctx.createBuffer(1, f32.length, outRate);
    buf.copyToChannel(f32, 0);
    const src = ctx.createBufferSource();
    src.buffer = buf;
    src.connect(ctx.destination);
    playhead = Math.max(playhead, ctx.currentTime + 0.02);
    src.start(playhead);
    playhead += buf.duration;
    sources.add(src);
    onState("speaking");
    src.onended = () => {
      sources.delete(src);
      if (!sources.size && !ended) onState("listening");
    };
  };

  try {
    onState("connecting");
    // Create the context and ask for the mic inside the tap, before any await that could lose the user gesture on iOS.
    ctx = new (window.AudioContext || window.webkitAudioContext)();
    const [url, mic] = await Promise.all([
      signedUrl(),
      navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } }),
    ]);
    stream = mic;
    await ctx.resume();
    const blob = URL.createObjectURL(new Blob([MIC_WORKLET], { type: "text/javascript" }));
    await ctx.audioWorklet.addModule(blob);
    URL.revokeObjectURL(blob);

    ws = new WebSocket(url);
    await new Promise((res, rej) => { ws.onopen = res; ws.onerror = () => rej(new Error("Couldn't reach ElevenLabs")); });
    ws.send(JSON.stringify({ type: "conversation_initiation_client_data", dynamic_variables: variables }));

    let pending = [], pendingLen = 0;
    const per = MIC_RATE * CHUNK_MS / 1000;
    node = new AudioWorkletNode(ctx, "mic");
    node.port.onmessage = (e) => {
      if (muted || ws.readyState !== 1) return;
      const mono = resample(e.data, ctx.sampleRate, MIC_RATE);
      pending.push(mono); pendingLen += mono.length;
      if (pendingLen < per) return;
      const all = new Float32Array(pendingLen);
      let o = 0;
      for (const p of pending) { all.set(p, o); o += p.length; }
      pending = []; pendingLen = 0;
      const pcm = floatToPcm16(all);
      ws.send(JSON.stringify({ user_audio_chunk: bytesToBase64(new Uint8Array(pcm.buffer)) }));
    };
    ctx.createMediaStreamSource(stream).connect(node);
    // The worklet must be pulled to run in Safari; route it to a silent sink.
    const sink = ctx.createGain(); sink.gain.value = 0;
    node.connect(sink).connect(ctx.destination);

    ws.onmessage = (ev) => {
      let m;
      try { m = interpret(JSON.parse(ev.data)); } catch { return; }
      if (m.kind === "ready") {
        outRate = m.outRate;
        if (!m.supported) end(new Error("Unsupported audio format from ElevenLabs"));
        else onState("listening");
      } else if (m.kind === "audio" && m.pcm) play(m.pcm);
      else if (m.kind === "line" && m.text) onLine({ who: m.who, text: m.text });
      else if (m.kind === "interrupt") { stopPlayback(); onState("listening"); }
      else if (m.kind === "ping") ws.send(JSON.stringify({ type: "pong", event_id: m.eventId }));
    };
    ws.onclose = () => end();
    ws.onerror = () => end(new Error("Connection lost"));
  } catch (e) {
    end(e.name === "NotAllowedError" ? new Error("Microphone blocked. Allow it in Settings → Safari → Microphone.") : e);
  }

  return { stop: () => end(), mute: (v) => { muted = v; } };
}
