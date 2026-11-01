"""Transcripts, in priority order: (1) the publisher's, (2) Whisper run locally, (3) none.

Everything is normalised to sentences with timestamps:
    {"source": "publisher" | "whisper", "timed": bool, "sentences": [{"i", "start", "end", "text"}], ...}
"""

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from . import config
from .store import Store

WHISPER_WARNING = "Automatic (Whisper) transcript: it can contain errors, especially names and fast speech."
SCRIBE_WARNING = "Automatic (ElevenLabs) transcript: timestamps are accurate, but names and fast speech can still be wrong."
END = re.compile(r"[.?!…][\"'»”)]*$")


@dataclass
class Transcript:
    source: str
    timed: bool
    sentences: list[dict]
    model: str | None = None
    language: str = "es"

    def to_json(self) -> dict:
        d = {"source": self.source, "timed": self.timed, "language": self.language, "model": self.model,
             "sentences": self.sentences, "generated_at": int(time.time())}
        if self.source == "whisper":
            d["warning"] = WHISPER_WARNING
        elif self.source == "elevenlabs":
            d["warning"] = SCRIBE_WARNING
        return d


# ── parsers ─────────────────────────────────────────────────────────────────
def _secs(ts: str) -> float:
    ts = ts.strip().replace(",", ".")
    parts = [float(p) for p in ts.split(":")]
    out = 0.0
    for p in parts:
        out = out * 60 + p
    return out


TIME = re.compile(r"((?:\d+:)?\d{1,2}:\d{2}[.,]\d{1,3})\s*-->\s*((?:\d+:)?\d{1,2}:\d{2}[.,]\d{1,3})")


def parse_cues(text: str) -> list[dict]:
    """SRT and WebVTT share the same cue timing line."""
    cues = []
    blocks = re.split(r"\n\s*\n", text.replace("\r", "").strip())
    for b in blocks:
        lines = b.split("\n")
        for i, line in enumerate(lines):
            m = TIME.search(line)
            if m:
                body = re.sub(r"<[^>]+>", "", " ".join(lines[i + 1:])).strip()
                if body:
                    cues.append({"start": _secs(m.group(1)), "end": _secs(m.group(2)), "text": re.sub(r"\s+", " ", body)})
                break
    return cues


def parse_podcast_json(obj: dict) -> list[dict]:
    """Podcasting 2.0 JSON transcript."""
    return [{"start": float(s["startTime"]), "end": float(s.get("endTime", s["startTime"])), "text": s["body"].strip()}
            for s in obj.get("segments", []) if s.get("body", "").strip()]


def sentences_from_cues(cues: list[dict]) -> list[dict]:
    """Merge caption lines into sentences (a sentence ends at . ? ! …)."""
    out, cur = [], None
    for c in cues:
        if cur is None:
            cur = {"start": c["start"], "end": c["end"], "text": c["text"]}
        else:
            cur["end"] = c["end"]
            cur["text"] += " " + c["text"]
        if END.search(c["text"]):
            out.append(cur)
            cur = None
    if cur:
        out.append(cur)
    return [{"i": i, **s, "text": s["text"].strip()} for i, s in enumerate(out)]


def sentences_from_words(words: list[dict], max_gap: float = 1.2) -> list[dict]:
    """Whisper word timestamps → sentences, cut at sentence punctuation or a long pause."""
    out, cur = [], []
    for w in words:
        if cur and (w["start"] - cur[-1]["end"] > max_gap or w.get("speaker") != cur[-1].get("speaker")):
            out.append(cur)
            cur = []
        cur.append(w)
        if END.search(w["word"].strip()):
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    res = [{"i": i, "start": round(float(s[0]["start"]), 2), "end": round(float(s[-1]["end"]), 2),
            "text": "".join(w["word"] for w in s).strip()} for i, s in enumerate(out) if s]
    for r, s in zip(res, out):
        if s[0].get("speaker"):
            r["speaker"] = s[0]["speaker"]
    return res


def sentences_from_plain(text: str) -> list[dict]:
    """Publisher text without timestamps: usable for reading along, not for highlighting."""
    text = re.sub(r"<[^>]+>", " ", text)
    parts = [p.strip() for p in re.split(r"(?<=[.?!…])\s+", re.sub(r"\s+", " ", text)) if p.strip()]
    return [{"i": i, "start": None, "end": None, "text": p} for i, p in enumerate(parts)]


# ── publisher ───────────────────────────────────────────────────────────────
PREFERENCE = ["application/json", "text/vtt", "application/x-subrip", "text/srt", "text/plain", "text/html"]


def fetch_publisher(ep: dict, client: httpx.Client | None = None) -> Transcript | None:
    refs = sorted(ep.get("transcripts") or [], key=lambda r: PREFERENCE.index(r["type"]) if r["type"] in PREFERENCE else 99)
    own = client is None
    client = client or httpx.Client(follow_redirects=True, timeout=30)
    try:
        for ref in refs:
            try:
                r = client.get(ref["url"], headers={"User-Agent": config.USER_AGENT})
                r.raise_for_status()
            except httpx.HTTPError:
                continue
            kind = ref["type"]
            if kind == "application/json":
                cues = parse_podcast_json(r.json())
                sents = sentences_from_cues(cues)
                timed = True
            elif kind in ("text/vtt", "application/x-subrip", "text/srt") or TIME.search(r.text[:2000]):
                sents = sentences_from_cues(parse_cues(r.text))
                timed = True
            else:
                sents, timed = sentences_from_plain(r.text), False
            if sents:
                return Transcript("publisher", timed, sents, language=ref.get("language") or "es")
    finally:
        if own:
            client.close()
    return None


