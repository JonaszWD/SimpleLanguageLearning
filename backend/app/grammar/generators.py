"""Deterministic exercise generators: real Tatoeba sentences + Wiktionary conjugation data.

Nothing here calls an LLM. Every conjugated answer is derived from, and later re-verified against,
the conjugation table. Topics whose grammar can't be detected reliably (reported speech, ...) have no
deterministic generator and are left to the LLM step.
"""

import math
import random
import re
from collections import Counter
from dataclasses import dataclass
from typing import Callable, Iterator

from .conjugation import Analysis, Conjugator
from .corpus import ATTRIBUTION, WORD, Sentence
from .models import BLANK, Exercise, Verify
from .quality import BLOCKLIST

FINITE = ("indicative", "subjunctive", "imperative")
PERSON_ES = {(1, "s"): "yo", (2, "s"): "tú", (3, "s"): "él / ella / usted", (1, "p"): "nosotros",
             (2, "p"): "vosotros", (3, "p"): "ellos / ellas / ustedes"}
TENSE_ES = {("indicative", "present"): "presente", ("indicative", "preterite"): "pretérito indefinido",
            ("indicative", "imperfect"): "pretérito imperfecto", ("indicative", "future"): "futuro",
            ("indicative", "conditional"): "condicional", ("subjunctive", "present"): "presente de subjuntivo",
            ("subjunctive", "imperfect"): "imperfecto de subjuntivo", ("imperative", None): "imperativo"}
TIME_WORDS = {"hoy", "ahora", "mañana", "ayer", "anoche", "ya", "todavía", "aún", "antes", "después"}


@dataclass
class Ctx:
    sentences: list[Sentence]
    conj: Conjugator
    topic: dict
    rng: random.Random
    homograph: Callable[[str], bool]

    def spans(self, s: Sentence) -> list[tuple[int, int, str]]:
        return [(m.start(), m.end(), m.group()) for m in WORD.finditer(s.es)]


# ── sentences ────────────────────────────────────────────────────────────────
def usable(s: Sentence) -> bool:
    t = s.es
    return (3 <= s.words <= 14 and t[:1].isupper() or t[:1] in "¿¡") and re.search(r"[.!?]$", t) is not None \
        and not re.search(r"\d", t) and not BLOCKLIST.search(t) and "  " not in t


def blank(s: Sentence, a: int, b: int) -> str:
    return s.es[:a] + BLANK + s.es[b:]


def swap(s: Sentence, a: int, b: int, new: str) -> str:
    return s.es[:a] + new + s.es[b:]


def match_case(model: str, word: str) -> str:
    return word.capitalize() if model[:1].isupper() else word


# ── exercise builders ────────────────────────────────────────────────────────
def _base(ctx: Ctx, **kw) -> dict:
    return dict(topic=ctx.topic["id"], level=ctx.topic["level"], tags=[ctx.topic["id"], ctx.topic["level"], "grammar"], **kw)


def from_sentence(ctx: Ctx, s: Sentence, **kw) -> dict:
    return _base(ctx, source="tatoeba", source_ids={"tatoeba_es": s.es_id, "tatoeba_en": s.en_id},
                 attribution=ATTRIBUTION, translation=s.en, **kw)


def cloze(ctx, s, a, b, answer, prompt, hint="", explanation="", verify=None, alternatives=(), conf="high", notes=()):
    return from_sentence(ctx, s, type="cloze", prompt=prompt, text=blank(s, a, b), answer=answer, hint=hint,
                         explanation=explanation, verify=verify, alternatives=list(alternatives),
                         confidence=conf, notes=list(notes))


def multiple_choice(ctx, s, a, b, answer, distractors, prompt, explanation="", verify=None, conf="high", notes=()):
    opts = [answer, *distractors]
    ctx.rng.shuffle(opts)
    return from_sentence(ctx, s, type="multiple_choice", prompt=prompt, text=blank(s, a, b), answer=answer,
                         options=opts, explanation=explanation, verify=verify, confidence=conf, notes=list(notes))


def error_correction(ctx, s, a, b, wrong, explanation="", conf="high", notes=(), prompt="Corrige el error de la frase.", alt_forms=()):
    """alt_forms: other forms that also fix the sentence (e.g. the -se counterpart of a -ra verb)."""
    return from_sentence(ctx, s, type="error_correction", prompt=prompt, text=swap(s, a, b, wrong), answer=s.es,
                         alternatives=[swap(s, a, b, f) for f in alt_forms], explanation=explanation, confidence=conf, notes=list(notes))


def transformation(ctx, s, a, b, new, prompt, explanation="", conf="medium", notes=()):
    return from_sentence(ctx, s, type="transformation", prompt=prompt, text=s.es, answer=swap(s, a, b, new),
                         explanation=explanation, confidence=conf, notes=list(notes))


def conjugation(ctx, lemma, mood, tense, person, number, answers, explanation="", verify=None, extra_hint=""):
    label = TENSE_ES[(mood, tense)]
    who = PERSON_ES.get((person, number), "")
    return _base(ctx, type="conjugation", prompt=f"Conjuga el verbo: {label}" + (f" · {who}" if who else ""),
                 answer=sorted(answers, key=len)[0] if len(answers) == 1 else answers[0], alternatives=list(answers[1:]),
                 hint=f"{lemma}{extra_hint}", explanation=explanation, source="wiktionary",
                 source_ids={"wiktionary": lemma}, attribution="Wiktionary via kaikki.org, CC BY-SA 4.0", verify=verify)


