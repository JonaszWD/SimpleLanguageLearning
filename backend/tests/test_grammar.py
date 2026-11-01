import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest

from app.anki_import import parse_apkg
from app.grammar import export_apkg, llm, quality, syllabus
from app.grammar.conjugation import CONJ_PATH, Conjugator
from app.grammar.models import Exercise, Verify

ROOT = Path(__file__).resolve().parents[2]
TATOEBA = ROOT / "9000_Spanish_sentences_-_difficulty_sorted_with_native_audio.apkg"
GRAMMAR = ROOT / "content" / "grammar"


@pytest.fixture
def conj(tmp_path):
    """Tiny conjugation table so gate tests don't depend on the big Wiktionary build."""
    path = tmp_path / "c.sqlite"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE conj (lemma TEXT, form TEXT, mood TEXT, tense TEXT, person INT, number TEXT, flags TEXT)")
    rows = [("hablar", "hable", "subjunctive", "present", 1, "s", ""), ("hablar", "hables", "subjunctive", "present", 2, "s", ""),
            ("hablar", "hablado", "participle", None, None, None, ""), ("haber", "he", "indicative", "present", 1, "s", ""),
            ("haber", "has", "indicative", "present", 2, "s", "")]
    con.executemany("INSERT INTO conj VALUES (?,?,?,?,?,?,?)", rows)
    con.commit()
    con.close()
    return Conjugator(path)


def cloze(**kw):
    base = dict(topic="subj-deseos", level="B1", type="cloze", prompt="Completa.", text="Quiero que ____ conmigo.",
                answer="hables", hint="hablar", source="tatoeba", explanation="x",
                verify=Verify(lemma="hablar", mood="subjunctive", tense="present", person=2, number="s"))
    base.update(kw)
    return base


# ── syllabus ────────────────────────────────────────────────────────────────
def test_syllabus_is_valid_and_ordered():
    syl = syllabus.load(GRAMMAR / "syllabus.json")
    topics = syl.track().topics
    assert len(topics) == 32 and [t.week for t in topics] == list(range(1, 33))
    assert topics[0].id == "ser-estar" and topics[-1].id == "simulacro-b2"
    assert all(t.key_rules and t.common_mistakes and t.explanation.es and t.explanation.en for t in topics)


def test_topic_for_date():
    syl = syllabus.load(GRAMMAR / "syllabus.json")
    start = date(2026, 11, 2)
    assert syllabus.topic_for_date(syl, start, date(2026, 11, 2)).week == 1
    assert syllabus.topic_for_date(syl, start, date(2026, 11, 8)).week == 1
    assert syllabus.topic_for_date(syl, start, date(2026, 11, 9)).week == 2
    assert syllabus.topic_for_date(syl, start, date(2026, 10, 1)).week == 1      # before the start
    assert syllabus.topic_for_date(syl, start, date(2030, 1, 1)).week == 32      # after the end


# ── quality gates ───────────────────────────────────────────────────────────
def test_valid_item_passes_and_gets_stable_id(conj):
    rep = quality.run([cloze()], conj)
    assert len(rep.accepted) == 1 and not rep.rejected
    again = quality.run([cloze()], conj)
    assert rep.accepted[0].id == again.accepted[0].id


def test_wrong_conjugation_is_rejected(conj):
    rep = quality.run([cloze(answer="hablas")], conj)  # indicative, not subjunctive
    assert not rep.accepted and "not a subjunctive" in rep.rejected[0][1][0]


def test_unknown_verb_goes_to_review_not_rejected(conj):
    rep = quality.run([cloze(verify=Verify(lemma="zzzar", mood="subjunctive", tense="present"))], conj)
    assert len(rep.accepted) == 1 and "unverified" in rep.review[0][1][0]


def test_compound_forms_are_composed_from_haber(conj):
    ok = cloze(text="Espero que ya ____ mucho.", answer="has hablado",
               verify=Verify(lemma="hablar", mood="indicative", person=2, number="s", compound=True, aux_tense="present"))
    assert quality.run([ok], conj).accepted
    bad = {**ok, "answer": "has hablar"}
    assert quality.run([bad], conj).rejected


@pytest.mark.parametrize("patch,reason", [
    ({"text": "Quiero que ____ con una persona muy amable que conocí ayer en la estación de tren."}, "longer than"),
    ({"text": "Quiero que ____ con la puta."}, "blocked"),
    ({"text": "Mira http://x.com ____ ya."}, "unnatural"),
    ({"text": "Quiero que conmigo."}, "schema"),            # no blank
])
def test_gates_reject(conj, patch, reason):
    rep = quality.run([cloze(**patch)], conj)
    assert not rep.accepted and reason in " ".join(rep.rejected[0][1])


