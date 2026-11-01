import { resample, floatToPcm16, pcm16ToFloat, bytesToBase64, base64ToInt16, pcmRate, interpret } from "../js/talk.js";
import { sessionsFor } from "../js/plan.js";
const ok = (c, m) => { if (!c) { console.log("FAIL", m); process.exitCode = 1; } else console.log("ok  ", m); };

const ramp = Float32Array.from({ length: 480 }, (_, i) => i / 480);
ok(resample(ramp, 48000, 16000).length === 160, "48k → 16k keeps 1/3 of samples");
ok(resample(ramp, 16000, 16000) === ramp, "same rate is a no-op");
ok(Math.abs(resample(Float32Array.of(1, 1, 1, 0, 0, 0), 48000, 16000)[0] - 1) < 1e-6, "downsample averages");

const pcm = floatToPcm16(Float32Array.of(0, 1, -1, 2, -2));
ok(pcm[0] === 0 && pcm[1] === 32767 && pcm[2] === -32768 && pcm[3] === 32767 && pcm[4] === -32768, "float → pcm16 clamps");
const back = pcm16ToFloat(Int16Array.of(0, 32767, -32768));
ok(back[1] === 1 && back[2] === -1, "pcm16 → float full scale");

const bytes = new Uint8Array(new Int16Array([1, -2, 300, -32768]).buffer);
ok(base64ToInt16(bytesToBase64(bytes)).join() === "1,-2,300,-32768", "base64 round trip");
ok(bytesToBase64(new Uint8Array(100000)).length > 100000, "large chunk encodes without stack overflow");

ok(pcmRate("pcm_16000") === 16000 && pcmRate("pcm_44100") === 44100 && pcmRate("ulaw_8000") === null, "audio format parsing");
ok(interpret({ type: "conversation_initiation_metadata", conversation_initiation_metadata_event: { agent_output_audio_format: "pcm_24000", user_input_audio_format: "pcm_16000" } }).outRate === 24000, "metadata → output rate");
ok(interpret({ type: "conversation_initiation_metadata", conversation_initiation_metadata_event: { user_input_audio_format: "pcm_8000" } }).supported === false, "wrong mic format flagged");
ok(interpret({ type: "user_transcript", user_transcription_event: { user_transcript: "hola" } }).text === "hola", "user transcript");
ok(interpret({ type: "agent_response", agent_response_event: { agent_response: "¿Qué tal?" } }).who === "agent", "agent response");
ok(interpret({ type: "ping", ping_event: { event_id: 7 } }).eventId === 7, "ping carries event id");
ok(interpret({ type: "whatever" }).kind === "ignore" && interpret(null).kind === "ignore", "unknown messages ignored");

const SAT = new Date(2026, 10, 7), SUN = new Date(2026, 10, 8);
const kinds = (d) => sessionsFor(d).flatMap((s) => s.tasks).map((t) => `${t.id}:${t.min}`);
ok(kinds(SAT).join() === "s1-anki:10,s2-talk:15", "Saturday = Anki + 15 min talk");
ok(kinds(SUN).join() === "s1-anki:10", "Sunday stays Anki only");
