"""Download episode audio for personal offline use, and keep the cache within its limits.

Audio is stored locally and only served back to the owner's own app. It is never re-hosted.
"""

import time
from pathlib import Path

import httpx
from mutagen import File as MutagenFile

from . import config
from .store import Store


class AudioError(RuntimeError):
    pass


def audio_path(ep: dict) -> Path:
    url = ep["audio_url"].split("?")[0].lower()
    ext = next((e for e in (".mp3", ".m4a", ".aac", ".ogg", ".wav") if url.endswith(e)), ".mp3")
    return config.AUDIO_DIR / f"{ep['id']}{ext}"


def have_audio(ep: dict) -> bool:
    return bool(ep.get("audio_path")) and Path(ep["audio_path"]).exists()


def download(ep: dict, store: Store, client: httpx.Client | None = None) -> Path:
    if have_audio(ep):
        store.touch(ep["id"])
        return Path(ep["audio_path"])
    config.ensure_dirs()
    dest = audio_path(ep)
    tmp = dest.with_suffix(dest.suffix + ".part")
    own = client is None
    client = client or httpx.Client(follow_redirects=True, timeout=60)
    cap = config.MAX_AUDIO_MB * 1_000_000
    try:
        with client.stream("GET", ep["audio_url"], headers={"User-Agent": config.USER_AGENT}) as r:
            r.raise_for_status()
            size = 0
            with tmp.open("wb") as fh:
                for chunk in r.iter_bytes(1 << 16):
                    size += len(chunk)
                    if size > cap:
                        raise AudioError(f"file larger than {config.MAX_AUDIO_MB} MB")
                    fh.write(chunk)
    except (httpx.HTTPError, AudioError) as exc:
        tmp.unlink(missing_ok=True)
        store.update_episode(ep["id"], status="error", error=f"download: {exc}"[:200])
        raise AudioError(str(exc)) from exc
    finally:
        if own:
            client.close()
    tmp.replace(dest)
    try:   # a odd tag header must not fail a download that worked
        meta = MutagenFile(dest)
        duration = int(meta.info.length) if meta and meta.info else ep.get("duration_sec")
    except Exception:  # noqa: BLE001 - mutagen raises many error types
        duration = ep.get("duration_sec")
    store.update_episode(ep["id"], audio_path=str(dest), audio_bytes=dest.stat().st_size, duration_sec=duration,
                         accessed_at=time.time(), status="audio", error=None)
    return dest


def cleanup(store: Store, max_mb: int | None = None, keep_days: int | None = None, now: float | None = None) -> dict:
    """Delete audio of episodes listened more than `keep_days` ago, then the least recently used
    audio until the cache fits. Episodes in a plan (tomorrow's) and unlistened ones are kept first."""
    max_bytes = (max_mb if max_mb is not None else config.CACHE_MB) * 1_000_000
    keep = (keep_days if keep_days is not None else config.KEEP_DAYS) * 86400
    now = now or time.time()
    planned = store.planned_ids()
    removed: list[str] = []

    def drop(ep: dict) -> None:
        Path(ep["audio_path"]).unlink(missing_ok=True)
        store.update_episode(ep["id"], audio_path=None, audio_bytes=0, status="listened" if ep.get("listened_at") else "new")
        removed.append(ep["id"])

    eps = [e for e in store.episodes(limit=10_000) if have_audio(e)]
    for ep in eps:
        if ep.get("listened_at") and now - ep["listened_at"] > keep and ep["id"] not in planned:
            drop(ep)
    eps = [e for e in eps if e["id"] not in removed]
    total = sum(e["audio_bytes"] for e in eps)
    # then LRU, listened first, never planned ones
    for ep in sorted(eps, key=lambda e: (e.get("listened_at") is None, e.get("accessed_at") or 0)):
        if total <= max_bytes:
            break
        if ep["id"] in planned:
            continue
        total -= ep["audio_bytes"]
        drop(ep)
    return {"removed": removed, "bytes_after": total}
