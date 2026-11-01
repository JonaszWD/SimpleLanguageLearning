"""Tatoeba sentences, taken from the Anki deck "Spanish 9000 sentences" (CC BY 2.0 FR)."""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from ..anki_import import parse_apkg

ATTRIBUTION = "Tatoeba.org, CC BY 2.0 FR"
WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)?")


@dataclass(frozen=True)
class Sentence:
    es: str
    en: str
    es_id: str
    en_id: str

    @property
    def tokens(self) -> list[str]:
        return WORD.findall(self.es)

    @property
    def words(self) -> int:
        return len(self.es.split())


def load(apkg: Path, cache: Path | None = None) -> list[Sentence]:
    if cache and cache.exists():
        return [Sentence(**d) for d in json.loads(cache.read_text())]
    parsed = parse_apkg(apkg.read_bytes())
    model = next(m for m in parsed["models"] if m["cloze"])
    ix = {f: i for i, f in enumerate(model["fields"])}
    out = []
    for n in parsed["notes"]:
        f = n["fields"]
        out.append(Sentence(f[ix["SpanishSentence"]].strip(), f[ix["EnglishSentence"]].strip(),
                            f[ix["SpanishSentenceID"]], f[ix["EnglishSentenceID"]]))
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps([s.__dict__ for s in out], ensure_ascii=False))
    return out