# ── verb-form candidates ─────────────────────────────────────────────────────
@dataclass
class Cand:
    s: Sentence
    a: int
    b: int
    token: str
    lemma: str
    persons: frozenset
    idx: int


def verb_candidates(ctx: Ctx, mood: str, tense: str | None, *, lemma_ok=None, before: re.Pattern | None = None,
                    extra_ok: frozenset = frozenset(), need_start: bool = False, flags: str | None = None) -> Iterator[Cand]:
    """Sentences where one token is unambiguously a `mood`/`tense` form of a single verb."""
    for s in ctx.sentences:
        if not usable(s):
            continue
        sp = ctx.spans(s)
        for idx, (a, b, tok) in enumerate(sp):
            if need_start and idx != 0:
                break
            ans = ctx.conj.analyze(tok)
            fin = [x for x in ans if x.mood in FINITE]
            hit = [x for x in fin if x.mood == mood and (tense is None or x.tense == tense)
                   and (flags is None or x.flags == flags)]
            if not hit or any(x.mood not in (mood, *extra_ok) for x in fin):
                continue
            lemmas = {x.lemma for x in hit}
            if len(lemmas) != 1 or ctx.homograph(tok.lower()):
                continue
            lemma = next(iter(lemmas))
            if lemma == "haber":  # auxiliary: belongs to the compound-tense topics
                continue
            if lemma_ok and not lemma_ok(lemma, tok.lower()):
                continue
            if before and not before.search(s.es[:a].lower()):
                continue
            yield Cand(s, a, b, tok, lemma, frozenset((x.person, x.number) for x in hit), idx)


def other_forms(ctx: Ctx, c: Cand, avoid: set[str], moods_tenses=None, n=3) -> list[str]:
    """Same verb, same person/number, a different mood or tense: plausible wrong options."""
    (person, number) = sorted(c.persons)[0]
    pool = []
    for (mood, tense) in moods_tenses or [("indicative", t) for t in ("present", "preterite", "imperfect", "future", "conditional")] + [("subjunctive", "present"), ("subjunctive", "imperfect")]:
        for f in sorted(ctx.conj.forms(c.lemma, mood, tense, person, number, flags="")):
            if f not in avoid and f != c.token.lower():
                pool.append(f)
    pool = list(dict.fromkeys(pool))
    ctx.rng.shuffle(pool)
    return [match_case(c.token, f) for f in pool[:n]]


def valid_forms(ctx: Ctx, c: Cand, mood: str, tense: str | None) -> set[str]:
    out = set()
    for (p, n) in c.persons:
        out |= ctx.conj.forms(c.lemma, mood, tense, p, n)
    return out


def single_person(c: Cand) -> bool:
    return len(c.persons) == 1


# ── plan: how many of each type ──────────────────────────────────────────────
SHARE = {"cloze": 0.40, "multiple_choice": 0.25, "conjugation": 0.15, "error_correction": 0.10, "transformation": 0.10}


def quota(n: int) -> dict[str, int]:
    q = {k: max(1, round(n * v)) for k, v in SHARE.items()}
    q["cloze"] += n - sum(q.values())
    return q


def pick(items: list, k: int, ctx: Ctx, used: set | None = None, key=lambda x: x.s.es_id) -> list:
    """Shuffle, then take up to k with distinct sentences."""
    items = list(items)
    ctx.rng.shuffle(items)
    out, seen = [], used if used is not None else set()
    for it in items:
        if len(out) >= k:
            break
        if key(it) in seen:
            continue
        seen.add(key(it))
        out.append(it)
    return out


# ── topic builders ───────────────────────────────────────────────────────────
def verb_form_topic(mood: str, tense: str | None, explain: str, *, lemma_ok=None, before=None, extra_ok=frozenset(),
                    mc_conf="high", wrong_pool=None, transform_to: tuple | None = None, conj_lemma_ok=None,
                    need_start=False, conj_persons=None, flags: str | None = None, ec_conf="high"):
    """Cloze / multiple choice / conjugation / error correction (/ transformation) for one verb form."""
    label = TENSE_ES[(mood, tense)]

    def gen(ctx: Ctx, n: int) -> list[dict]:
        q = quota(n)
        cands = list(verb_candidates(ctx, mood, tense, lemma_ok=lemma_ok, before=before, extra_ok=extra_ok,
                                     need_start=need_start, flags=flags))
        used: set = set()
        out = []
        for c in pick(cands, q["cloze"], ctx, used):
            v = Verify(lemma=c.lemma, mood=mood, tense=tense, person=sorted(c.persons)[0][0] if single_person(c) else None,
                       number=sorted(c.persons)[0][1] if single_person(c) else None)
            alts = []
            if (mood, tense) == ("subjunctive", "imperfect"):  # -ra and -se forms are interchangeable
                alts = [match_case(c.token, f) for f in sorted(valid_forms(ctx, c, mood, tense) - {c.token.lower()})]
            out.append(cloze(ctx, c.s, c.a, c.b, c.token, f"Completa con el verbo en {label}.", hint=c.lemma,
                             explanation=explain, verify=v, alternatives=alts))
        for c in pick([c for c in cands if single_person(c)], q["multiple_choice"], ctx, used):
            avoid = valid_forms(ctx, c, mood, tense)
            d = other_forms(ctx, c, avoid, wrong_pool, 3)
            if len(d) >= 2:
                out.append(multiple_choice(ctx, c.s, c.a, c.b, c.token, d, "Elige la forma correcta.", explanation=explain,
                                           verify=Verify(lemma=c.lemma, mood=mood, tense=tense, person=sorted(c.persons)[0][0],
                                                         number=sorted(c.persons)[0][1]), conf=mc_conf))
        for c in pick([c for c in cands if single_person(c)], q["error_correction"], ctx, used):
            d = other_forms(ctx, c, valid_forms(ctx, c, mood, tense), wrong_pool, 1)
            if d:
                alt = [match_case(c.token, f) for f in sorted(valid_forms(ctx, c, mood, tense) - {c.token.lower()})]
                out.append(error_correction(ctx, c.s, c.a, c.b, d[0], explanation=explain, conf=ec_conf, alt_forms=alt))
        out += conjugation_exercises(ctx, mood, tense, q["conjugation"], conj_lemma_ok or lemma_ok, explain, conj_persons)
        if transform_to:
            out += tense_transformations(ctx, q["transformation"], *transform_to, explain)
        return out
    return gen


