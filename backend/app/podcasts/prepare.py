"""Make an episode ready for offline use: audio, transcript (publisher → Whisper), chunks."""

import time
from datetime import date as Date
from datetime import timedelta

import httpx

from . import audio, chunks, config, planner, registry, transcripts
from .store import Store


def prepare_episode(ep_id: str, store: Store, client: httpx.Client | None = None, *, allow_whisper: bool = True,
                    whisper=transcripts.whisper_transcribe) -> dict:
    ep = store.episode(ep_id)
    if ep is None:
        raise KeyError(ep_id)
    path = audio.download(ep, store, client)
    tr = transcripts.ensure(ep, store, path, client=client, allow_whisper=allow_whisper, whisper=whisper)
    ready = {"id": ep_id, "audio": True, "transcript": tr["source"] if tr else None, "timed": bool(tr and tr["timed"]),
             "chunks": len(chunks.chunk(tr["sentences"])) if tr and tr["timed"] else 0}
    store.update_episode(ep_id, status="ready", accessed_at=time.time())   # keep any transcript error visible
    ready["error"] = (store.episode(ep_id) or {}).get("error")
    return ready


def prepare_date(day: Date, store: Store, start: Date, mode_map=None, *, allow_whisper: bool = True, client=None) -> dict:
    """Plan `day` and prepare every selected episode (this is what runs each evening for tomorrow)."""
    feeds = registry.load()
    plan = planner.plan_for(store, feeds, day, start, mode_map, whisper_ok=allow_whisper and transcripts.asr_available())
    out = []
    for item in plan["items"]:
        try:
            out.append(prepare_episode(item["episode"], store, client, allow_whisper=allow_whisper))
        except Exception as exc:  # noqa: BLE001 - one bad episode must not block the others
            out.append({"id": item["episode"], "error": str(exc)[:200]})
    return {"plan": plan, "prepared": out}


def tomorrow() -> Date:
    return Date.today() + timedelta(days=1)


def status(store: Store, day: Date) -> dict:
    """'Ready for offline' summary for a day's plan."""
    items = store.plan(day.isoformat())
    eps = [store.episode(i["episode"]) for i in items]
    ready = [e for e in eps if e and e["status"] == "ready" and audio.have_audio(e)]
    return {"date": day.isoformat(), "planned": len(items), "ready": len(ready), "all_ready": bool(items) and len(ready) == len(items)}