def test_duplicates_rejected(conj):
    rep = quality.run([cloze(), cloze()], conj)
    assert len(rep.accepted) == 1 and rep.rejected[0][1] == ["duplicate"]


def test_multiple_choice_schema(conj):
    mc = dict(topic="t", level="B1", type="multiple_choice", prompt="Elige.", text="Quiero que ____.", answer="hables",
              options=["hables", "hablas"], source="tatoeba")
    assert quality.run([mc], conj).accepted
    assert quality.run([{**mc, "options": ["hablas", "habla"]}], conj).rejected   # answer missing from options
    assert quality.run([{**mc, "options": ["hables", "Hables"]}], conj).rejected  # duplicates


def test_llm_items_are_never_high_confidence(conj):
    item = dict(cloze(), source="llm", confidence="high")
    assert quality.run([item], conj).accepted[0].confidence == "medium"


# ── LLM step: cache, dry run, no key ────────────────────────────────────────
TOPIC = {"id": "subj-duda", "level": "B1", "title": {"en": "Doubt", "es": "Duda"}, "explanation": {"en": "e", "es": "e"},
         "key_rules": ["r1"], "common_mistakes": ["m1"]}


class FakeClient:
    calls = 0

    class messages:  # noqa: N801
        @staticmethod
        def create(**kw):
            FakeClient.calls += 1
            assert kw["tool_choice"]["name"] == "submit_exercises"
            item = {"type": "cloze", "prompt": "Completa.", "text": "No creo que ____ verdad.", "answer": "sea",
                    "explanation": "duda", "natural": True, "confidence": "high"}
            bad = {**item, "text": "No creo que ____ raro.", "natural": False}

            class Block:
                type = "tool_use"
                input = {"items": [item, bad]}
            return type("M", (), {"content": [Block]})


def test_llm_caches_and_second_run_is_free(tmp_path):
    FakeClient.calls = 0
    first, status = llm.generate(TOPIC, ["cloze"], 2, client=FakeClient, cache_dir=tmp_path)
    second, status2 = llm.generate(TOPIC, ["cloze"], 2, client=FakeClient, cache_dir=tmp_path)
    assert (status, status2) == ("generated", "cached") and FakeClient.calls == 1 and first == second
    good, bad = llm.to_exercise_dicts(first, TOPIC)
    assert len(good) == 1 and good[0]["source"] == "llm" and "not natural" in bad[0][1][0]


