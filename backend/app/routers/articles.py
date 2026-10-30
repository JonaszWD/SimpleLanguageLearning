import asyncio

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import articles, daily
from ..dictionary import Dictionary

router = APIRouter(tags=["articles"])
_dictionary: Dictionary | None = None


def dictionary() -> Dictionary:
    global _dictionary
    if _dictionary is None or not _dictionary.available:
        _dictionary = Dictionary()
    return _dictionary


class ImportUrl(BaseModel):
    url: str = Field(max_length=2048)


class PasteText(BaseModel):
    title: str = Field("", max_length=300)
    text: str = Field(max_length=200_000)
    url: str = Field("", max_length=2048)
    source: str = Field("", max_length=100)


async def _run(fn, *args):
    try:
        return await asyncio.to_thread(fn, *args)
    except articles.ArticleError as exc:
        raise HTTPException(422, str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Could not reach the site.") from exc


@router.get("/feed")
async def feed(source: str) -> list[dict]:
    return await _run(articles.feed, source)


@router.post("/import")
async def import_url(body: ImportUrl) -> dict:
    page = await _run(articles.fetch, body.url)
    return await _run(lambda: articles.prepare(**page, dictionary=dictionary()))


@router.post("/prepare")
async def prepare(body: PasteText) -> dict:
    return await _run(lambda: articles.prepare(**body.model_dump(), dictionary=dictionary()))


_refresh_lock = asyncio.Lock()


async def refresh_daily() -> int:
    async with _refresh_lock:
        try:
            return await asyncio.to_thread(daily.refresh, dictionary())
        except (articles.ArticleError, httpx.HTTPError, OSError):
            return 0


@router.get("/daily")
async def daily_index() -> list[dict]:
    if not daily.index():  # first run: fill the cache before answering
        await refresh_daily()
    return daily.index()


@router.get("/daily/{aid}")
async def daily_article(aid: str) -> dict:
    art = daily.get(aid)
    if art is None:
        raise HTTPException(404, "Unknown article.")
    return art
