"""Offline Spanish -> English dictionary built from Wiktionary (kaikki.org extract, CC BY-SA).

Maps inflected forms back to their lemma, so "hablamos" finds "hablar".

    uv run python -m app.dictionary build data/dict/kaikki-spanish.jsonl
"""

import json
import os
import re
import sqlite3
import sys
from pathlib import Path

DICT_PATH = Path(os.environ.get(
    "DICT_PATH", Path(__file__).resolve().parents[1] / "data" / "dict" / "es-en.sqlite"))

DEMOTE_TAGS = {"obsolete", "archaic", "rare", "dated", "historical"}
SKIP_FORM_TAGS = {"table-tags", "inflection-template", "class", "romanization"}
WEAK_POS = {"character", "symbol", "prefix", "suffix", "phrase", "proverb", "contraction"}
WORD = re.compile(r"[^\W\d_]+")
MAX_GLOSS = 90


def _clean(g: str) -> str:
    g = re.sub(r"\s+", " ", g).strip()
    return g if len(g) <= MAX_GLOSS else g[: MAX_GLOSS - 1].rstrip() + "…"


def build(src: Path, out: Path = DICT_PATH) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    con.executescript("""
        CREATE TABLE entries (word TEXT, pos TEXT, glosses TEXT);
        CREATE TABLE forms (form TEXT, lemma TEXT, pos TEXT, note TEXT, UNIQUE(form, lemma, pos));
    """)
    n = 0
    with src.open(encoding="utf-8") as fh:
        for line in fh:
            e = json.loads(line)
            word, pos, senses = e.get("word", ""), e.get("pos", ""), e.get("senses", [])
            if not word or " " in word:
                continue
            glosses, flagged = [], []
            for s in senses:
                refs = s.get("form_of", []) + s.get("alt_of", [])
                if refs:
                    tags = " ".join(t for t in s.get("tags", []) if t not in ("form-of", "alt-of"))
                    for ref in refs:
                        con.execute("INSERT OR IGNORE INTO forms VALUES (?,?,?,?)",
                                    (word.lower(), ref["word"], pos, tags))
                    continue
                if not s.get("glosses"):
                    continue
                g = _clean(s["glosses"][-1])
                bucket = flagged if DEMOTE_TAGS & set(s.get("tags", [])) else glosses
                if g and g not in glosses and g not in flagged:
                    bucket.append(g)
            glosses = (glosses + flagged)[:3]  # archaic/rare senses only fill leftover slots
            if not glosses:
                continue
            con.execute("INSERT INTO entries VALUES (?,?,?)", (word, pos, json.dumps(glosses, ensure_ascii=False)))
            for f in e.get("forms", []):
                form = f.get("form", "")
                if (not form or form == word or " " in form or SKIP_FORM_TAGS & set(f.get("tags", []))
                        or not WORD.fullmatch(form)):
                    continue
                con.execute("INSERT OR IGNORE INTO forms VALUES (?,?,?,?)",
                            (form.lower(), word, pos, " ".join(f.get("tags", []))))
            n += 1
    con.executescript("CREATE INDEX e_word ON entries(word); CREATE INDEX f_form ON forms(form);")
    con.commit()
    con.execute("VACUUM")
    con.close()
    tmp.replace(out)
    print(f"built {out} ({n} lemmas, {out.stat().st_size / 1e6:.0f} MB)")


_ORDER = ["first-person", "second-person", "third-person", "singular", "plural", "masculine", "feminine",
          "present", "preterite", "imperfect", "future", "conditional", "past", "participle", "gerund",
          "indicative", "subjunctive", "imperative", "diminutive", "augmentative"]
_SHORT = {"first-person": "1st person", "second-person": "2nd person", "third-person": "3rd person"}


def describe(tags: str | None) -> str | None:
    """Grammar tags in a readable order: '1st person plural present indicative'."""
    have = set((tags or "").split())
    out = [_SHORT.get(t, t) for t in _ORDER if t in have]
    return " ".join(out) or None


class Dictionary:
    def __init__(self, path: Path = DICT_PATH):
        self.con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False) if path.exists() else None

    @property
    def available(self) -> bool:
        return self.con is not None

    def _entries(self, word: str) -> list[tuple[str, list[str]]]:
        return [(pos, json.loads(g)) for pos, g in
                self.con.execute("SELECT pos, glosses FROM entries WHERE word = ? LIMIT 3", (word,))]

    def lookup(self, token: str) -> list[dict]:
        """Up to 3 readings: the word itself, then lemmas it is an inflection of."""
        out: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for cand in dict.fromkeys([token.lower(), token]):
            for pos, glosses in self._entries(cand):
                if (cand, pos) not in seen:
                    seen.add((cand, pos))
                    out.append({"lemma": cand, "pos": pos, "gloss": glosses, "form": None})
        rows = self.con.execute(
            "SELECT lemma, pos, note FROM forms WHERE form = ? LIMIT 12", (token.lower(),)).fetchall()
        rows.sort(key=lambda r: r[1] == "verb")  # nouns/adjectives first: "muertos" -> muerto before morir
        have = {o["lemma"].lower() for o in out}
        for lemma, pos, note in rows:
            if lemma.lower() in have:
                continue
            for lpos, glosses in self._entries(lemma)[:1]:
                have.add(lemma.lower())
                out.append({"lemma": lemma, "pos": lpos, "gloss": glosses, "form": describe(note)})
        out.sort(key=lambda o: o["pos"] in WEAK_POS)  # stable: letters/symbols after real words
        return out[:3]

    def glossary(self, text: str) -> dict[str, list[dict]]:
        if not self.available:
            return {}
        first: dict[str, str] = {}
        for w in WORD.findall(text):
            first.setdefault(w.lower(), w)
        gl = {}
        for low, orig in first.items():
            hits = self.lookup(orig)
            if hits:
                gl[low] = hits
        return gl


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "build":
        build(Path(sys.argv[2]))
    else:
        sys.exit(__doc__)
