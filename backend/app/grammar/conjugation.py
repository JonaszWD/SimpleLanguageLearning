"""Spanish conjugation data from Wiktionary (kaikki.org, CC BY-SA 4.0), used to verify answers.

Simple tenses are stored per form. Compound tenses (he hablado, hubiera hablado) are not in the
data, so they are composed from the auxiliary "haber" plus the participle.

    uv run python -m app.grammar.conjugation build data/dict/kaikki-spanish.jsonl
"""

import json
import os
import re
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

CONJ_PATH = Path(os.environ.get(
    "CONJ_PATH", Path(__file__).resolve().parents[2] / "data" / "grammar" / "conj.sqlite"))

TENSES = {"present", "preterite", "imperfect", "future", "conditional"}
PERSON = {"first-person": 1, "second-person": 2, "third-person": 3}
NUMBER = {"singular": "s", "plural": "p"}
SKIP_TAGS = {"combined-form", "table-tags", "inflection-template", "obsolete", "dialectal", "alternative",
             "accusative", "dative"}
WORD = re.compile(r"[^\W\d_]+")


IRREGULAR_PARTICIPLES = {
    "abrir": "abierto", "cubrir": "cubierto", "decir": "dicho", "escribir": "escrito", "hacer": "hecho",
    "morir": "muerto", "poner": "puesto", "romper": "roto", "ver": "visto", "volver": "vuelto",
    "satisfacer": "satisfecho", "resolver": "resuelto",
}


@dataclass(frozen=True)
class Analysis:
    lemma: str
    mood: str              # indicative | subjunctive | imperative | infinitive | gerund | participle
    tense: str | None
    person: int | None
    number: str | None     # "s" | "p"
    flags: str = ""        # space separated: se vos neg formal


def _normalise(form: str, lemma: str, tags: list[str]) -> Analysis | None:
    t = set(tags)
    if t & SKIP_TAGS or " " in form or not WORD.fullmatch(form):
        return None
    person = next((v for k, v in PERSON.items() if k in t), None)
    number = next((v for k, v in NUMBER.items() if k in t), None)
    flags = " ".join(f for f, tag in [("se", "imperfect-se"), ("vos", "vos-form"), ("neg", "negative"),
                                      ("formal", "formal"), ("nosotros", "nosotros")] if tag in t)
    if "infinitive" in t:
        return Analysis(lemma, "infinitive", None, None, None)
    if "gerund" in t:
        return Analysis(lemma, "gerund", None, None, None)
    if "participle" in t:
        # masculine singular only: it is the base form we compose with
        if t >= {"masculine", "singular"} or not t & {"masculine", "feminine", "plural"}:
            return Analysis(lemma, "participle", None, None, None)
        return None
    if "imperative" in t:
        return Analysis(lemma, "imperative", None, person, number, flags)
    tense = next((x for x in TENSES if x in t), None)
    if tense is None:
        return None
    mood = "subjunctive" if "subjunctive" in t else "indicative"
    if person is None or number is None:
        return None
    return Analysis(lemma, mood, tense, person, number, flags)


def build(src: Path, out: Path = CONJ_PATH, tokens: set[str] | None = None, keep: set[str] = frozenset()) -> None:
    """Build the table. With `tokens`, only verbs having a form in that set (or in `keep`) are kept."""
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    con.execute("CREATE TABLE conj (lemma TEXT, form TEXT, mood TEXT, tense TEXT, person INT, number TEXT, flags TEXT)")
    kept = 0
    with src.open(encoding="utf-8") as fh:
        for line in fh:
            if '"pos": "verb"' not in line:
                continue
            e = json.loads(line)
            if e.get("pos") != "verb" or " " in e["word"]:
                continue
            lemma = e["word"]
            rows = set()
            for f in e.get("forms", []):
                form = f["form"].lower()
                a = _normalise(form, lemma, f.get("tags", []))
                if a:
                    rows.add((a, form))
            if not rows:
                continue
            forms = {form for _, form in rows} | {lemma}
            if tokens is not None and lemma not in keep and not (forms & tokens):
                continue
            for a, form in rows:
                con.execute("INSERT INTO conj VALUES (?,?,?,?,?,?,?)",
                            (lemma, form, a.mood, a.tense, a.person, a.number, a.flags))
            kept += 1
    con.execute("CREATE INDEX c_form ON conj(form)")
    con.execute("CREATE INDEX c_lemma ON conj(lemma)")
    con.commit()
    con.execute("VACUUM")
    con.close()
    tmp.replace(out)
    print(f"built {out}: {kept} verbs, {out.stat().st_size / 1e6:.0f} MB")


def _gender(participle: str) -> list[str]:
    """Participle agreement forms (ado/ido/to/cho/so → a/os/as)."""
    stem = participle[:-1]
    return [participle, stem + "a", stem + "os", stem + "as"]


class Conjugator:
    def __init__(self, path: Path = CONJ_PATH):
        if not path.exists():
            raise FileNotFoundError(f"{path} missing: build it with `python -m app.grammar.conjugation build <kaikki.jsonl>`")
        self.con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)

    def knows(self, lemma: str) -> bool:
        return self.con.execute("SELECT 1 FROM conj WHERE lemma = ? LIMIT 1", (lemma,)).fetchone() is not None

    def analyze(self, token: str) -> list[Analysis]:
        rows = self.con.execute(
            "SELECT lemma, mood, tense, person, number, flags FROM conj WHERE form = ?", (token.lower(),))
        return [Analysis(*r) for r in rows]

    def lemmas(self) -> list[str]:
        return [r[0] for r in self.con.execute("SELECT DISTINCT lemma FROM conj")]

    def forms(self, lemma: str, mood: str, tense: str | None = None, person: int | None = None,
              number: str | None = None, flags: str | None = None) -> set[str]:
        q, args = "SELECT form FROM conj WHERE lemma = ? AND mood = ?", [lemma, mood]
        for col, val in (("tense", tense), ("person", person), ("number", number)):
            if val is not None:
                q += f" AND {col} = ?"
                args.append(val)
        if flags is not None:
            q += " AND flags = ?"
            args.append(flags)
        return {r[0] for r in self.con.execute(q, args)}

    def participles(self, lemma: str) -> set[str]:
        return self.forms(lemma, "participle")

    def participle(self, lemma: str) -> str | None:
        """The standard participle. The data also lists archaic variants (escripto), so prefer known
        irregulars, then the regular -ado/-ido, then the shortest."""
        got = self.participles(lemma)
        if not got:
            return None
        base = lemma[:-2] if lemma.endswith(("ar", "er", "ir")) else lemma  # also handles compounds: deshacer
        for stem, part in IRREGULAR_PARTICIPLES.items():
            if lemma.endswith(stem) and lemma[: -len(stem)] + part in got:
                return lemma[: -len(stem)] + part
        regular = base + ("ado" if lemma.endswith("ar") else "ido")
        return regular if regular in got else min(got, key=len)

    def compound(self, lemma: str, aux_mood: str, aux_tense: str, person: int, number: str,
                 flags: str | None = "", any_participle: bool = False) -> set[str]:
        """Compose e.g. he hablado (present indicative of haber + participle)."""
        parts = self.participles(lemma) if any_participle else {self.participle(lemma)} - {None}
        return {f"{aux} {p}" for p in parts for aux in self.forms("haber", aux_mood, aux_tense, person, number, flags)}

    def participle_forms(self, lemma: str) -> set[str]:
        """Participles with gender/number agreement (for passives)."""
        return {g for p in self.participles(lemma) for g in _gender(p)}


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "build":
        build(Path(sys.argv[2]))
    else:
        sys.exit(__doc__)
