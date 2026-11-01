"""Quality gates every exercise must pass before it is published."""

import re
from dataclasses import dataclass, field

from pydantic import ValidationError

from .conjugation import Conjugator
from .models import BLANK, Exercise

MAX_WORDS = 14

# Deliberately small: Tatoeba is crowd-sourced and may contain crude sentences. Extend as needed.
BLOCKLIST = re.compile(
    r"\b(put[ao]s?|puta|mierda|joder|co[ñn]o|cabr[oó]n|gilipollas|pendej[oa]s?|culo|polla|follar|"
    r"matar|violar|violaci[oó]n|suicid\w*|nazi\w*|terroris\w*|bomba|"
    r"fuck\w*|shit|bitch|cunt|dick|rape\w*|kill\w*)\b", re.I)
ODD = re.compile(r"https?://|www\.|@|[<>{}\[\]\\|#*_=~^]|\d{4,}")


@dataclass
class Report:
    accepted: list[Exercise] = field(default_factory=list)
    review: list[tuple[Exercise, list[str]]] = field(default_factory=list)    # kept, but a human should look
    rejected: list[tuple[dict, list[str]]] = field(default_factory=list)      # dropped (raw item + reasons)

    def merge(self, other: "Report") -> None:
        self.accepted += other.accepted
        self.review += other.review
        self.rejected += other.rejected


def _word_count(*texts: str) -> int:
    return max((len(t.replace(BLANK, "X").split()) for t in texts if t), default=0)


def verify_forms(ex: Exercise, conj: Conjugator) -> list[str]:
    """Check conjugated answers against the data. Returns problems (empty = verified)."""
    v = ex.verify
    if v is None:
        return []
    if not conj.knows(v.lemma):
        return [f"verb '{v.lemma}' is not in the conjugation data (unverified)"]
    if v.compound:
        valid = conj.compound(v.lemma, v.mood, v.aux_tense or "present", v.person or 3, v.number or "s",
                              flags=None, any_participle=True)
    else:
        valid = conj.forms(v.lemma, v.mood, v.tense, v.person, v.number)
    if not valid:
        return [f"no {v.mood} {v.tense} forms for '{v.lemma}' in the data"]
    bad = [a for a in ex.all_answers() if a.lower() not in valid]
    return [f"'{a}' is not a {v.mood} {v.tense or ''} form of {v.lemma} (expected one of {sorted(valid)})" for a in bad]


def check(raw: dict | Exercise, conj: Conjugator, seen: set[str], *, verify_required: bool = False) -> tuple[Exercise | None, list[str], list[str]]:
    """Returns (exercise or None, reject reasons, review reasons)."""
    try:
        ex = raw if isinstance(raw, Exercise) else Exercise.model_validate(raw)
    except ValidationError as e:
        return None, [f"schema: {err['msg']}" for err in e.errors()], []

    reject: list[str] = []
    review: list[str] = list(ex.notes)

    if _word_count(ex.text, ex.answer if ex.type in ("transformation", "error_correction") else "") > MAX_WORDS:
        reject.append(f"longer than {MAX_WORDS} words")
    blob = " ".join([ex.text, ex.answer, *ex.alternatives, *ex.options, ex.hint])
    if BLOCKLIST.search(blob):
        reject.append("blocked content")
    if ODD.search(blob.replace(BLANK, " ")):
        reject.append("unnatural characters")
    if ex.type in ("cloze", "transformation", "error_correction") and ex.text and not re.search(r"[.!?…»”\"]$", ex.text.strip()) and ex.source != "llm":
        review.append("sentence does not end with punctuation")
    if ex.text and ex.text.strip()[:1].islower():
        review.append("sentence starts lower-case")

    problems = verify_forms(ex, conj)
    if problems:
        # A wrong form is fatal. An unknown verb only means we could not check it.
        (review if all("unverified" in p for p in problems) else reject).extend(problems)
    elif verify_required and ex.verify is None:
        review.append("no verification metadata")

    k = ex.key()
    if k in seen:
        reject.append("duplicate")
    if reject:
        return None, reject, []
    seen.add(k)
    ex = ex.with_id()
    if ex.confidence != "high":
        review.append(f"confidence {ex.confidence}")
    return ex, [], review


def run(items: list[dict | Exercise], conj: Conjugator, seen: set[str] | None = None) -> Report:
    seen = set() if seen is None else seen
    rep = Report()
    for raw in items:
        ex, rej, rev = check(raw, conj, seen)
        if ex is None:
            rep.rejected.append((raw.model_dump() if isinstance(raw, Exercise) else raw, rej))
        elif rev:
            rep.review.append((ex, rev))
            rep.accepted.append(ex)
        else:
            rep.accepted.append(ex)
    return rep
