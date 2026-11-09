"""Explain the verb form a learner tapped in a sentence, and find the full verb group.

"ha llegado" is two words but one verb, so tapping either one yields the span of both plus a short
note: which tense it is, of which verb, and what it is used for. Uses the conjugation table built by
app.grammar.conjugation; without it (or for a word it doesn't know) there is simply no note."""

import re
from dataclasses import dataclass

from .grammar.conjugation import Analysis, Conjugator

WORD = re.compile(r"[^\W\d_]+")
ORDINAL = {1: "1st", 2: "2nd", 3: "3rd"}
NUMBER = {"s": "singular", "p": "plural"}
PRIORITY = {"indicative": 0, "subjunctive": 1, "imperative": 2, "infinitive": 3, "gerund": 4, "participle": 5}

# (mood, tense) -> (name, what it is used for)
SIMPLE = {
    ("indicative", "present"): ("Present", "what is true now, happens regularly, or is planned."),
    ("indicative", "preterite"): ("Preterite", "a finished action in the past."),
    ("indicative", "imperfect"): ("Imperfect", "an ongoing or habitual action in the past."),
    ("indicative", "future"): ("Future", "what will happen."),
    ("indicative", "conditional"): ("Conditional", "what would happen."),
    ("subjunctive", "present"): ("Present subjunctive", "used after verbs of wish, doubt, emotion or necessity, and after 'que' when it isn't plain fact."),
    ("subjunctive", "imperfect"): ("Imperfect subjunctive", "past wishes and doubts, or an 'if' that is unlikely or untrue."),
    ("subjunctive", "future"): ("Future subjunctive", "a rare, formal form for possible future events."),
}
# aux (mood, tense) of haber -> (name, what it is used for)
COMPOUND = {
    ("indicative", "present"): ("Present perfect", "has/have + past participle: done recently or still relevant now."),
    ("indicative", "imperfect"): ("Pluperfect", "had + past participle: done before another point in the past."),
    ("indicative", "preterite"): ("Preterite perfect", "a literary form: had just done something."),
    ("indicative", "future"): ("Future perfect", "will have + past participle: done by a future point, or a guess about the past."),
    ("indicative", "conditional"): ("Conditional perfect", "would have + past participle: what would have happened."),
    ("subjunctive", "present"): ("Present perfect subjunctive", "have done, where the subjunctive is needed (wish, doubt, emotion)."),
    ("subjunctive", "imperfect"): ("Pluperfect subjunctive", "had done, in 'if' clauses and past wishes (si hubiera...)."),
}
OTHER = {
    "infinitive": "Infinitive: the dictionary form of the verb ('to ...').",
    "gerund": "Gerund: the '-ing' form, used for ongoing actions (estar + gerund).",
    "participle": "Past participle: used with haber for perfect tenses, or as an adjective.",
    "imperative": "Imperative: a command.",
}

_conj: Conjugator | None = None
_missing = False


def conjugator() -> Conjugator | None:
    global _conj, _missing
    if _conj is None and not _missing:
        try:
            _conj = Conjugator()
        except FileNotFoundError:
            _missing = True
    return _conj


@dataclass
class Token:
    text: str
    start: int
    end: int


def _groups(analyses: list[Analysis]) -> list[tuple[Analysis, list[tuple[int, str]]]]:
    """One entry per (lemma, mood, tense), best first, with every person/number it could be."""
    seen: dict[tuple, tuple[Analysis, list]] = {}
    for a in analyses:
        key = (a.lemma, a.mood, a.tense)
        seen.setdefault(key, (a, []))
        if a.person and (a.person, a.number) not in seen[key][1]:
            seen[key][1].append((a.person, a.number))
    return sorted(seen.values(), key=lambda g: PRIORITY.get(g[0].mood, 9))


def _person(pn: list[tuple[int, str]]) -> str:
    if not pn:
        return ""
    by_number: dict[str, list[int]] = {}
    for p, n in pn:
        by_number.setdefault(n, []).append(p)
    return " or ".join(f"{'/'.join(ORDINAL[p] for p in sorted(ps))} person {NUMBER[n]}" for n, ps in by_number.items())


def _aux(groups):
    return next(((a, pn) for a, pn in groups if a.lemma == "haber" and a.mood in ("indicative", "subjunctive")), None)


def explain(sentence: str, word: str, offset: int | None = None, *, conj: Conjugator | None = None) -> dict | None:
    """{"start", "end", "note"} for the verb group around the tapped word, or None if it isn't a known verb."""
    conj = conj or conjugator()
    if conj is None:
        return None
    toks = [Token(m.group(), m.start(), m.end()) for m in WORD.finditer(sentence)]
    if offset is None or not sentence.startswith(word, offset):
        offset = sentence.lower().find(word.lower())
    i = next((n for n, t in enumerate(toks) if t.start == offset), None)
    if i is None:
        return None

    def groups(n):
        return _groups(conj.analyze(toks[n].text)) if 0 <= n < len(toks) else []

    def is_participle(n):
        return any(a.mood == "participle" for a, _ in groups(n))

    def adjacent(a, b):  # only whitespace between two tokens
        return not sentence[toks[a].end:toks[b].start].strip()

    here = groups(i)
    # haber + participle, tapped on either word
    pair = None
    if (aux := _aux(here)) and i + 1 < len(toks) and adjacent(i, i + 1) and is_participle(i + 1):
        pair = (i, i + 1, aux)
    elif is_participle(i) and i > 0 and adjacent(i - 1, i) and (aux := _aux(groups(i - 1))):
        pair = (i - 1, i, aux)
    if pair:
        a_i, p_i, (aux_a, pn) = pair
        lemma = next(a.lemma for a, _ in groups(p_i) if a.mood == "participle")
        name, use = COMPOUND.get((aux_a.mood, aux_a.tense), ("Compound tense", "haber + past participle."))
        who = _person(pn)
        note = f"{name} of {lemma}{', ' + who if who else ''} ({toks[a_i].text} + {toks[p_i].text}). {use[0].upper()}{use[1:]}"
        return {"start": toks[a_i].start, "end": toks[p_i].end, "note": note}

    if not here:
        return None
    top, pn = here[0]
    if top.mood in OTHER:
        note = f"{OTHER[top.mood]} From {top.lemma}."
    else:
        name, use = SIMPLE.get((top.mood, top.tense), (None, None))
        if name is None:
            return None
        who = _person(pn)
        note = f"{name} of {top.lemma}{', ' + who if who else ''}. {use[0].upper()}{use[1:]}"
    return {"start": toks[i].start, "end": toks[i].end, "note": note}
