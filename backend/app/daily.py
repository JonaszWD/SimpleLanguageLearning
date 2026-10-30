"""Daily article cache: fresh El Mundo articles, extracted and glossed ahead of time.

The app syncs this index in the background, so Reading always has new material.
"""

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from . import articles

ARTICLES_DIR = Path(os.environ.get(
    "ARTICLES_DIR", Path(__file__).resolve().parents[1] / "data" / "articles"))
SOURCE = "elmundo"        # El País can't be fetched automatically
MIN_WORDS, MAX_WORDS = 250, 1200
KEEP_DAYS = 14
PER_REFRESH = 12
REFRESH_SECONDS = 3 * 3600


def article_id(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:12]


def _published(item: dict) -> str:
    try:
        return parsedate_to_datetime(item["published"]).astimezone(timezone.utc).isoformat()
    except (KeyError, TypeError, ValueError):
        return datetime.now(timezone.utc).isoformat()


def refresh(dictionary, directory: Path = ARTICLES_DIR) -> int:
    """Fetch new articles from the feed. Returns how many were added."""
    directory.mkdir(parents=True, exist_ok=True)
    added = 0
    for item in articles.feed(SOURCE, limit=40):
        if added >= PER_REFRESH:
            break
        aid = article_id(item["url"])
        path = directory / f"{aid}.json"
        if path.exists() or item["pasteOnly"]:
            continue
        try:
            page = articles.fetch(item["url"])
            art = articles.prepare(**page, dictionary=dictionary)
        except (articles.ArticleError, OSError, ValueError):
            continue
        if art["truncated"] or not MIN_WORDS <= art["words"] <= MAX_WORDS:
            path.write_text(json.dumps({"skip": True}))  # remember, so we don't refetch it
            continue
        art.update(id=aid, published=_published(item))
        path.write_text(json.dumps(art, ensure_ascii=False))
        added += 1
    _prune(directory)
    return added


def _prune(directory: Path) -> None:
    cutoff = time.time() - KEEP_DAYS * 86400
    for p in directory.glob("*.json"):
        if p.stat().st_mtime < cutoff:
            p.unlink()


def index(directory: Path = ARTICLES_DIR) -> list[dict]:
    out = []
    for p in directory.glob("*.json") if directory.is_dir() else []:
        d = json.loads(p.read_text())
        if d.get("skip"):
            continue
        out.append({k: d[k] for k in ("id", "title", "source", "words", "published")})
    return sorted(out, key=lambda a: a["published"], reverse=True)


def get(aid: str, directory: Path = ARTICLES_DIR) -> dict | None:
    p = directory / f"{aid}.json"
    if not aid.isalnum() or not p.exists():
        return None
    d = json.loads(p.read_text())
    return None if d.get("skip") else d