def common_lemmas(ctx: Ctx, mood: str, tense: str | None, lemma_ok=None, top=60) -> list[str]:
    """Most frequent verbs of the corpus that have this form."""
    freq = Counter()
    for s in ctx.sentences:
        for tok in WORD.findall(s.es):
            fin = [x for x in ctx.conj.analyze(tok.lower()) if x.mood in FINITE]
            if fin and len({x.lemma for x in fin}) == 1 and not ctx.homograph(tok.lower()):
                freq[fin[0].lemma] += 1
    return [l for l, _ in freq.most_common(500) if ctx.conj.forms(l, mood, tense) and (not lemma_ok or lemma_ok(l, None))][:top]


def conjugation_exercises(ctx, mood, tense, n, lemma_ok, explain, persons=None) -> list[dict]:
    persons = persons or [(1, "s"), (2, "s"), (3, "s"), (1, "p"), (2, "p"), (3, "p")]
    lemmas = common_lemmas(ctx, mood, tense, lemma_ok)
    ctx.rng.shuffle(lemmas)
    out = []
    for lemma in lemmas:
        if len(out) >= n:
            break
        p, num = ctx.rng.choice(persons)
        forms = sorted(ctx.conj.forms(lemma, mood, tense, p, num, flags=""))
        if not forms:
            continue
        out.append(conjugation(ctx, lemma, mood, tense, p, num, forms, explain,
                               Verify(lemma=lemma, mood=mood, tense=tense, person=p, number=num)))
    return out


def tense_transformations(ctx, n, from_tense, to_mood, to_tense, explain) -> list[dict]:
    """Change the only finite verb of a present-tense sentence to another tense."""
    out = []
    pool = []
    for s in ctx.sentences:
        if not usable(s) or s.words > 10 or TIME_WORDS & {t.lower() for t in WORD.findall(s.es)}:
            continue
        sp = ctx.spans(s)
        fin = [(a, b, t, [x for x in ctx.conj.analyze(t.lower()) if x.mood in FINITE]) for a, b, t in sp]
        fin = [f for f in fin if f[3]]
        if len(fin) != 1:
            continue
        a, b, tok, ans = fin[0]
        if any(x.mood != "indicative" or x.tense != from_tense for x in ans) or len({x.lemma for x in ans}) != 1 \
                or len({(x.person, x.number) for x in ans}) != 1 or ctx.homograph(tok.lower()):
            continue
        x = ans[0]
        new = sorted(ctx.conj.forms(x.lemma, to_mood, to_tense, x.person, x.number, flags=""))
        if new:
            pool.append((s, a, b, match_case(tok, new[0])))
    ctx.rng.shuffle(pool)
    label = TENSE_ES[(to_mood, to_tense)]
    for s, a, b, new in pool[:n]:
        out.append(transformation(ctx, s, a, b, new, f"Cambia el verbo al {label}.", explain,
                                  notes=["time reference may feel odd after the change"]))
    return out


