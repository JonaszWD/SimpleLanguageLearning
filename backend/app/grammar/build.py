"""Build grammar exercises per topic.

    uv run python -m app.grammar.build                       # every topic, deterministic sources
    uv run python -m app.grammar.build --topic por-para --count 30
    uv run python -m app.grammar.build --llm --dry-run       # preview the Claude prompts, no calls, no writes
    ANTHROPIC_API_KEY=... uv run python -m app.grammar.build --llm --topic subj-duda
"""

import argparse
import hashlib
import json
import random
from pathlib import Path

from ..dictionary import DICT_PATH, Dictionary
from . import corpus, llm, syllabus
from .conjugation import CONJ_PATH, Conjugator, build as build_conj
from .generators import Ctx, build_registry
from .models import Exercise
from .quality import Report, run

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_APKG = ROOT / "9000_Spanish_sentences_-_difficulty_sorted_with_native_audio.apkg"
LLM_TYPES = ["cloze", "multiple_choice", "conjugation", "transformation", "error_correction"]


def summarize(topic_id: str, rep: Report, source: str = "") -> dict:
    by_type: dict[str, int] = {}
    for ex in rep.accepted:
        by_type[ex.type] = by_type.get(ex.type, 0) + 1
    return {"accepted": len(rep.accepted), "by_type": by_type, "review": len(rep.review), "rejected": len(rep.rejected)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--topic", action="append", help="topic id (repeatable); default: all")
    ap.add_argument("--count", type=int, default=24, help="deterministic exercises per topic")
    ap.add_argument("--llm", action="store_true", help="also generate exercises with the Claude API")
    ap.add_argument("--llm-count", type=int, default=8, help="LLM exercises per topic")
    ap.add_argument("--items", type=Path, help="pre-written items ({'items': [...]} in the API tool format) for ONE --topic; "
                    "goes through the same gates as API output, no API call")
    ap.add_argument("--model", default=llm.DEFAULT_MODEL)
    ap.add_argument("--dry-run", action="store_true", help="build and report, write nothing; with --llm print prompts only")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", type=Path, default=syllabus.GRAMMAR_DIR)
    ap.add_argument("--apkg", type=Path, default=DEFAULT_APKG, help="Tatoeba deck used as the sentence source")
    ap.add_argument("--kaikki", type=Path, help="kaikki Spanish jsonl, only needed to (re)build the conjugation table")
    a = ap.parse_args(argv)

    syl = syllabus.load(a.out / "syllabus.json")
    sentences = corpus.load(a.apkg, CONJ_PATH.parent / "tatoeba.json")
    if not CONJ_PATH.exists():
        if not a.kaikki:
            raise SystemExit("conjugation table missing: pass --kaikki <kaikki-spanish.jsonl>")
        build_conj(a.kaikki, tokens={t.lower() for s in sentences for t in s.tokens},
                   keep={"ser", "estar", "haber", "ir", "tener", "hacer", "poder", "decir"})
    conj = Conjugator()
    dic = Dictionary(DICT_PATH) if DICT_PATH.exists() else None
    homographs: dict[str, bool] = {}

    def homograph(tok: str) -> bool:  # also a noun/adjective/adverb? then it is a poor verb blank
        if dic is None:
            return False
        if tok not in homographs:
            homographs[tok] = dic.con.execute("SELECT 1 FROM entries WHERE word = ? AND pos != 'verb' LIMIT 1", (tok,)).fetchone() is not None
        return homographs[tok]

    if a.items and (not a.topic or len(a.topic) != 1):
        raise SystemExit("--items needs exactly one --topic")
    registry = build_registry(lambda: conj)
    topics = [t for t in syl.track().topics if not a.topic or t.id in a.topic]
    if a.topic and (unknown := set(a.topic) - {t.id for t in topics}):
        raise SystemExit(f"unknown topic(s): {sorted(unknown)}")

    review: dict[str, dict] = {}
    index_topics: dict[str, dict] = {}
    seen: set[str] = set()   # shared across topics: the same item must not appear under two topics
    for t in topics:
        td = t.model_dump()
        if t.type == "review":
            index_topics[t.id] = {"count": 0, "file": None, "reviews": t.reviews}
            continue
        rep = Report()
        gen = registry.get(t.id)
        needs_llm = gen is None
        if gen:
            ctx = Ctx(sentences, conj, td, random.Random(f"{a.seed}:{t.id}"), homograph)
            rep.merge(run(gen(ctx, a.count), conj, seen))
        llm_status = ""
        if a.llm:
            raw, llm_status = llm.generate(td, LLM_TYPES, a.llm_count, model=a.model, dry_run=a.dry_run)
            if raw is not None:
                good, bad = llm.to_exercise_dicts(raw, td)
                rep.rejected += bad
                rep.merge(run(good, conj, seen))
        if a.items:
            good, bad = llm.to_exercise_dicts(json.loads(a.items.read_text(encoding="utf-8"))["items"], td)
            rep.rejected += bad
            rep.merge(run(good, conj, seen))
            llm_status = f"from {a.items.name}"
        info = summarize(t.id, rep)
        info.update(needs_llm=needs_llm and not any(e.source == "llm" for e in rep.accepted), llm=llm_status)
        print(f"{t.week:>2} {t.id:<32} {info['accepted']:>3} ok  {info['review']:>3} to review  {info['rejected']:>3} rejected"
              + ("   (no deterministic generator: needs --llm)" if info["needs_llm"] else ""))
        review[t.id] = {**info, "rejected_items": [{"item": i, "reasons": r} for i, r in rep.rejected],
                        "review_items": [{"id": e.id, "type": e.type, "text": e.text or e.hint, "answer": e.answer, "reasons": r} for e, r in rep.review]}
        digest = hashlib.sha1(json.dumps([e.model_dump() for e in rep.accepted], sort_keys=True).encode()).hexdigest()[:10]
        index_topics[t.id] = {"count": len(rep.accepted), "file": f"exercises/{t.id}.json", "version": digest}
        if not a.dry_run:
            (a.out / "exercises").mkdir(parents=True, exist_ok=True)
            (a.out / "exercises" / f"{t.id}.json").write_text(json.dumps(
                {"topic": t.id, "level": t.level, "exercises": [e.model_dump(exclude_defaults=False) for e in rep.accepted]},
                ensure_ascii=False, indent=1))

    if not a.dry_run:
        rv_path = a.out / "review.json"
        old_review = json.loads(rv_path.read_text()) if rv_path.exists() else {}
        rv_path.write_text(json.dumps({**old_review, **review}, ensure_ascii=False, indent=1, default=lambda o: o.model_dump()))
        # Merge with any existing index so a partial run (--topic) doesn't drop other topics.
        idx_path = a.out / "index.json"
        old = json.loads(idx_path.read_text())["topics"] if idx_path.exists() else {}
        merged = {**old, **index_topics}
        version = hashlib.sha1(json.dumps(merged, sort_keys=True).encode()).hexdigest()[:10]
        idx_path.write_text(json.dumps({"version": version, "topics": merged}, ensure_ascii=False, indent=1))
        print(f"\nwrote {a.out}/exercises, review.json, index.json (version {version})")
    else:
        print("\ndry run: nothing written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
