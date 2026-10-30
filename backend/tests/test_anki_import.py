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