def compound_topic(aux_mood: str, aux_tense: str, explain: str, *, trigger: re.Pattern | None = None, mc_conf="medium"):
    """haber + participle: he hablado, había comido, haya llegado, hubiera sabido."""
    label = {"present": "pretérito perfecto", "imperfect": "pluscuamperfecto"}.get(aux_tense, aux_tense)
    if aux_mood == "subjunctive":
        label = f"{label} de subjuntivo" if aux_tense == "imperfect" else "pretérito perfecto de subjuntivo"

    def gen(ctx: Ctx, n: int) -> list[dict]:
        q = quota(n)
        found = []
        for s in ctx.sentences:
            if not usable(s):
                continue
            sp = ctx.spans(s)
            for i in range(len(sp) - 1):
                (a1, b1, t1), (a2, b2, t2) = sp[i], sp[i + 1]
                aux = [x for x in ctx.conj.analyze(t1.lower()) if x.lemma == "haber" and x.mood == aux_mood and x.tense == aux_tense]
                if not aux:
                    continue
                parts = [x for x in ctx.conj.analyze(t2.lower()) if x.mood == "participle"]
                if len(parts) != 1 or ctx.homograph(t2.lower()):
                    continue
                if trigger and not trigger.search(s.es[:a1].lower()):
                    continue
                found.append((s, a1, b2, f"{t1} {t2}", parts[0].lemma, aux[0]))
        cands = pick(found, q["cloze"] + q["multiple_choice"] + q["error_correction"], ctx, set(), key=lambda x: x[0].es_id)
        out = []
        for k, (s, a, b, answer, lemma, aux) in enumerate(cands):
            v = Verify(lemma=lemma, mood=aux_mood, tense=None, person=aux.person, number=aux.number, compound=True, aux_tense=aux_tense)
            if k < q["cloze"]:
                out.append(cloze(ctx, s, a, b, answer, f"Completa con el {label} del verbo.", hint=lemma, explanation=explain, verify=v))
            elif k < q["cloze"] + q["multiple_choice"]:
                wrong = [match_case(answer, w) for w in compound_distractors(ctx, lemma, aux_mood, aux_tense, aux.person, aux.number, answer)]
                if len(wrong) >= 2:
                    out.append(multiple_choice(ctx, s, a, b, answer, wrong, "Elige la forma correcta.", explanation=explain, verify=v, conf=mc_conf))
            else:
                wrong = compound_distractors(ctx, lemma, aux_mood, aux_tense, aux.person, aux.number, answer)[:1]
                if wrong:
                    out.append(error_correction(ctx, s, a, b, match_case(answer, wrong[0]), explanation=explain, conf=mc_conf))
        # conjugation: compose haber + participle
        lemmas = [l for l in common_lemmas(ctx, "indicative", "present") if ctx.conj.participle(l)]
        ctx.rng.shuffle(lemmas)
        for lemma in lemmas[: q["conjugation"]]:
            p, num = ctx.rng.choice([(1, "s"), (2, "s"), (3, "s"), (1, "p"), (3, "p")])
            ans = sorted(ctx.conj.compound(lemma, aux_mood, aux_tense, p, num, flags=""))
            if ans:
                out.append(_base(ctx, type="conjugation", prompt=f"Conjuga el verbo: {label} · {PERSON_ES[(p, num)]}", answer=ans[0],
                                 hint=lemma, explanation=explain, source="wiktionary", source_ids={"wiktionary": lemma},
                                 attribution="Wiktionary via kaikki.org, CC BY-SA 4.0",
                                 verify=Verify(lemma=lemma, mood=aux_mood, person=p, number=num, compound=True, aux_tense=aux_tense)))
        return out
    return gen


def compound_distractors(ctx, lemma, mood, tense, person, number, answer) -> list[str]:
    part = ctx.conj.participle(lemma) or ""
    pool = [f"{a} {part}" for t in ("present", "imperfect", "future", "conditional") if mood == "indicative"
            for a in sorted(ctx.conj.forms("haber", mood, t, person, number, flags=""))]
    pool += sorted(ctx.conj.forms(lemma, "indicative", "preterite", person, number, flags=""))
    pool += sorted(ctx.conj.forms(lemma, "indicative", "imperfect", person, number, flags=""))
    pool = [p for p in dict.fromkeys(pool) if p.lower() != answer.lower()]
    ctx.rng.shuffle(pool)
    return pool[:3]


def word_contrast_topic(groups: list[list[str]], prompt: str, explain: str, *, conf="medium", note: str, phrase_ok=None):
    """Cloze + multiple choice + error correction over a closed set of words (por/para, connectors, ...)."""
    flat = {w: g for g in groups for w in g}
    pattern = re.compile(r"(?<![\w])(" + "|".join(sorted((re.escape(w) for w in flat), key=len, reverse=True)) + r")(?![\w])", re.I)

    def gen(ctx: Ctx, n: int) -> list[dict]:
        q = quota(n)
        found = []
        for s in ctx.sentences:
            if not usable(s):
                continue
            ms = list(pattern.finditer(s.es))
            if len(ms) != 1:      # exactly one occurrence keeps the blank unambiguous
                continue
            m = ms[0]
            if phrase_ok and not phrase_ok(s.es, m):
                continue
            found.append((s, m.start(), m.end(), m.group(1)))
        out, used = [], set()
        key = lambda x: x[0].es_id
        for s, a, b, w in pick(found, q["cloze"], ctx, used, key):
            out.append(cloze(ctx, s, a, b, w, prompt, explanation=explain, conf=conf, notes=[note]))
        for s, a, b, w in pick(found, q["multiple_choice"], ctx, used, key):
            others = [x for x in flat[w.lower()] if x != w.lower()]
            pool = others + [x for g in groups for x in g if x not in flat[w.lower()]]
            d = [match_case(w, x) for x in list(dict.fromkeys(pool))[:3]]
            if d:
                out.append(multiple_choice(ctx, s, a, b, w, d[:3], "Elige la palabra correcta.", explanation=explain, conf=conf, notes=[note]))
        for s, a, b, w in pick(found, q["error_correction"] + q["transformation"], ctx, used, key):
            others = [x for x in flat[w.lower()] if x != w.lower()]
            if others:
                out.append(error_correction(ctx, s, a, b, match_case(w, others[0]), explanation=explain, conf=conf, notes=[note]))
        return out
    return gen


