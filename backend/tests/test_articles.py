import json

import pytest
from fastapi.testclient import TestClient

from app import articles
from app.dictionary import Dictionary, build
from app.main import app
from app.routers import articles as router


@pytest.fixture
def dic(tmp_path):
    src = tmp_path / "k.jsonl"
    rows = [
        {"word": "hablar", "pos": "verb", "senses": [{"glosses": ["to speak"]}, {"glosses": ["to talk"], "tags": ["rare"]}],
         "forms": [{"form": "hablamos", "tags": ["present", "indicative"]}, {"form": "hablar", "tags": ["infinitive"]},
                   {"form": "x", "tags": ["table-tags"]}]},
        {"word": "casa", "pos": "noun", "senses": [{"glosses": ["house"]}]},
        {"word": "casas", "pos": "noun", "senses": [{"glosses": ["plural of casa"], "form_of": [{"word": "casa"}]}]},
        {"word": "Madrid", "pos": "name", "senses": [{"glosses": ["the capital of Spain"]}]},
    ]
    src.write_text("\n".join(json.dumps(r) for r in rows))
    out = tmp_path / "d.sqlite"
    build(src, out)
    return Dictionary(out)


def test_lookup_forms_and_lemmas(dic):
    assert dic.lookup("hablamos")[0]["lemma"] == "hablar"
    assert dic.lookup("hablamos")[0]["gloss"] == ["to speak", "to talk"]  # rare sense last
    assert dic.lookup("casas")[0]["gloss"] == ["house"]
    assert dic.lookup("Madrid")[0]["lemma"] == "Madrid"


def test_glossary_keys_are_lowercase(dic):
    g = dic.glossary("Hablamos en Madrid. Las casas.")
    assert set(g) >= {"hablamos", "madrid", "casas"} and "las" not in g


def test_prepare(dic):
    a = articles.prepare("T", "Hablamos de casas.\r\n\r\n\r\nOtra línea.", dictionary=dic)
    assert a["text"] == "Hablamos de casas.\n\nOtra línea." and a["truncated"] and a["glossary"]["casas"]


def test_host_rules():
    assert articles.host_allowed("https://www.elmundo.es/x.html")
    assert not articles.host_allowed("http://www.elmundo.es/x.html")
    assert not articles.host_allowed("https://evil.com/?elmundo.es")
    assert not articles.host_allowed("https://elmundo.es.evil.com/")
    with pytest.raises(articles.ArticleError):
        articles.fetch("https://elpais.com/x.html")


def test_endpoints(dic, monkeypatch):
    monkeypatch.setattr(router, "_dictionary", dic)
    c = TestClient(app)
    r = c.post("/api/articles/prepare", json={"title": "t", "text": "Hablamos."})
    assert r.status_code == 200 and r.json()["glossary"]["hablamos"]
    assert c.post("/api/articles/import", json={"url": "https://example.com/a"}).status_code == 422
    assert c.post("/api/articles/prepare", json={"text": "  "}).status_code == 422


def test_service_worker_tracks_frontend(tmp_path, monkeypatch):
    from app import build, main
    (tmp_path / "sw.js").write_text("// sw")
    (tmp_path / "index.html").write_text("a")
    (tmp_path / "js").mkdir()
    (tmp_path / "js" / "x.js").write_text("1")
    monkeypatch.setattr(main, "FRONTEND_DIR", tmp_path)
    c = TestClient(app)
    v1 = c.get("/api/version").json()["version"]
    body = c.get("/sw.js").text
    assert body.startswith("self.__BUILD__") and '"js/x.js"' in body and '"/sw.js"' not in body.split("\n")[0]
    (tmp_path / "js" / "x.js").write_text("2")
    assert c.get("/api/version").json()["version"] != v1


def test_daily_cache(tmp_path, monkeypatch, dic):
    from app import daily
    long_text = "Hablamos de casas. " * 100
    items = [
        {"title": "A", "url": "https://www.elmundo.es/a.html", "pasteOnly": False, "published": "Fri, 30 Oct 2026 08:00:00 +0100"},
        {"title": "Short", "url": "https://www.elmundo.es/b.html", "pasteOnly": False, "published": ""},
        {"title": "P", "url": "https://elpais.com/c.html", "pasteOnly": True, "published": ""},
    ]
    monkeypatch.setattr(articles, "feed", lambda *a, **k: items)
    monkeypatch.setattr(articles, "fetch", lambda url: {"title": "T", "text": long_text if url.endswith("a.html") else "corto", "url": url, "source": "El Mundo"})
    assert daily.refresh(dic, tmp_path) == 1
    idx = daily.index(tmp_path)
    assert [a["id"] for a in idx] == [daily.article_id(items[0]["url"])]
    assert daily.get(idx[0]["id"], tmp_path)["glossary"]["casas"]
    assert daily.get(daily.article_id(items[1]["url"]), tmp_path) is None  # too short: skipped
    assert daily.get("../x", tmp_path) is None
    assert daily.refresh(dic, tmp_path) == 0  # nothing new, nothing refetched


def _deepl(reply, seen=None):
    import httpx

    def handler(request):
        if seen is not None:
            seen.append(json.loads(request.content))
        return httpx.Response(200, json={"translations": [{"text": reply}]})
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_translate_returns_tagged_words_and_caches(monkeypatch):
    from app import translate as tr
    monkeypatch.setenv("DEEPL_API_KEY", "k:fx")
    monkeypatch.setattr(tr.verbs, "conjugator", lambda: None)  # no verb table: just the tapped word
    tr._CACHE.clear()
    seen = []
    client = _deepl("The president <x>has arrived</x> &amp; left.", seen)
    out = tr.translate("El presidente ha llegado & se fue.", "ha", client=client)
    assert out["translation"] == "The president has arrived & left." and out["word_en"] == "has arrived"
    assert seen[0]["text"] == ["El presidente <x>ha</x> llegado &amp; se fue."]
    assert seen[0]["tag_handling"] == "xml" and seen[0]["source_lang"] == "ES"
    tr.translate("El presidente ha llegado & se fue.", "HA", client=client)
    assert len(seen) == 1


def test_translate_without_tag_has_no_highlight(monkeypatch):
    from app import translate as tr
    monkeypatch.setenv("DEEPL_API_KEY", "k")
    monkeypatch.setattr(tr.verbs, "conjugator", lambda: None)
    tr._CACHE.clear()
    out = tr.translate("Hola amigo.", "amigo", client=_deepl("Hello friend."))
    assert (out["translation"], out["word_en"], out["note"]) == ("Hello friend.", "", "")
    assert (out["start"], out["end"]) == (5, 10)


def test_translate_endpoint_needs_key(monkeypatch):
    monkeypatch.delenv("DEEPL_API_KEY", raising=False)
    res = TestClient(app).post("/api/articles/translate", json={"sentence": "Hola.", "word": "Hola"})
    assert res.status_code == 503
