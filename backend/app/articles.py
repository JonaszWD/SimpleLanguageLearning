"""Fetch news articles from allowed sites and prepare them for reading with a glossary."""

import json
import os
import re
import unicodedata
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

import httpx
import trafilatura

# Hosts the server may fetch from. Extend with ARTICLE_HOSTS="a.com,b.com".
ALLOWED_HOSTS = {"elmundo.es", "elpais.com", *filter(None, os.environ.get("ARTICLE_HOSTS", "").split(","))}
# El País blocks automated fetches (HTTP 403), so its articles come in via paste instead.
PASTE_ONLY = {"elpais.com"}
UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"

FEEDS = {
    "elmundo": ("El Mundo", "https://e00-elmundo.uecdn.es/elmundo/rss/portada.xml"),
    "elpais": ("El País", "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/portada"),
}
MIN_WORDS = 150


class ArticleError(ValueError):
    pass


def host_allowed(url: str) -> bool:
    p = urlparse(url)
    h = (p.hostname or "").lower()
    return p.scheme == "https" and any(h == d or h.endswith("." + d) for d in ALLOWED_HOSTS)


def is_paste_only(url: str) -> bool:
    h = (urlparse(url).hostname or "").lower()
    return any(h == d or h.endswith("." + d) for d in PASTE_ONLY)


def feed(source: str, limit: int = 30) -> list[dict]:
    if source not in FEEDS:
        raise ArticleError("Unknown source.")
    name, url = FEEDS[source]
    r = httpx.get(url, headers={"User-Agent": UA}, timeout=20, follow_redirects=True)
    r.raise_for_status()
    items = []
    for it in ET.fromstring(r.content).iter("item"):
        link = (it.findtext("link") or "").strip()
        if not link or not host_allowed(link):
            continue
        items.append({
            "title": (it.findtext("title") or "").strip(),
            "summary": re.sub(r"<[^>]+>", "", it.findtext("description") or "").strip()[:200],
            "url": link, "source": name, "pasteOnly": is_paste_only(link),
            "published": (it.findtext("pubDate") or "").strip(),
        })
        if len(items) >= limit:
            break
    return items


def fetch(url: str) -> dict:
    if not host_allowed(url):
        raise ArticleError("That site isn't on the allowed list.")
    if is_paste_only(url):
        raise ArticleError("This site blocks automatic downloads. Open it in Safari, copy the text and paste it here.")
    for _ in range(4):  # follow redirects by hand so every hop is checked
        r = httpx.get(url, headers={"User-Agent": UA}, timeout=20, follow_redirects=False)
        if r.is_redirect:
            url = str(r.url.join(r.headers["location"]))
            if not host_allowed(url):
                raise ArticleError("Redirected to a site that isn't allowed.")
            continue
        break
    else:
        raise ArticleError("Too many redirects.")
    if r.status_code != 200:
        raise ArticleError(f"The site answered {r.status_code}.")
    raw = trafilatura.extract(r.content, output_format="json", with_metadata=True,
                              favor_precision=True, include_comments=False)
    if not raw:
        raise ArticleError("Couldn't find an article on that page.")
    data = json.loads(raw)
    return {"title": data.get("title") or "", "text": data.get("text") or "", "url": url,
            "source": data.get("sitename") or urlparse(url).hostname}


def prepare(title: str, text: str, url: str = "", source: str = "", dictionary=None) -> dict:
    text = unicodedata.normalize("NFC", text).replace("\r", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip()]
    text = "\n\n".join(paragraphs)
    if not text:
        raise ArticleError("No text to import.")
    words = len(text.split())
    return {
        "title": unicodedata.normalize("NFC", title).strip() or paragraphs[0][:80],
        "text": text, "url": url, "source": source, "words": words,
        "truncated": words < MIN_WORDS,
        "glossary": dictionary.glossary(text) if dictionary else {},
        "dictionary": bool(dictionary and dictionary.available),
    }