def trigger_topic(trigger: re.Pattern, mood: str, tense: str, explain: str, prompt: str, *, wrong_pool, lemma_ok=None,
                  extra_ok=frozenset(), conf="high", mc_conf="high"):
    """A subjunctive (or other) verb that follows a trigger phrase such as 'quiero que' or 'no creo que'."""
    label = TENSE_ES[(mood, tense)]

    def gen(ctx: Ctx, n: int) -> list[dict]:
        q = quota(n)
        cands = list(verb_candidates(ctx, mood, tense, lemma_ok=lemma_ok, before=trigger, extra_ok=extra_ok))
        used: set = set()
        out = []
        for c in pick(cands, q["cloze"], ctx, used):
            out.append(cloze(ctx, c.s, c.a, c.b, c.token, prompt, hint=c.lemma, explanation=explain, conf=conf,
                             verify=Verify(lemma=c.lemma, mood=mood, tense=tense,
                                           person=sorted(c.persons)[0][0] if single_person(c) else None,
                                           number=sorted(c.persons)[0][1] if single_person(c) else None)))
        for c in pick([c for c in cands if single_person(c)], q["multiple_choice"], ctx, used):
            d = other_forms(ctx, c, valid_forms(ctx, c, mood, tense), wrong_pool, 3)
            if len(d) >= 2:
                out.append(multiple_choice(ctx, c.s, c.a, c.b, c.token, d, "Elige la forma correcta.", explanation=explain, conf=mc_conf,
                                           verify=Verify(lemma=c.lemma, mood=mood, tense=tense, person=sorted(c.persons)[0][0], number=sorted(c.persons)[0][1])))
        for c in pick([c for c in cands if single_person(c)], q["error_correction"] + q["transformation"], ctx, used):
            d = other_forms(ctx, c, valid_forms(ctx, c, mood, tense), wrong_pool, 1)
            if d:
                alt = [match_case(c.token, f) for f in sorted(valid_forms(ctx, c, mood, tense) - {c.token.lower()})]
                out.append(error_correction(ctx, c.s, c.a, c.b, d[0], explanation=explain, conf=conf, alt_forms=alt))
        out += conjugation_exercises(ctx, mood, tense, q["conjugation"], lemma_ok, explain)
        return out
    return gen


# ── subjunctive helpers ──────────────────────────────────────────────────────
def regular_subj_present(lemma: str, person: int, number: str) -> str | None:
    """Naive regular formation (with spelling changes, without stem changes)."""
    if not lemma.endswith(("ar", "er", "ir")):
        return None
    stem, end = lemma[:-2], lemma[-2:]
    ar = end == "ar"
    vowels = ["e", "es", "e", "emos", "éis", "en"] if ar else ["a", "as", "a", "amos", "áis", "an"]
    ending = vowels[(person - 1) + (3 if number == "p" else 0)]
    if ar:
        for old, new in (("c", "qu"), ("g", "gu"), ("z", "c")):
            if stem.endswith(old):
                stem = stem[: -len(old)] + new
                break
    else:
        for old, new in (("g", "j"), ("c", "z"), ("gu", "g")):
            if stem.endswith(old):
                stem = stem[: -len(old)] + new
                break
    return stem + ending


def make_regular_filter(conj_getter):
    def ok(lemma, tok):
        if tok is None:
            return True
        c = conj_getter()
        for x in c.analyze(tok):
            if x.lemma == lemma and x.mood == "subjunctive" and x.tense == "present":
                return regular_subj_present(lemma, x.person, x.number) == tok
        return False
    return ok


def make_irregular_filter(conj_getter):
    reg = make_regular_filter(conj_getter)
    return lambda lemma, tok: tok is None or not reg(lemma, tok)


def before(*stems: str, de: bool = False) -> re.Pattern:
    """Text before the verb must end with '<trigger> (de) que <up to 2 words>'."""
    alt = "|".join(stems)
    return re.compile(rf"(?:{alt})\s+" + (r"(?:de\s+)?" if de else "") + r"que\s+(?:\w+\s+){0,2}$")


SUBJ_PRESENT_WRONG = [("indicative", "present"), ("indicative", "future"), ("indicative", "preterite")]
SUBJ_IMPERF_WRONG = [("indicative", "imperfect"), ("indicative", "preterite"), ("subjunctive", "present"), ("indicative", "conditional")]


def ser_estar_topic(explain: str):
    """Blank a form of ser/estar. Distractors: the other verb in the same tense and person."""
    pair = {"ser": "estar", "estar": "ser"}

    def gen(ctx: Ctx, n: int) -> list[dict]:
        q = quota(n)
        cands = []
        for tense in ("present", "imperfect", "preterite"):
            cands += [c for c in verb_candidates(ctx, "indicative", tense, lemma_ok=lambda l, t: l in pair)
                      if single_person(c)]
        out, used = [], set()
        for c in pick(cands, q["cloze"], ctx, used):
            out.append(cloze(ctx, c.s, c.a, c.b, c.token, "Completa con la forma correcta de ser o estar.", explanation=explain,
                             conf="medium", notes=["ser/estar can both fit some sentences with a change of meaning; check the blank is unambiguous"]))
        def paired(c):
            (p, num) = sorted(c.persons)[0]
            tense = next(x.tense for x in ctx.conj.analyze(c.token.lower()) if x.lemma == c.lemma)
            other = sorted(ctx.conj.forms(pair[c.lemma], "indicative", tense, p, num, flags=""))
            return other, tense, p, num
        for c in pick(cands, q["multiple_choice"], ctx, used):
            other, tense, p, num = paired(c)
            if not other:
                continue
            same = [f for t in ("present", "imperfect", "preterite") if t != tense
                    for f in sorted(ctx.conj.forms(c.lemma, "indicative", t, p, num, flags=""))]
            d = [match_case(c.token, other[0])] + [match_case(c.token, f) for f in same[:1]]
            out.append(multiple_choice(ctx, c.s, c.a, c.b, c.token, d, "Elige la forma correcta.", explanation=explain, conf="medium",
                                       verify=Verify(lemma=c.lemma, mood="indicative", tense=tense, person=p, number=num),
                                       notes=["the other verb may also fit with a change of meaning"]))
        for c in pick(cands, q["error_correction"] + q["transformation"], ctx, used):
            other, *_ = paired(c)
            if other:
                out.append(error_correction(ctx, c.s, c.a, c.b, match_case(c.token, other[0]), explanation=explain, conf="medium",
                                            notes=["the swapped verb may also fit with a change of meaning"]))
        out += conjugation_exercises(ctx, "indicative", "present", q["conjugation"], lambda l, t: l in pair, explain)
        return out
    return gen


