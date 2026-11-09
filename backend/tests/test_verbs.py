from app import verbs
from app.grammar.conjugation import Analysis


class FakeConj:
    DATA = {
        "ha": [Analysis("her", "subjunctive", "present", 3, "s"), Analysis("haber", "indicative", "present", 3, "s")],
        "llegado": [Analysis("llegar", "participle", None, None, None)],
        "suba": [Analysis("subir", "subjunctive", "present", 3, "s"), Analysis("subir", "subjunctive", "present", 1, "s"),
                 Analysis("subir", "imperative", None, 3, "s")],
        "hubieran": [Analysis("haber", "subjunctive", "imperfect", 3, "p")],
        "dicho": [Analysis("decir", "participle", None, None, None)],
        "llegando": [Analysis("llegar", "gerund", None, None, None)],
        "casa": [],
    }

    def analyze(self, token):
        return self.DATA.get(token.lower(), [])


S = "El presidente ha llegado a Madrid."


def test_either_word_of_a_compound_gives_the_whole_group():
    for word, off in (("ha", 14), ("llegado", 17)):
        out = verbs.explain(S, word, off, conj=FakeConj())
        assert S[out["start"]:out["end"]] == "ha llegado"
        assert out["note"].startswith("Present perfect of llegar, 3rd person singular (ha + llegado).")


def test_compound_in_the_subjunctive():
    s = "Si lo hubieran dicho antes."
    out = verbs.explain(s, "hubieran", 6, conj=FakeConj())
    assert s[out["start"]:out["end"]] == "hubieran dicho"
    assert out["note"].startswith("Pluperfect subjunctive of decir, 3rd person plural")


def test_simple_form_lists_possible_persons():
    out = verbs.explain("Quieren que suba.", "suba", 13, conj=FakeConj())
    assert out["note"].startswith("Present subjunctive of subir, 1st/3rd person singular.")


def test_gerund_and_non_verbs():
    assert "Gerund" in verbs.explain("Está llegando.", "llegando", 5, conj=FakeConj())["note"]
    assert verbs.explain("La casa.", "casa", 3, conj=FakeConj()) is None


def test_aux_without_participle_is_a_simple_form():
    out = verbs.explain("Ha sido.", "Ha", 0, conj=FakeConj())
    assert out["note"].startswith("Present of haber")
