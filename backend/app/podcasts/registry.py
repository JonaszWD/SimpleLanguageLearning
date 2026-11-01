"""The feed registry: content/podcasts/feeds.yaml (data, not code)."""

import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator

from . import config

Level = Literal["A2", "B1", "B2", "C1"]
LEVEL_ORDER = ["A2", "B1", "B2", "C1"]
HEADER = """# Podcast feed registry. Edit by hand, or use:
#   uv run python -m app.podcasts feeds resolve "<podcast name>"   (finds the RSS URL, asks before saving)
#   uv run python -m app.podcasts feeds validate
# feed_url stays empty until a URL has been resolved and confirmed. URLs are never guessed.
"""


class Feed(BaseModel):
    id: str
    title: str
    feed_url: str = ""
    level: Level
    accent: Literal["Spain", "Latin America", "mixed"] = "mixed"
    mode: Literal["extensive", "intensive", "both"] = "both"
    has_official_transcript: bool = False
    episode_length_min: int = Field(20, ge=1)
    active: bool = True
    notes: str = ""

    @field_validator("id")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", v):
            raise ValueError("id must be a lowercase slug (a-z, 0-9, -)")
        return v

    @field_validator("feed_url")
    @classmethod
    def _url(cls, v: str) -> str:
        if v and not re.match(r"https?://", v):
            raise ValueError("feed_url must be http(s)")
        return v

    @property
    def usable(self) -> bool:
        return self.active and bool(self.feed_url)


def load(path: Path | None = None) -> list[Feed]:
    path = path or config.FEEDS_FILE
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    feeds = [Feed.model_validate(f) for f in raw.get("feeds", [])]
    ids = [f.id for f in feeds]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate feed ids in " + str(path))
    return feeds


def save(feeds: list[Feed], path: Path | None = None) -> None:
    path = path or config.FEEDS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump({"feeds": [f.model_dump() for f in feeds]}, sort_keys=False, allow_unicode=True, width=100)
    path.write_text(HEADER + body, encoding="utf-8")


def get(feed_id: str, path: Path | None = None) -> Feed:
    return next(f for f in load(path) if f.id == feed_id)


def set_url(feed_id: str, url: str, path: Path | None = None) -> None:
    feeds = load(path)
    for f in feeds:
        if f.id == feed_id:
            f.feed_url = url
            save(feeds, path)
            return
    raise KeyError(feed_id)
