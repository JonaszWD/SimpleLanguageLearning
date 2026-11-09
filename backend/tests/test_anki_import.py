import io
import json
import sqlite3
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.anki_import import AnkiImportError, parse_apkg
from app.main import app


def make_apkg(member="collection.anki21") -> bytes:
    con = sqlite3.connect(":memory:")
    con.executescript("""
        CREATE TABLE col (crt integer, models text, decks text);
        CREATE TABLE notes (id integer, guid text, mid integer, tags text, flds text);
        CREATE TABLE cards (id integer, nid integer, did integer, ord integer, type integer,
            queue integer, due integer, ivl integer, factor integer, reps integer, lapses integer);
    """)
    models = {"1": {"id": 1, "name": "Basic", "type": 0, "css": "",
                    "flds": [{"name": "Front", "ord": 0}, {"name": "Back", "ord": 1}],
                    "tmpls": [{"name": "Card 1", "ord": 0, "qfmt": "{{Front}}", "afmt": "{{Back}}"}]}}
    decks = {"1": {"id": 1, "name": "Spanish"}}
    con.execute("INSERT INTO col VALUES (1700000000, ?, ?)", (json.dumps(models), json.dumps(decks)))
    con.execute("INSERT INTO notes VALUES (10, 'g', 1, ' verbs ', 'hola\x1fhello')")
    con.execute("INSERT INTO cards VALUES (100, 10, 1, 0, 2, 2, 5, 12, 2300, 4, 1)")
    raw = con.serialize()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(member, raw)
    return buf.getvalue()


def test_parse():
    out = parse_apkg(make_apkg())
    assert out["decks"] == [{"id": 1, "name": "Spanish"}]
    assert out["notes"][0]["fields"] == ["hola", "hello"]
    assert out["notes"][0]["tags"] == ["verbs"]
    card = out["cards"][0]
    assert card["kind"] == "review" and card["ivl"] == 12 and card["ease"] == 2.3
    assert card["due"] == (1700000000 + 5 * 86400) * 1000


def test_new_format_rejected():
    with pytest.raises(AnkiImportError):
        parse_apkg(make_apkg("collection.anki21b"))


def test_endpoint():
    client = TestClient(app)
    r = client.post("/api/anki/import", files={"file": ("d.apkg", make_apkg())})
    assert r.status_code == 200 and r.json()["notes"]
    r = client.post("/api/anki/import", files={"file": ("d.apkg", b"nope")})
    assert r.status_code == 422
    assert client.get("/api/health").json() == {"status": "ok"}


def test_vocab_pack_levels():
    from app.packs import LEVELS, level_for

    assert [level_for(r) for r in (1, 600, 601, 1500, 1501, 3000, 3001, 5000)] == \
        ["A1", "A1", "A2", "A2", "B1", "B1", "B2", "B2"]
    assert LEVELS[0][1] == 1 and LEVELS[-1][2] == 5000
    assert all(a[2] + 1 == b[1] for a, b in zip(LEVELS, LEVELS[1:]))  # no gaps between levels


def test_sentences_only_keeps_clips_and_drops_cards(tmp_path):
    import json
    from app.packs import sentences_only
    pack = tmp_path / "p"
    pack.mkdir()
    (pack / "manifest.json").write_text(json.dumps({"id": "p", "models": [1], "decks": [1], "notes": [1], "cards": [1],
                                                    "clips": [{"text": "Hola."}], "audio": ["a.mp3"]}))
    (pack / "pack.json").write_text(json.dumps({"id": "p", "notes": 1, "clips": 1, "version": "x"}))
    meta = sentences_only(pack)
    m = json.loads((pack / "manifest.json").read_text())
    assert m["notes"] == m["cards"] == [] and m["clips"] and m["audio"] == ["a.mp3"]
    assert meta["notes"] == 0 and meta["clips"] == 1 and meta["version"] != "x"
    assert json.loads((tmp_path / "index.json").read_text())[0]["id"] == "p"
