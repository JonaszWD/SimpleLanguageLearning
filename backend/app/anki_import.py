"""Parse Anki .apkg / .colpkg exports into plain JSON for the frontend.

Only the legacy collection formats are supported (`collection.anki2` and
`collection.anki21`). Anki's newest format (`collection.anki21b`, zstd + protobuf)
is rejected with a message telling the user how to re-export.
"""

import io
import json
import sqlite3
import zipfile

FIELD_SEP = "\x1f"
CARD_KINDS = {0: "new", 1: "learning", 2: "review", 3: "relearn"}


class AnkiImportError(ValueError):
    pass


def _open_collection(zf: zipfile.ZipFile) -> sqlite3.Connection:
    names = set(zf.namelist())
    if "collection.anki21" in names:
        raw = zf.read("collection.anki21")
    elif "collection.anki21b" in names:
        raise AnkiImportError(
            "This deck uses Anki's newest export format. Re-export it with "
            "'Support older Anki versions' ticked."
        )
    elif "collection.anki2" in names:
        raw = zf.read("collection.anki2")
    else:
        raise AnkiImportError("No Anki collection found in this file.")
    con = sqlite3.connect(":memory:")
    con.deserialize(raw)
    return con


def _card_state(kind: int, queue: int, due: int, ivl: int, factor: int,
                reps: int, lapses: int, crt: int) -> dict:
    state = {
        "kind": CARD_KINDS.get(kind, "new"),
        "ivl": max(ivl, 0),
        "ease": (factor or 2500) / 1000,
        "reps": reps,
        "lapses": lapses,
        "suspended": queue == -1,
        "due": None,
    }
    if kind == 2 or (kind == 3 and queue == 2):
        state["due"] = (crt + due * 86400) * 1000
    elif kind in (1, 3):
        state["due"] = due * 1000
    return state


def parse_apkg(data: bytes) -> dict:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise AnkiImportError("Not a valid .apkg file.") from exc

    with zf:
        con = _open_collection(zf)

    try:
        crt, models_json, decks_json = con.execute(
            "SELECT crt, models, decks FROM col"
        ).fetchone()
        if not models_json:
            raise AnkiImportError("Unsupported collection schema.")

        models = []
        for m in json.loads(models_json).values():
            models.append({
                "id": int(m["id"]),
                "name": m["name"],
                "cloze": m.get("type") == 1,
                "css": m.get("css", ""),
                "fields": [f["name"] for f in sorted(m["flds"], key=lambda f: f["ord"])],
                "templates": [
                    {"name": t["name"], "qfmt": t["qfmt"], "afmt": t["afmt"]}
                    for t in sorted(m["tmpls"], key=lambda t: t["ord"])
                ],
            })

        decks = [
            {"id": int(d["id"]), "name": d["name"]}
            for d in json.loads(decks_json).values()
            if not d.get("dyn")
        ]

        notes = [
            {
                "id": nid,
                "guid": guid,
                "mid": mid,
                "fields": flds.split(FIELD_SEP),
                "tags": tags.split(),
            }
            for nid, guid, mid, tags, flds in con.execute(
                "SELECT id, guid, mid, tags, flds FROM notes"
            )
        ]

        cards = [
            {
                "id": cid, "nid": nid, "did": did, "ord": ord_,
                **_card_state(kind, queue, due, ivl, factor, reps, lapses, crt),
            }
            for cid, nid, did, ord_, kind, queue, due, ivl, factor, reps, lapses in con.execute(
                "SELECT id, nid, did, ord, type, queue, due, ivl, factor, reps, lapses FROM cards"
            )
        ]
    except sqlite3.DatabaseError as exc:
        raise AnkiImportError("Could not read the Anki collection.") from exc
    finally:
        con.close()

    return {"decks": decks, "models": models, "notes": notes, "cards": cards}
