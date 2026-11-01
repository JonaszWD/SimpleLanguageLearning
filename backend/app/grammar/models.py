"""Exercise schema shared by every generator (deterministic and LLM)."""

import hashlib
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ExerciseType = Literal["cloze", "conjugation", "multiple_choice", "transformation", "error_correction"]
Source = Literal["tatoeba", "wiktionary", "llm"]
Confidence = Literal["high", "medium", "low"]
BLANK = "____"


class Verify(BaseModel):
    """What to check the answer against in the conjugation data."""
    lemma: str
    mood: Literal["indicative", "subjunctive", "imperative"]
    tense: str | None = None
    person: int | None = Field(None, ge=1, le=3)
    number: Literal["s", "p"] | None = None
    compound: bool = False  # haber + participle (he hablado, hubiera hablado)
    aux_tense: str | None = None  # tense of haber when compound


class Exercise(BaseModel):
    id: str = ""
    topic: str
    level: Literal["A2", "B1", "B2", "C1"]
    type: ExerciseType
    prompt: str                       # instruction shown above the item
    text: str = ""                    # sentence (cloze / MC contain ____ ); empty for conjugation
    answer: str
    alternatives: list[str] = []      # other accepted answers
    options: list[str] = []           # multiple choice only, answer included
    hint: str = ""
    explanation: str = ""
    translation: str = ""             # English translation (Tatoeba)
    source: Source
    source_ids: dict[str, str] = {}   # e.g. {"tatoeba_es": "123", "tatoeba_en": "456"} or {"wiktionary": "hablar"}
    attribution: str = ""
    verify: Verify | None = None
    confidence: Confidence = "high"
    notes: list[str] = []             # why a human should look (for review.json)
    tags: list[str] = []

    @field_validator("answer", "prompt")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty")
        return v.strip()

    @model_validator(mode="after")
    def _shape(self):
        t = self.type
        if t in ("cloze", "multiple_choice") and self.text.count(BLANK) != 1:
            raise ValueError(f"{t} text needs exactly one {BLANK}")
        if t == "multiple_choice":
            if not 2 <= len(self.options) <= 4 or len(set(o.lower() for o in self.options)) != len(self.options):
                raise ValueError("multiple_choice needs 2-4 distinct options")
            if self.answer not in self.options:
                raise ValueError("answer must be one of the options")
        elif self.options:
            raise ValueError("options only belong to multiple_choice")
        if t in ("transformation", "error_correction"):
            if not self.text.strip():
                raise ValueError(f"{t} needs a source sentence in text")
            if self.text.strip().lower() == self.answer.strip().lower():
                raise ValueError(f"{t}: answer equals the question")
        if t == "conjugation" and self.text:
            raise ValueError("conjugation has no sentence")
        if self.source == "llm" and self.confidence == "high":
            self.confidence = "medium"  # LLM items are never auto-trusted
        return self

    def key(self) -> str:
        """Identity for duplicate detection."""
        return "|".join([self.type, self.text.lower().strip(), self.answer.lower().strip(), self.hint.lower()])

    def with_id(self) -> "Exercise":
        digest = hashlib.sha1(f"{self.topic}|{self.key()}".encode()).hexdigest()[:12]
        return self.model_copy(update={"id": f"{self.topic}-{digest}"})

    def all_answers(self) -> list[str]:
        return [self.answer, *self.alternatives]
