"""Find a podcast's RSS URL via the iTunes Search API (no key) and, if keys are set, Podcast Index.

Candidates are only shown. Nothing is saved until the user confirms one.
"""

import hashlib
import os
import time
from dataclasses import dataclass

import httpx

from . import config

ITUNES = "https://itunes.apple.com/search"
PODCASTINDEX = "https://api.podcastindex.org/api/1.0/search/byterm"


@dataclass(frozen=True)
class Candidate:
    title: str
    author: str
    feed_url: str
    country: str
    source: str            # "itunes" | "podcastindex"
    link: str = ""

    def line(self) -> str:
        return f"{self.title} · {self.author} · {self.country or '?'} · [{self.source}]\n      {self.feed_url}"


def search_itunes(term: str, country: str | None = None, limit: int = 8, client: httpx.Client | None = None) -> list[Candidate]:
    params = {"term": term, "media": "podcast", "limit": limit}
    if country:
        params["country"] = country
    r = (client or httpx).get(ITUNES, params=params, timeout=20, headers={"User-Agent": config.USER_AGENT})
    r.raise_for_status()
    return [Candidate(x["collectionName"], x.get("artistName", ""), x["feedUrl"], x.get("country", ""), "itunes",
                      x.get("collectionViewUrl", ""))
            for x in r.json().get("results", []) if x.get("feedUrl")]


def search_podcastindex(term: str, limit: int = 8, client: httpx.Client | None = None) -> list[Candidate]:
    """Needs PODCASTINDEX_API_KEY and PODCASTINDEX_API_SECRET in the environment."""
    key, secret = os.environ.get("PODCASTINDEX_API_KEY"), os.environ.get("PODCASTINDEX_API_SECRET")
    if not key or not secret:
        return []
    now = str(int(time.time()))
    headers = {"User-Agent": config.USER_AGENT, "X-Auth-Key": key, "X-Auth-Date": now,
               "Authorization": hashlib.sha1((key + secret + now).encode()).hexdigest()}
    r = (client or httpx).get(PODCASTINDEX, params={"q": term, "max": limit}, headers=headers, timeout=20)
    r.raise_for_status()
    return [Candidate(x["title"], x.get("author", ""), x["url"], x.get("language", ""), "podcastindex", x.get("link", ""))
            for x in r.json().get("feeds", []) if x.get("url")]


def candidates(term: str, country: str | None = None, client: httpx.Client | None = None) -> list[Candidate]:
    out, seen = [], set()
    for c in [*search_itunes(term, country, client=client), *search_podcastindex(term, client=client)]:
        if c.feed_url not in seen:
            seen.add(c.feed_url)
            out.append(c)
    return out