def participle_of(ctx: Ctx, token: str) -> str | None:
    """Lemma of an agreeing participle: escrita/escritos/escritas → escribir."""
    t = token.lower()
    for suffix, repl in (("os", "o"), ("as", "o"), ("a", "o")):
        if t.endswith(suffix):
            for x in ctx.conj.analyze(t[: -len(suffix)] + repl):
                if x.mood == "participle":
                    return x.lemma
    return next((x.lemma for x in ctx.conj.analyze(t) if x.mood == "participle"), None)


def passive_topic(explain: str):
    ser = {"es", "son", "fue", "fueron", "era", "eran", "será", "serán", "ha sido", "han sido", "sido", "ser", "sea"}

    def gen(ctx: Ctx, n: int) -> list[dict]:
        q = quota(n)
        found = []
        for s in ctx.sentences:
            if not usable(s):
                continue
            sp = ctx.spans(s)
            for i in range(len(sp) - 1):
                if sp[i][2].lower() not in ser:
                    continue
                a, b, tok = sp[i + 1]
                lemma = participle_of(ctx, tok)
                if lemma and tok.lower().endswith(("o", "a", "os", "as")) and not ctx.homograph(tok.lower()):
                    found.append((s, a, b, tok, lemma))
        out, used = [], set()
        key = lambda x: x[0].es_id
        for s, a, b, tok, lemma in pick(found, q["cloze"] + q["multiple_choice"], ctx, used, key):
            part = ctx.conj.participle(lemma) or tok
            if len(out) < q["cloze"]:
                out.append(cloze(ctx, s, a, b, tok, "Completa con el participio del verbo (concuerda con el sujeto).", hint=lemma,
                                 explanation=explain, conf="medium", notes=["agreement and passive reading checked only by the participle table"]))
            else:
                wrong = [x for x in dict.fromkeys([part[:-1] + e for e in ("o", "a", "os", "as")]) if x.lower() != tok.lower()]
                out.append(multiple_choice(ctx, s, a, b, tok, [match_case(tok, w) for w in wrong[:3]], "Elige el participio con la concordancia correcta.",
                                           explanation=explain, conf="medium", notes=["participle agreement"]))
        return out
    return gen


def se_topic(explain: str):
    lemmas = {"vender", "hablar", "decir", "necesitar", "buscar", "prohibir", "permitir", "alquilar", "ver", "oír", "poder", "vivir", "comer", "trabajar", "usar", "hacer", "saber", "creer", "pensar", "dar"}

    def gen(ctx: Ctx, n: int) -> list[dict]:
        q = quota(n)
        cands = [c for c in verb_candidates(ctx, "indicative", "present", lemma_ok=lambda l, t: l in lemmas, before=re.compile(r"(?:^|\s)se\s+$"))
                 if c.persons <= {(3, "s"), (3, "p")} and single_person(c)]
        out, used = [], set()
        for c in pick(cands, q["cloze"], ctx, used):
            p, num = sorted(c.persons)[0]
            out.append(cloze(ctx, c.s, c.a, c.b, c.token, "Completa con el presente del verbo (se + 3.ª persona).", hint=c.lemma, explanation=explain,
                             conf="medium", verify=Verify(lemma=c.lemma, mood="indicative", tense="present", person=3, number=num),
                             notes=["check that 'se' is passive/impersonal and not reflexive"]))
        for c in pick(cands, q["multiple_choice"] + q["error_correction"], ctx, used):
            p, num = sorted(c.persons)[0]
            other = "p" if num == "s" else "s"
            wrong = sorted(ctx.conj.forms(c.lemma, "indicative", "present", 3, other))
            if not wrong:
                continue
            if len(out) % 2:
                out.append(error_correction(ctx, c.s, c.a, c.b, match_case(c.token, wrong[0]), explanation=explain, conf="medium",
                                            notes=["agreement of the verb with the thing"]))
            else:
                extra = other_forms(ctx, c, {c.token.lower(), wrong[0]}, [("indicative", "preterite"), ("indicative", "imperfect")], 1)
                out.append(multiple_choice(ctx, c.s, c.a, c.b, c.token, [match_case(c.token, wrong[0]), *extra], "Elige la forma correcta.",
                                           explanation=explain, conf="medium", notes=["agreement of the verb with the thing"]))
        return out
    return gen