# ── whisper ─────────────────────────────────────────────────────────────────
def whisper_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return config.WHISPER_ENABLED
    except ImportError:
        return False


def decode_audio(path: Path):
    """16 kHz mono float32 via ffmpeg. faster-whisper's own decoder breaks with some PyAV versions."""
    import shutil
    import subprocess

    import numpy as np
    if not shutil.which("ffmpeg"):
        return str(path)          # let faster-whisper try its own decoder
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar", "16000", "-"],
                         check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def whisper_transcribe(path: Path, model_name: str | None = None, *, model=None) -> Transcript:
    """Local transcription with faster-whisper (install: uv sync --extra whisper)."""
    model_name = model_name or config.WHISPER_MODEL
    if model is None:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError("faster-whisper is not installed: run `uv sync --extra whisper`") from exc
        model = WhisperModel(model_name, device=config.WHISPER_DEVICE, compute_type=config.WHISPER_COMPUTE)
    segments, info = model.transcribe(decode_audio(path), language="es", word_timestamps=True, vad_filter=True)
    words = [{"word": w.word, "start": w.start, "end": w.end} for seg in segments for w in (seg.words or [])]
    return Transcript("whisper", True, sentences_from_words(words), model=model_name, language=info.language)


# ── ElevenLabs Scribe ───────────────────────────────────────────────────────
SCRIBE_URL = "https://api.elevenlabs.io/v1/speech-to-text"


def elevenlabs_available() -> bool:
    return config.ELEVENLABS_ENABLED and bool(config.elevenlabs_key())


def words_from_scribe(payload: dict) -> list[dict]:
    """Scribe response → [{word, start, end, speaker}]. Skips spacing and audio events like (risas)."""
    letters: dict[str, str] = {}
    out = []
    for w in payload.get("words", []):
        if w.get("type", "word") != "word" or not w.get("text", "").strip():
            continue
        sp = w.get("speaker_id")
        if sp is not None:
            letters.setdefault(sp, chr(ord("A") + len(letters) % 26))
        out.append({"word": " " + w["text"].strip(), "start": float(w["start"]), "end": float(w["end"]),
                    "speaker": letters.get(sp)})
    return out


def elevenlabs_transcribe(path: Path, *, client: httpx.Client | None = None) -> Transcript:
    """Timestamped transcript with speaker labels from ElevenLabs Scribe. The audio file is uploaded to ElevenLabs."""
    key = config.elevenlabs_key()
    if not key:
        raise RuntimeError("ELEVENLABS_API_KEY is not set")
    own = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(900, connect=30))
    try:
        with open(path, "rb") as fh:
            r = client.post(SCRIBE_URL, headers={"xi-api-key": key},
                            data={"model_id": config.ELEVENLABS_MODEL, "language_code": "spa", "diarize": "true",
                                  "timestamps_granularity": "word", "tag_audio_events": "false"},
                            files={"file": (path.name, fh)})
    finally:
        if own:
            client.close()
    if r.status_code >= 400:
        raise RuntimeError(f"elevenlabs {r.status_code}: {r.text[:160]}")
    payload = r.json()
    sents = sentences_from_words(words_from_scribe(payload))
    if not sents:
        raise RuntimeError("elevenlabs returned no words")
    return Transcript("elevenlabs", True, sents, model=config.ELEVENLABS_MODEL, language=payload.get("language_code") or "es")


def asr_available() -> bool:
    return elevenlabs_available() or whisper_available()


# ── storage + priority ──────────────────────────────────────────────────────
def transcript_path(ep_id: str) -> Path:
    return config.TRANSCRIPT_DIR / f"{ep_id}.json"


def load(ep_id: str) -> dict | None:
    p = transcript_path(ep_id)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def ensure(ep: dict, store: Store, audio: Path | None, *, client=None, whisper=whisper_transcribe, allow_whisper: bool = True,
           scribe=elevenlabs_transcribe) -> dict | None:
    """Publisher transcript first; otherwise (none, or no timestamps) automatic: ElevenLabs if keyed, else Whisper."""
    existing = load(ep["id"])
    if existing:
        return existing
    config.ensure_dirs()
    result = fetch_publisher(ep, client) if ep.get("transcripts") else None
    if (result is None or not result.timed) and audio and allow_whisper:
        engines = []
        if scribe is not elevenlabs_transcribe or elevenlabs_available():
            engines.append(("elevenlabs", scribe))
        if whisper is not whisper_transcribe or whisper_available():
            engines.append(("whisper", whisper))
        for name, run in engines:
            try:
                result = run(audio)
                break
            except Exception as exc:  # noqa: BLE001 - try the next engine; keep a text-only publisher transcript
                store.update_episode(ep["id"], error=f"{name}: {exc}"[:200])
    if result is None:
        store.update_episode(ep["id"], transcript_source="none")
        return None
    data = result.to_json()
    transcript_path(ep["id"]).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    store.update_episode(ep["id"], transcript_source=result.source)
    return data
