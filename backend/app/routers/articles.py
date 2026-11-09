import asyncio

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import articles, daily, translate as translation
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


class TranslateRequest(BaseModel):
    sentence: str = Field(max_length=translation.MAX_SENTENCE)
    word: str = Field(max_length=100)
    offset: int | None = Field(None, ge=0, le=translation.MAX_SENTENCE)  # where the word starts in the sentence


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


@router.post("/translate")
async def translate_sentence(body: TranslateRequest) -> dict:
    if not translation.available():
        raise HTTPException(503, "Sentence translation needs DEEPL_API_KEY on the server.")
    try:
        return await asyncio.to_thread(translation.translate, body.sentence, body.word, body.offset)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:  # DeepL errors: network, quota, bad key
        raise HTTPException(502, "Translation failed. Try again.") from exc


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
