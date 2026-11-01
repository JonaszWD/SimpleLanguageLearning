"""Load and validate the grammar syllabus (content/grammar/syllabus.json)."""

import json
import os
from datetime import date, timedelta
from pathlib import Path

from pydantic import BaseModel, model_validator

GRAMMAR_DIR = Path(os.environ.get("GRAMMAR_DIR", Path(__file__).resolve().parents[3] / "content" / "grammar"))


class Bilingual(BaseModel):
    es: str
    en: str


class Topic(BaseModel):
    id: str
    week: int
    level: str
    phase: str = ""
    type: str = "topic"                     # "topic" | "review"
    title: Bilingual
    explanation: Bilingual
    key_rules: list[str]
    common_mistakes: list[str]
    tags: list[str] = []
    reviews: list[str] = []                 # for review/mock-test weeks: topics they draw exercises from
    verify: list[str] = []                  # content the author is unsure about

    @model_validator(mode="after")
    def _review_has_sources(self):
        if self.type == "review" and not self.reviews:
            raise ValueError(f"review topic {self.id} needs 'reviews'")
        return self


class Track(BaseModel):
    id: str
    title: str
    topics: list[Topic]

    @model_validator(mode="after")
    def _unique(self):
        ids = [t.id for t in self.topics]
        weeks = [t.week for t in self.topics]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate topic ids")
        if len(set(weeks)) != len(weeks):
            raise ValueError("duplicate weeks")
        known = set(ids)
        for t in self.topics:
            missing = set(t.reviews) - known
            if missing:
                raise ValueError(f"{t.id} reviews unknown topics {sorted(missing)}")
        return self


class Syllabus(BaseModel):
    schema_version: int
    note: str = ""
    tracks: list[Track]

    def track(self, track_id: str = "b1-b2") -> Track:
        return next(t for t in self.tracks if t.id == track_id)

    def topic(self, topic_id: str) -> Topic:
        return next(t for tr in self.tracks for t in tr.topics if t.id == topic_id)


def load(path: Path | None = None) -> Syllabus:
    return Syllabus.model_validate(json.loads((path or GRAMMAR_DIR / "syllabus.json").read_text(encoding="utf-8")))


def topic_for_date(syl: Syllabus, start: date, today: date, track_id: str = "b1-b2") -> Topic:
    """The topic of the week containing `today`. Before the start: week 1. After the end: last week."""
    topics = sorted(syl.track(track_id).topics, key=lambda t: t.week)
    week = max(0, (today - start).days) // 7 + 1
    return next((t for t in topics if t.week == min(week, topics[-1].week)), topics[-1])


def week_start(start: date, week: int) -> date:
    return start + timedelta(days=7 * (week - 1))
