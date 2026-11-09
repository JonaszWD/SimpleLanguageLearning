"""Sentence translation for the article reader: the whole sentence into English, plus which English
words correspond to the word the learner tapped. Uses DeepL (DEEPL_API_KEY, never from code).

DeepL has no word alignment, so the tapped word is wrapped in an XML tag. With tag_handling=xml
DeepL keeps the tag and puts it around the corresponding words of the translation."""

import os
from collections import OrderedDict
from html import escape, unescape
import re

import httpx

from . import verbs

MAX_SENTENCE = 1000
TARGET = os.environ.get("DEEPL_TARGET_LANG", "EN-GB")
_CACHE: OrderedDict[tuple, dict] = OrderedDict()
_CACHE_SIZE = 500
_TAG = re.compile(r"<x>(.*?)</x>", re.S)
_ANY_TAG = re.compile(r"</?x>")


def available() -> bool:
    return bool(os.environ.get("DEEPL_API_KEY"))


def _endpoint(key: str) -> str:
    # Free-plan keys end in ":fx" and use a different host.
    return "https://api-free.deepl.com/v2/translate" if key.endswith(":fx") else "https://api.deepl.com/v2/translate"


def translate(sentence: str, word: str, offset: int | None = None, *, client: httpx.Client | None = None) -> dict:
    """Returns {"translation", "word_en", "start", "end", "note"}. word_en is always a substring of
    translation. start/end delimit the tapped word, or the whole verb group ("ha llegado"), in the
    sentence; note explains the verb form (empty if the word isn't a known verb)."""
    sentence, word = sentence.strip(), word.strip()
    if not sentence or not word:
        raise ValueError("Nothing to translate.")
    if len(sentence) > MAX_SENTENCE:
        raise ValueError("Sentence too long.")
    key = (sentence, word.lower(), offset)
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key]
    api_key = os.environ.get("DEEPL_API_KEY")
    if not api_key:
        raise RuntimeError("Set DEEPL_API_KEY on the server")

    verb = verbs.explain(sentence, word, offset)
    if verb:
        start, end, note = verb["start"], verb["end"], verb["note"]
    else:
        start = offset if offset is not None and sentence.startswith(word, offset) else sentence.lower().find(word.lower())
        end, note = (start + len(word) if start >= 0 else -1), ""
    marked = escape(sentence, quote=False)
    if start >= 0:
        marked = "".join([escape(sentence[:start], quote=False), "<x>", escape(sentence[start:end], quote=False), "</x>", escape(sentence[end:], quote=False)])
    res = (client or httpx).post(
        _endpoint(api_key), headers={"Authorization": f"DeepL-Auth-Key {api_key}"}, timeout=15,
        json={"text": [marked], "source_lang": "ES", "target_lang": TARGET, "tag_handling": "xml"})
    res.raise_for_status()
    out = res.json()["translations"][0]["text"]

    m = _TAG.search(out)
    word_en = unescape(_ANY_TAG.sub("", m.group(1))).strip() if m else ""
    text = unescape(_ANY_TAG.sub("", out)).strip()
    if not text:
        raise RuntimeError("DeepL returned no translation.")
    result = {"translation": text, "word_en": word_en if word_en and word_en.lower() in text.lower() else "",
              "start": max(start, 0), "end": max(end, 0), "note": note}
    _CACHE[key] = result
    while len(_CACHE) > _CACHE_SIZE:
        _CACHE.popitem(last=False)
    return result
