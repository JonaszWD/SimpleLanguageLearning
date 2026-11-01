"""Background automation: poll feeds, prepare tomorrow's episodes every evening, clean the cache."""

import asyncio
import logging
from datetime import date as Date
from datetime import datetime

from . import audio, config, fetcher, planner, prepare, registry
from .cli import config_start
from .store import Store

log = logging.getLogger("podcasts")
_done: dict[str, str] = {}   # job → date it last ran


def run_once(now: datetime | None = None) -> dict:
    """One tick. Safe to call often: every job guards itself."""
    now = now or datetime.now()
    store = Store()
    out: dict = {}
    feeds = [f for f in registry.load() if f.usable]
    out["poll"] = [fetcher.poll(f, store).status for f in feeds]    # respects the polling interval itself
    if now.hour >= config.EVENING_HOUR and _done.get("prepare") != now.date().isoformat():
        day = prepare.tomorrow()
        out["prepare"] = prepare.prepare_date(day, store, config_start(), planner.parse_map(None))["prepared"]
        _done["prepare"] = now.date().isoformat()
    if _done.get("cleanup") != now.date().isoformat():
        out["cleanup"] = audio.cleanup(store)
        _done["cleanup"] = now.date().isoformat()
    return out


async def loop() -> None:
    if not config.AUTOMATION:
        return
    while True:
        try:
            await asyncio.to_thread(run_once)
        except Exception:  # noqa: BLE001
            log.exception("podcast automation tick failed")
        await asyncio.sleep(30 * 60)
