"""Podcast API for the app: plan, readiness, audio, transcripts, ratings. Single-user, personal use."""

import asyncio
from datetime import date as Date

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..podcasts import audio, chunks, clip, config, planner, prepare, questions, registry, transcripts
from ..podcasts.cli import config_start
from ..podcasts.store import Store

router = APIRouter(tags=["podcasts"])
_status: dict[str, str] = {}       # episode → "preparing" | "ready" | "error: …"


def store() -> Store:
    return Store()


def _ep_view(ep: dict, feeds: dict) -> dict:
    f = feeds.get(ep["feed_id"])
    tr = transcripts.load(ep["id"])
    return {"id": ep["id"], "title": ep["title"], "published": ep["published"], "feed": ep["feed_id"],
            "show": f.title if f else ep["feed_id"], "level": f.level if f else None, "accent": f.accent if f else None,
            "link": ep["link"], "minutes": round((ep.get("duration_sec") or 0) / 60) or None,
            "ready": ep["status"] == "ready" and audio.have_audio(ep),
            "state": _status.get(ep["id"]),
            "transcript": {"source": tr["source"], "timed": tr["timed"], "warning": tr.get("warning")} if tr else None}


def _day(d: str | None) -> Date:
    return Date.fromisoformat(d) if d else Date.today()


@router.get("/status")
def status() -> dict:
    s = store()
    with s.db() as c:
        eps = c.execute("SELECT COUNT(*), COALESCE(SUM(audio_bytes),0) FROM episodes WHERE audio_path IS NOT NULL").fetchone()
    return {"feeds": len([f for f in registry.load() if f.usable]), "cached_episodes": eps[0], "cache_mb": round(eps[1] / 1e6),
            "cache_limit_mb": config.CACHE_MB, "whisper": transcripts.whisper_available(), "elevenlabs": transcripts.elevenlabs_available(), "ffmpeg": clip.available(),
            "claude": bool(__import__("os").environ.get("ANTHROPIC_API_KEY"))}


@router.get("/feeds")
def feeds() -> list[dict]:
    return [f.model_dump() for f in registry.load()]


@router.get("/plan")
def plan(date: str | None = None, start: str | None = None, map: str | None = None, refresh: bool = False) -> dict:
    s, day = store(), _day(date)
    p = planner.plan_for(s, registry.load(), day, Date.fromisoformat(start) if start else config_start(),
                         planner.parse_map(map), whisper_ok=transcripts.asr_available(), save=refresh or not s.plan(day.isoformat()))
    if not refresh and s.plan(day.isoformat()) and not p["items"]:
        pass
    fm = {f.id: f for f in registry.load()}
    for item in p["items"]:
        ep = s.episode(item["episode"])
        item["ready"] = bool(ep and ep["status"] == "ready" and audio.have_audio(ep))
        item["state"] = _status.get(item["episode"])
    p["offline"] = prepare.status(s, day)
    return p


class PrepareBody(BaseModel):
    date: str | None = None
    start: str | None = None
    map: str | None = None
    episodes: list[str] | None = None


def _run_prepare(body: PrepareBody) -> None:
    s = store()
    ids = body.episodes
    if ids is None:
        day = _day(body.date) if body.date else prepare.tomorrow()
        plan_ = planner.plan_for(s, registry.load(), day, Date.fromisoformat(body.start) if body.start else config_start(),
                                 planner.parse_map(body.map), whisper_ok=transcripts.asr_available())
        ids = [i["episode"] for i in plan_["items"]]
    for ep_id in ids:
        _status[ep_id] = "preparing"
        try:
            prepare.prepare_episode(ep_id, s)
            _status[ep_id] = "ready"
        except Exception as exc:  # noqa: BLE001
            _status[ep_id] = f"error: {str(exc)[:120]}"


@router.post("/prepare", status_code=202)
def prepare_now(body: PrepareBody, bg: BackgroundTasks) -> dict:
    bg.add_task(_run_prepare, body)
    return {"accepted": True}


def _episode(ep_id: str) -> dict:
    ep = store().episode(ep_id)
    if not ep:
        raise HTTPException(404, "Unknown episode.")
    return ep


@router.get("/episodes")
def episodes(feed: str | None = None, limit: int = 12) -> list[dict]:
    """Newest episodes (per feed if given) with their transcript state, so any of them can be opened on demand."""
    fmap = {f.id: f for f in registry.load()}
    s = store()
    ids = [feed] if feed else [f.id for f in fmap.values() if f.active and f.feed_url]
    out = []
    for fid in ids:
        out += [_ep_view(e, fmap) for e in sorted(s.episodes(fid), key=lambda e: e["published"] or "", reverse=True)[:limit]]
    return out


@router.get("/episodes/{ep_id}")
def episode(ep_id: str) -> dict:
    ep = _episode(ep_id)
    out = _ep_view(ep, {f.id: f for f in registry.load()})
    tr = transcripts.load(ep_id)
    out["chunks"] = chunks.chunk(tr["sentences"]) if tr and tr["timed"] else []
    return out


@router.get("/episodes/{ep_id}/audio")
def episode_audio(ep_id: str) -> FileResponse:
    ep = _episode(ep_id)
    if not audio.have_audio(ep):
        raise HTTPException(409, "Audio is not downloaded yet.")
    store().touch(ep_id)
    return FileResponse(ep["audio_path"], media_type="audio/mpeg")     # Starlette serves Range requests


@router.get("/episodes/{ep_id}/transcript")
def episode_transcript(ep_id: str) -> dict:
    _episode(ep_id)
    tr = transcripts.load(ep_id)
    if not tr:
        raise HTTPException(404, "No transcript.")
    return {**tr, "chunks": chunks.chunk(tr["sentences"]) if tr["timed"] else []}


@router.get("/episodes/{ep_id}/clip")
def episode_clip(ep_id: str, start: float, end: float) -> FileResponse:
    ep = _episode(ep_id)
    if not audio.have_audio(ep):
        raise HTTPException(409, "Audio is not downloaded yet.")
    try:
        return FileResponse(clip.cut(__import__("pathlib").Path(ep["audio_path"]), start, end), media_type="audio/mpeg")
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/episodes/{ep_id}/questions")
async def episode_questions(ep_id: str, chunk: int = 0) -> dict:
    _episode(ep_id)
    tr = transcripts.load(ep_id)
    if not tr or not tr["timed"]:
        raise HTTPException(404, "No timed transcript.")
    parts = chunks.chunk(tr["sentences"])
    if chunk >= len(parts):
        raise HTTPException(404, "Unknown segment.")
    c = parts[chunk]
    text = " ".join(s["text"] for s in tr["sentences"][c["first"]:c["last"] + 1])
    try:
        return await asyncio.to_thread(questions.generate, text)
    except RuntimeError as exc:
        raise HTTPException(503, f"{exc}. Questions need the Claude API.") from exc


class Rating(BaseModel):
    episode: str
    rating: str


@router.post("/ratings")
def rate(body: Rating) -> dict:
    if body.rating not in ("too easy", "right", "too hard"):
        raise HTTPException(422, "rating must be 'too easy', 'right' or 'too hard'")
    ep = _episode(body.episode)
    f = next((f for f in registry.load() if f.id == ep["feed_id"]), None)
    store().add_rating(ep["id"], ep["feed_id"], f.level if f else "B1", body.rating)
    return {"ok": True}


class Listened(BaseModel):
    episode: str


@router.post("/listened")
def listened(body: Listened) -> dict:
    import time
    _episode(body.episode)
    store().update_episode(body.episode, listened_at=time.time())
    return {"ok": True}