def build_registry(conj_getter) -> dict[str, Callable[[Ctx, int], list[dict]]]:
    """topic id → generator. Topics without a reliable deterministic detector are absent."""
    imperative_neg = re.compile(r"^(?:no\s+)(?:(?:me|te|se|lo|la|le|nos|os|los|las|les)\s+){0,2}$")
    R: dict[str, Callable] = {}

    R["ser-estar"] = ser_estar_topic("Ser: identidad, origen, profesión, material. Estar: estado, ubicación, resultado.")
    R["por-para"] = word_contrast_topic(
        [["por"], ["para"]], "Completa con por o para.",
        "Por: causa, medio, duración, lugar de paso. Para: finalidad, destinatario, plazo, destino.",
        note="por/para can both fit some sentences with a change of meaning; check the blank is unambiguous")
    R["preterito-imperfecto"] = verb_form_topic(
        "indicative", "preterite",
        "Pretérito indefinido: acción terminada. Imperfecto: hábito, descripción, acción en curso.",
        mc_conf="medium", wrong_pool=[("indicative", "imperfect"), ("indicative", "present"), ("indicative", "future")],
        transform_to=("present", "indicative", "imperfect"), ec_conf="medium")
    R["preterito-perfecto"] = compound_topic("indicative", "present", "Pretérito perfecto: haber en presente + participio.")
    R["pluscuamperfecto"] = compound_topic("indicative", "imperfect", "Pluscuamperfecto: había + participio, acción anterior a otro momento del pasado.")
    R["futuro"] = verb_form_topic(
        "indicative", "future", "Futuro simple: infinitivo + -é, -ás, -á, -emos, -éis, -án (raíces irregulares).",
        mc_conf="medium", wrong_pool=[("indicative", "present"), ("indicative", "conditional"), ("indicative", "imperfect")],
        transform_to=("present", "indicative", "future"), ec_conf="medium")
    R["condicional"] = verb_form_topic(
        "indicative", "conditional", "Condicional: infinitivo + -ía, -ías, -ía, -íamos, -íais, -ían.",
        mc_conf="medium", wrong_pool=[("indicative", "future"), ("indicative", "imperfect"), ("subjunctive", "imperfect")],
        transform_to=("present", "indicative", "conditional"), ec_conf="medium")
    R["pronombres-od-oi"] = word_contrast_topic(
        [["se"], ["le"], ["les"]], "Completa con el pronombre correcto (se, le o les).",
        "Le/les se convierten en se delante de lo, la, los, las: Se lo di.", conf="medium",
        note="le/les/se choice depends on number of the recipient: verify against the translation",
        phrase_ok=lambda t, m: re.match(r"\s+(lo|la|los|las)\b", t[m.end():], re.I) is not None)

    reg, irr = make_regular_filter(conj_getter), make_irregular_filter(conj_getter)
    R["subj-presente-regular"] = trigger_topic(
        before("quiero", "quieres", "quiere", "queremos", "quieren", "espero", "esperas", "espera", "esperamos", "prefiero", "necesito", "necesitas", "pido", "ojalá", "dudo", "creo", "creemos"),
        "subjunctive", "present", "Presente de subjuntivo regular: raíz de la forma yo + vocal contraria (-ar → -e, -er/-ir → -a).",
        "Completa con el presente de subjuntivo.", wrong_pool=SUBJ_PRESENT_WRONG, lemma_ok=reg, extra_ok=frozenset({"imperative"}))
    R["subj-presente-irregular"] = trigger_topic(
        before("quiero", "quieres", "quiere", "queremos", "quieren", "espero", "esperas", "espera", "esperamos", "prefiero", "necesito", "necesitas", "pido", "ojalá", "dudo", "creo", "creemos"),
        "subjunctive", "present", "Presente de subjuntivo irregular: verbos con yo irregular (tener → tenga) y ser, estar, ir, saber, haber, dar.",
        "Completa con el presente de subjuntivo.", wrong_pool=SUBJ_PRESENT_WRONG, lemma_ok=irr, extra_ok=frozenset({"imperative"}))
    R["subj-deseos"] = trigger_topic(
        before("quiero", "quieres", "quiere", "queremos", "quieren", "quería", "esperar", "espero", "esperamos", "prefiero", "prefiere", "pido", "pide", "pedimos", "aconsejo", "aconseja", "necesito", "necesita", "prohíbo", "prohíbe", "permito", "permite", "recomiendo", "recomienda", "deseo", "desea", "es mejor", "es necesario", "es importante", "ojalá"),
        "subjunctive", "present", "Verbos de deseo, petición o consejo + que + subjuntivo cuando los sujetos son distintos.",
        "Completa con el presente de subjuntivo.", wrong_pool=SUBJ_PRESENT_WRONG, extra_ok=frozenset({"imperative"}))
    R["subj-emociones"] = trigger_topic(
        before("me alegro", "te alegras", "se alegra", "nos alegramos", "me molesta", "te molesta", "le molesta", "siento", "sentimos", "es una pena", "es una lástima", "me da miedo", "tengo miedo", "me gusta", "te gusta", "le gusta", "me encanta", "te encanta", "me sorprende", "me parece bien", "me parece mal", "es increíble", "lamento", "me importa", de=True),
        "subjunctive", "present", "Emoción o valoración + que + subjuntivo (me alegro de que, es una pena que...).",
        "Completa con el presente de subjuntivo.", wrong_pool=SUBJ_PRESENT_WRONG, extra_ok=frozenset({"imperative"}))
    R["subj-duda"] = trigger_topic(
        before("no creo", "no creemos", "no pienso", "dudo", "dudamos", "no es verdad", "no es cierto", "es posible", "es probable", "es imposible", "puede ser", "no parece", "no estoy seguro de", "no estoy segura de", "niego", de=True),
        "subjunctive", "present", "Duda, negación o posibilidad + que + subjuntivo (no creo que, dudo que, es posible que).",
        "Completa con el presente de subjuntivo.", wrong_pool=SUBJ_PRESENT_WRONG, extra_ok=frozenset({"imperative"}))
    R["imperativo-afirmativo"] = verb_form_topic(
        "imperative", None, "Imperativo afirmativo de tú: forma de tercera persona del presente; ocho irregulares (di, haz, ve, ten, pon, sal, sé, ven).",
        lemma_ok=lambda l, t: t is None or (t in {"di", "haz", "ve", "ten", "pon", "sal", "sé", "ven"}) or t.endswith(("ad", "ed", "id")),
        need_start=True, mc_conf="medium", wrong_pool=[("indicative", "present"), ("subjunctive", "present"), ("indicative", "future")],
        conj_lemma_ok=lambda l, t: True, conj_persons=[(2, "s")], flags="", ec_conf="medium")
    R["imperativo-negativo-pronombres"] = trigger_topic(
        imperative_neg, "subjunctive", "present", "Imperativo negativo: no + presente de subjuntivo; los pronombres van delante del verbo.",
        "Completa con el imperativo negativo.", wrong_pool=[("indicative", "present"), ("indicative", "future")], extra_ok=frozenset({"imperative"}))
    R["oraciones-relativo"] = word_contrast_topic(
        [["que"], ["quien", "quienes"], ["donde"], ["cuyo", "cuya", "cuyos", "cuyas"], ["cual", "cuales"]],
        "Completa con el pronombre relativo.", "Relativos: que, quien, donde, cuyo (concuerda con lo que posee), el cual.",
        conf="medium", note="'que' also appears as a conjunction; blanks on 'que' are only appropriate when it is a relative pronoun",
        phrase_ok=lambda t, m: m.group(1).lower() != "que" or re.search(r"\b(el|la|los|las|un|una)\s+\w+\s+que\b", t[: m.end()], re.I) is not None)
    R["subj-imperfecto-formacion"] = verb_form_topic(
        "subjunctive", "imperfect", "Imperfecto de subjuntivo: 3.ª persona plural del indefinido sin -ron + -ra/-se.",
        wrong_pool=SUBJ_IMPERF_WRONG, mc_conf="high")
    R["subj-imperfecto-usos"] = trigger_topic(
        re.compile(r"(?:quer[íi]\w*|quisiera\w*|esperaba\w*|prefer[íi]\w*|ojal[aá]|como si|me gustar[íi]\w*|ped[íi]\w*|dud[aá]\w*|no cre[íi]\w*|era necesario|era importante|dijo)\s+(?:de\s+)?(?:que\s+)?(?:\w+\s+){0,2}$"),
        "subjunctive", "imperfect", "Imperfecto de subjuntivo tras un verbo principal en pasado o condicional, ojalá y como si.",
        "Completa con el imperfecto de subjuntivo.", wrong_pool=SUBJ_IMPERF_WRONG)
    R["si-reales"] = trigger_topic(
        re.compile(r"(?:^|[,;]\s*|\s)si\s+(?:\w+\s+){0,1}$"), "indicative", "present",
        "Si + presente de indicativo (condición real); nunca futuro ni subjuntivo tras si.",
        "Completa con el presente de indicativo.", wrong_pool=[("subjunctive", "present"), ("indicative", "future"), ("indicative", "imperfect")],
        conf="medium", mc_conf="medium")
    R["si-irreales"] = trigger_topic(
        re.compile(r"(?:^|[,;]\s*|\s)si\s+(?:\w+\s+){0,1}$"), "subjunctive", "imperfect",
        "Si + imperfecto de subjuntivo → condicional (hipótesis improbable o irreal).",
        "Completa con el imperfecto de subjuntivo.", wrong_pool=[("indicative", "conditional"), ("indicative", "imperfect"), ("indicative", "present")])
    R["se-impersonal-pasiva-refleja"] = se_topic("Se + verbo en 3.ª persona; en la pasiva refleja el verbo concuerda con el sujeto (Se venden pisos).")
    R["voz-pasiva"] = passive_topic("Ser + participio concordando con el sujeto: La casa fue construida.")
    R["conectores-contraste"] = word_contrast_topic(
        [["sin embargo"], ["no obstante"], ["aunque"], ["a pesar de"], ["mientras que"], ["en cambio"]],
        "Completa con el conector.", "Contraste y concesión: sin embargo, no obstante, aunque, a pesar de, mientras que, en cambio.",
        conf="medium", note="several connectors may fit; check that the blank has one clear answer")
    R["conectores-causa-consecuencia"] = word_contrast_topic(
        [["porque"], ["ya que"], ["puesto que"], ["así que"], ["por eso"], ["por lo tanto"], ["para que"]],
        "Completa con el conector.", "Causa: porque, ya que, puesto que. Consecuencia: así que, por eso, por lo tanto. Finalidad: para que + subjuntivo.",
        conf="medium", note="several connectors may fit; check that the blank has one clear answer")
    R["subj-perfecto"] = compound_topic(
        "subjunctive", "present", "Pretérito perfecto de subjuntivo: haya + participio.", mc_conf="high")
    return R
