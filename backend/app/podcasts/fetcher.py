"""Poll RSS feeds politely: conditional GET (ETag / Last-Modified) and a minimum interval."""

import hashlib
import re
import time
import xml.etree.ElementTree as ET
from calendar import timegm
from dataclasses import dataclass
from datetime import datetime, timezone

import feedparser
import httpx

from . import config
from .registry import Feed
from .store import Store

PODCAST_NS = "{https://podcastindex.org/namespace/1.0}"


@dataclass
class PollResult:
    feed_id: str
    status: str                 # updated | not-modified | skipped | error
    new: int = 0
    latest: str | None = None
    error: str | None = None


def episode_id(feed_id: str, guid: str) -> str:
    return hashlib.sha1(f"{feed_id}|{guid}".encode()).hexdigest()[:12]


def _duration(entry) -> int | None:
    raw = entry.get("itunes_duration") or ""
    if not raw:
        return None
    parts = [p for p in re.split(r":", str(raw)) if p != ""]
    try:
        nums = [int(float(p)) for p in parts]
    except ValueError:
        return None
    secs = 0
    for n in nums:
        secs = secs * 60 + n
    return secs


def _transcript_refs(xml: bytes) -> dict[str, list[dict]]:
    """guid → [{url, type, language}] from <podcast:transcript> tags (feedparser drops them)."""
    out: dict[str, list[dict]] = {}
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return out
    for item in root.iter("item"):
        guid = (item.findtext("guid") or "").strip()
        refs = [{"url": t.get("url"), "type": t.get("type", ""), "language": t.get("language", "")}
                for t in item.findall(f"{PODCAST_NS}transcript") if t.get("url")]
        if guid and refs:
            out[guid] = refs
    return out


def parse(feed: Feed, content: bytes) -> list[dict]:
    parsed = feedparser.parse(content)
    if parsed.bozo and not parsed.entries:
        raise ValueError(f"not a valid feed: {parsed.bozo_exception}")
    refs = _transcript_refs(content)
    out = []
    for e in parsed.entries:
        enc = next((l for l in e.get("links", []) if l.get("rel") == "enclosure" and "audio" in l.get("type", "audio")), None)
        if not enc:
            continue
        guid = e.get("id") or e.get("guid") or enc["href"]
        ts = e.get("published_parsed") or e.get("updated_parsed")
        published = datetime.fromtimestamp(timegm(ts), timezone.utc).isoformat() if ts else ""
        out.append({"id": episode_id(feed.id, guid), "feed_id": feed.id, "guid": guid, "title": e.get("title", "").strip(),
                    "published": published, "audio_url": enc["href"], "duration_sec": _duration(e), "link": e.get("link", ""),
                    "description": re.sub(r"<[^>]+>", "", e.get("summary", ""))[:600], "transcripts": refs.get(guid, [])})
    return out


def poll(feed: Feed, store: Store, client: httpx.Client | None = None, force: bool = False) -> PollResult:
    st = store.feed_state(feed.id)
    if not feed.usable:
        return PollResult(feed.id, "skipped", error="no feed_url" if feed.active else "inactive")
    if not force and st.get("checked_at") and time.time() - st["checked_at"] < config.POLL_MINUTES * 60:
        return PollResult(feed.id, "skipped", latest=st.get("latest_published"))
    headers = {"User-Agent": config.USER_AGENT}
    if st.get("etag"):
        headers["If-None-Match"] = st["etag"]
    if st.get("modified"):
        headers["If-Modified-Since"] = st["modified"]
    own = client is None
    client = client or httpx.Client(follow_redirects=True, timeout=30)
    try:
        r = client.get(feed.feed_url, headers=headers)
        if r.status_code == 304:
            store.set_feed_state(feed.id, checked_at=time.time(), status="not-modified", error=None)
            return PollResult(feed.id, "not-modified", latest=st.get("latest_published"))
        r.raise_for_status()
        episodes = parse(feed, r.content)
        new = sum(store.upsert_episode(ep) for ep in episodes)
        latest = max((e["published"] for e in episodes if e["published"]), default=None)
        store.set_feed_state(feed.id, etag=r.headers.get("etag"), modified=r.headers.get("last-modified"),
                             checked_at=time.time(), status="updated", latest_published=latest, error=None)
        return PollResult(feed.id, "updated", new=new, latest=latest)
    except (httpx.HTTPError, ValueError) as exc:
        store.set_feed_state(feed.id, checked_at=time.time(), status="error", error=str(exc)[:200])
        return PollResult(feed.id, "error", error=str(exc)[:200])
    finally:
        if own:
            client.close()
