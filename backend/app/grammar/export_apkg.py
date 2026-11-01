"""Export grammar exercises as Anki decks (.apkg), one per topic.

Model ids, deck ids and note guids are derived from stable names, so importing a re-exported deck
updates the existing notes instead of creating duplicates. The ids are different from the Tatoeba
deck's, so the two never interfere.

    uv run python -m app.grammar.export_apkg                  # all topics → content/grammar/apkg/
    uv run python -m app.grammar.export_apkg --topic por-para
"""

import argparse
import hashlib
import html
import json
from pathlib import Path

import genanki

from . import syllabus
from .models import BLANK, Exercise

FIELDS = ["Text", "Answer", "Explanation", "Topic", "Level", "Source", "SourceID"]
# Fixed forever: changing these makes Anki treat the notes as a different note type.
CLOZE_MODEL_ID = 1873001001
BASIC_MODEL_ID = 1873001002
FOOTER = "<div class='meta'>{{Topic}} · {{Level}} · {{Source}}</div>"
CSS = ".card{font-family:Inter,Arial,sans-serif;font-size:20px;text-align:center}.meta{font-size:12px;color:#777;margin-top:12px}.expl{font-size:15px;color:#555;margin-top:8px}"

CLOZE_MODEL = genanki.Model(
    CLOZE_MODEL_ID, "Grammar cloze", fields=[{"name": f} for f in FIELDS], model_type=genanki.Model.CLOZE, css=CSS,
    templates=[{"name": "Cloze", "qfmt": "{{cloze:Text}}",
                "afmt": "{{cloze:Text}}<br><div class='expl'>{{Explanation}}</div>" + FOOTER}])
BASIC_MODEL = genanki.Model(
    BASIC_MODEL_ID, "Grammar basic", fields=[{"name": f} for f in FIELDS], css=CSS,
    templates=[{"name": "Card 1", "qfmt": "{{Text}}",
                "afmt": "{{FrontSide}}<hr id=answer>{{Answer}}<div class='expl'>{{Explanation}}</div>" + FOOTER}])


def stable_int(name: str, bits: int = 31) -> int:
    return int(hashlib.sha1(name.encode()).hexdigest()[:12], 16) % (1 << bits)


def _e(s: str) -> str:
    return html.escape(s, quote=False)


def source_label(ex: Exercise) -> str:
    return {"tatoeba": "Tatoeba", "wiktionary": "Wiktionary", "llm": "LLM"}[ex.source]


def source_id(ex: Exercise) -> str:
    return ex.id if not ex.source_ids else f"{ex.id} | " + ", ".join(f"{k}:{v}" for k, v in ex.source_ids.items())


def to_note(ex: Exercise, title: str) -> genanki.Note:
    topic_tag = ex.topic
    if ex.type == "cloze":
        hint = f"::{_e(ex.hint)}" if ex.hint else ""
        text = _e(ex.text).replace(BLANK, "{{c1::" + _e(ex.answer) + hint + "}}")
        model, answer = CLOZE_MODEL, ex.answer
        if ex.alternatives:
            answer += " (also: " + ", ".join(ex.alternatives) + ")"
    else:
        lines = [f"<b>{_e(ex.prompt)}</b>"]
        if ex.hint:
            lines.append(f"({_e(ex.hint)})")
        if ex.text:
            lines.append(_e(ex.text))
        if ex.type == "multiple_choice":
            lines.append(" &nbsp; ".join(f"{chr(65 + i)}) {_e(o)}" for i, o in enumerate(ex.options)))
        text, model, answer = "<br>".join(lines), BASIC_MODEL, _e(ex.answer)
        if ex.alternatives:
            answer += "<br>(also: " + _e("; ".join(ex.alternatives)) + ")"
    return genanki.Note(
        model=model, guid=genanki.guid_for("grammar", ex.id),
        fields=[text, answer, _e(ex.explanation), title, ex.level, source_label(ex), source_id(ex)],
        tags=[topic_tag, ex.level, "grammar", ex.type.replace("_", "-")])


def export_topic(topic_id: str, base: Path, out_dir: Path) -> Path | None:
    f = base / "exercises" / f"{topic_id}.json"
    if not f.exists():
        return None
    exercises = [Exercise.model_validate(e) for e in json.loads(f.read_text())["exercises"]]
    if not exercises:
        return None
    title = syllabus.load(base / "syllabus.json").topic(topic_id).title.en
    deck = genanki.Deck(stable_int(f"grammar-deck:{topic_id}"), f"Grammar::{title}")
    for ex in sorted(exercises, key=lambda e: e.id):  # stable order
        deck.add_note(to_note(ex, title))
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{topic_id}.apkg"
    genanki.Package(deck).write_to_file(path)
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--topic", action="append")
    ap.add_argument("--base", type=Path, default=syllabus.GRAMMAR_DIR)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    out = a.out or a.base / "apkg"
    syl = syllabus.load(a.base / "syllabus.json")
    for t in syl.track().topics:
        if a.topic and t.id not in a.topic:
            continue
        p = export_topic(t.id, a.base, out)
        if p:
            print(f"{t.week:>2} {t.id:<32} {p.name} ({p.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
