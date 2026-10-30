"""Content packs: a filtered Anki deck + its audio, prepared once on the server.

The phone downloads a pack into IndexedDB so reviews and shadowing work offline.

    uv run python -m app.packs build ../deck.apkg --id spanish-9000 \
        --title "Spanish 9000 sentences" --min-difficulty 2500 --min-words 3
"""

import argparse
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path

from mutagen.mp3 import MP3

from .anki_import import parse_apkg

SOUND = re.compile(r"\[sound:(.+?)\]")
CLIP_MIN, CLIP_MAX, GAP = 10.0, 20.0, 0.4  # seconds; GAP is the pause between sentences

# The source template never shows the Audio field. English stays on the front as a hint.
QFMT = "{{cloze:Text}}<br><br><span class=\"hint\">{{EnglishSentence}}</span>"
AFMT = "{{cloze:Text}}<br><br><span class=\"hint\">{{EnglishSentence}}</span><br>{{Audio}}"


def make_clips(sentences: list[dict]) -> list[dict]:
    """Group consecutive sentences into shadowing clips of roughly 10-20 s."""
    clips, cur, total = [], [], 0.0
    for s in sentences:
        added = s["dur"] + (GAP if cur else 0)
        if cur and (total >= CLIP_MIN or total + added > CLIP_MAX):
            clips.append(cur)
            cur, total, added = [], 0.0, s["dur"]
        cur.append(s)
        total += added
    if cur:
        clips.append(cur)
    return [
        {
            "text": " ".join(s["text"] for s in c),
            "english": " ".join(s["english"] for s in c),
            "sounds": [s["audio"] for s in c],
            "dur": round(sum(s["dur"] for s in c) + GAP * (len(c) - 1), 1),
        }
        for c in clips
    ]


def write_index(packs_dir: Path) -> None:
    """index.json lists every pack. It is what the app reads, from this server or from static hosting."""
    metas = [json.loads(p.read_text()) for p in sorted(packs_dir.glob("*/pack.json"))]
    (packs_dir / "index.json").write_text(json.dumps(metas))


def build_pack(src: Path, out: Path, pack_id: str, title: str,
               min_difficulty: int, min_words: int) -> dict:
    data = src.read_bytes()
    parsed = parse_apkg(data)
    zf = zipfile.ZipFile(io.BytesIO(data))
    media = {name: num for num, name in json.loads(zf.read("media")).items()}

    model = next(m for m in parsed["models"] if m["cloze"])
    ix = {f: i for i, f in enumerate(model["fields"])}
    model = {**model, "css": "",
             "templates": [{"name": "Cloze", "qfmt": QFMT, "afmt": AFMT}]}

    kept = []
    for n in parsed["notes"]:
        f = n["fields"]
        if n["mid"] != model["id"]:
            continue
        difficulty, words = int(f[ix["Difficulty"]]), int(f[ix["NumberOfSpanishWords"]])
        if difficulty < min_difficulty or words < min_words:
            continue
        m = SOUND.search(f[ix["Audio"]])
        if not m or m.group(1) not in media:
            continue
        kept.append((difficulty, n, m.group(1)))
    kept.sort(key=lambda k: (k[0], k[1]["id"]))

    audio_dir = out / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    notes, sentences, audio_bytes = [], [], 0
    for rank, (_, n, orig) in enumerate(kept):
        f = n["fields"]
        name = f"{f[ix['EnglishSentenceID']]}-{f[ix['SpanishSentenceID']]}.mp3"
        path = audio_dir / name
        path.write_bytes(zf.read(media[orig]))
        audio_bytes += path.stat().st_size
        dur = MP3(path).info.length
        f[ix["Audio"]] = f"[sound:{name}]"
        notes.append({**n, "pos": rank})
        sentences.append({"text": f[ix["SpanishSentence"]], "english": f[ix["EnglishSentence"]],
                          "audio": name, "dur": dur})

    kept_ids = {n["id"] for n in notes}
    pos = {n["id"]: n["pos"] for n in notes}
    cards = [
        {"id": c["id"], "nid": c["nid"], "did": c["did"], "ord": c["ord"], "pos": pos[c["nid"]], "kind": "new"}
        for c in parsed["cards"] if c["nid"] in kept_ids
    ]
    used = {c["did"] for c in cards}
    manifest = {
        "id": pack_id, "title": title, "models": [model],
        "decks": [d for d in parsed["decks"] if d["id"] in used],
        "notes": notes, "cards": cards, "clips": make_clips(sentences),
        "audio": [s["audio"] for s in sentences],
    }
    text = json.dumps(manifest, ensure_ascii=False)
    (out / "manifest.json").write_text(text)
    meta = {"id": pack_id, "title": title, "notes": len(notes), "clips": len(manifest["clips"]),
            "audioFiles": len(sentences), "audioBytes": audio_bytes,
            "version": hashlib.sha1(text.encode()).hexdigest()[:10]}
    (out / "pack.json").write_text(json.dumps(meta))
    write_index(out.parent)
    return {**meta, "dropped": len(parsed["notes"]) - len(notes)}


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("src", type=Path)
    b.add_argument("--id", required=True)
    b.add_argument("--title", required=True)
    b.add_argument("--min-difficulty", type=int, default=2500)
    b.add_argument("--min-words", type=int, default=3)
    b.add_argument("--packs-dir", type=Path, default=Path(__file__).resolve().parents[2] / "content" / "packs")
    a = p.parse_args()
    print(build_pack(a.src, a.packs_dir / a.id, a.id, a.title, a.min_difficulty, a.min_words))


if __name__ == "__main__":
    main()