def test_llm_dry_run_makes_no_call_and_needs_no_key(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    items, status = llm.generate(TOPIC, ["cloze"], 3, cache_dir=tmp_path, dry_run=True)
    assert items is None and status == "dry-run" and not list(tmp_path.iterdir())
    assert "dry run" in capsys.readouterr().out


def test_llm_without_key_fails_clearly(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="ANTHROPIC_API_KEY"):
        llm.generate(TOPIC, ["cloze"], 3, cache_dir=tmp_path)


def test_no_api_key_in_source():
    for p in (ROOT / "backend" / "app").rglob("*.py"):
        assert "sk-ant" not in p.read_text(), p


# ── generated content (needs the local conjugation build) ───────────────────
needs_data = pytest.mark.skipif(not CONJ_PATH.exists() or not (GRAMMAR / "exercises").exists(), reason="local data not built")


@needs_data
def test_shipped_exercises_pass_every_gate():
    conj, seen = Conjugator(), set()
    total = 0
    for f in sorted((GRAMMAR / "exercises").glob("*.json")):
        for raw in json.loads(f.read_text())["exercises"]:
            ex, reject, _ = quality.check(raw, conj, seen)
            assert ex is not None, (f.name, reject, raw["text"])
            assert ex.level and ex.topic == f.stem and ex.type and ex.source in ("tatoeba", "wiktionary", "llm")
            assert ex.source != "tatoeba" or ex.source_ids.get("tatoeba_es")
            total += 1
    assert total > 300


# ── Anki export ─────────────────────────────────────────────────────────────
def _write_topic(tmp_path, exercises):
    (tmp_path / "exercises").mkdir()
    (tmp_path / "syllabus.json").write_text((GRAMMAR / "syllabus.json").read_text())
    (tmp_path / "exercises" / "subj-deseos.json").write_text(json.dumps({"topic": "subj-deseos", "exercises": exercises}))


def _exercises(conj):
    items = [cloze(), cloze(text="Espero que ____ pronto.", answer="hables", alternatives=["hable"]),
             dict(topic="subj-deseos", level="B1", type="multiple_choice", prompt="Elige.", text="Quiero que ____ mucho.",
                  answer="hables", options=["hables", "hablas", "hablarás"], source="tatoeba", source_ids={"tatoeba_es": "7"}),
             dict(topic="subj-deseos", level="B1", type="conjugation", prompt="Conjuga: presente de subjuntivo · tú",
                  answer="hables", hint="hablar", source="wiktionary", source_ids={"wiktionary": "hablar"})]
    return [e.model_dump() for e in quality.run(items, conj).accepted]


def test_apkg_ids_are_stable_and_reimport_updates(tmp_path, conj):
    _write_topic(tmp_path, _exercises(conj))
    a = export_apkg.export_topic("subj-deseos", tmp_path, tmp_path / "a")
    b = export_apkg.export_topic("subj-deseos", tmp_path, tmp_path / "b")
    pa, pb = parse_apkg(a.read_bytes()), parse_apkg(b.read_bytes())
    assert [n["guid"] for n in pa["notes"]] == [n["guid"] for n in pb["notes"]]      # same notes → update, not duplicate
    assert {m["id"] for m in pa["models"]} == {export_apkg.CLOZE_MODEL_ID, export_apkg.BASIC_MODEL_ID}
    assert pa["decks"] == pb["decks"] or {d["id"] for d in pa["decks"]} >= {d["id"] for d in pb["decks"]}


def test_apkg_fields_tags_and_cloze_types(tmp_path, conj):
    _write_topic(tmp_path, _exercises(conj))
    p = parse_apkg(export_apkg.export_topic("subj-deseos", tmp_path, tmp_path / "o").read_bytes())
    models = {m["name"]: m for m in p["models"]}
    assert models["Grammar cloze"]["cloze"] and not models["Grammar basic"]["cloze"]
    for m in models.values():
        assert m["fields"] == ["Text", "Answer", "Explanation", "Topic", "Level", "Source", "SourceID"]
    cloze_note = next(n for n in p["notes"] if n["mid"] == export_apkg.CLOZE_MODEL_ID)
    assert "{{c1::hables::hablar}}" in cloze_note["fields"][0]
    assert {"subj-deseos", "B1", "grammar"} <= set(cloze_note["tags"])


@pytest.mark.skipif(not TATOEBA.exists(), reason="Tatoeba deck not present")
def test_existing_tatoeba_deck_format_is_unaffected(tmp_path, conj):
    """Import-check: our models must not collide with, or alter, the Tatoeba deck's model."""
    tat = parse_apkg(TATOEBA.read_bytes())
    model = tat["models"][0]
    assert model["cloze"] and model["fields"][:8] == ["EnglishSentenceID", "SpanishSentenceID", "EnglishSentence",
                                                       "SpanishSentence", "ClozeWord", "Difficulty", "Text", "Audio"]
    assert model["id"] not in (export_apkg.CLOZE_MODEL_ID, export_apkg.BASIC_MODEL_ID)
    _write_topic(tmp_path, _exercises(conj))
    ours = parse_apkg(export_apkg.export_topic("subj-deseos", tmp_path, tmp_path / "o").read_bytes())
    assert not ({m["id"] for m in ours["models"]} & {model["id"]})
    assert not ({d["id"] for d in ours["decks"]} & {d["id"] for d in tat["decks"]} - {1})  # 1 = Anki's built-in Default deck


# ── build CLI ───────────────────────────────────────────────────────────────
@needs_data
def test_build_dry_run_writes_nothing(tmp_path):
    from app.grammar import build
    (tmp_path / "syllabus.json").write_text((GRAMMAR / "syllabus.json").read_text())
    assert build.main(["--dry-run", "--topic", "subj-deseos", "--out", str(tmp_path), "--count", "6"]) == 0
    assert [p.name for p in tmp_path.iterdir()] == ["syllabus.json"]


@needs_data
def test_authored_unit_passes_the_same_gates_as_api_output():
    """The hand-written reported-speech unit uses the API tool format and the normal gates."""
    raw = json.loads((GRAMMAR / "authored" / "estilo-indirecto-pasado.json").read_text(encoding="utf-8"))["items"]
    topic = syllabus.load(GRAMMAR / "syllabus.json").topic("estilo-indirecto-pasado").model_dump()
    good, bad = llm.to_exercise_dicts(raw, topic)
    rep = quality.run(good, Conjugator())
    assert not bad and not rep.rejected and len(rep.accepted) == len(raw)
    assert {e.type for e in rep.accepted} == {"cloze", "multiple_choice", "conjugation", "transformation", "error_correction"}
    assert all(e.source == "llm" and e.confidence != "high" for e in rep.accepted)   # never auto-trusted
    assert sum(1 for e in rep.accepted if e.verify) >= 12                              # conjugations were machine-checked
