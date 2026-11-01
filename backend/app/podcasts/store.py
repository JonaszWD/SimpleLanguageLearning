"""SQLite state: feed polling info, episodes, ratings and the daily plan."""

import json
import sqlite3
import time
from contextlib import contextmanager

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS feed_state (feed_id TEXT PRIMARY KEY, etag TEXT, modified TEXT, checked_at REAL,
    status TEXT, latest_published TEXT, error TEXT);
CREATE TABLE IF NOT EXISTS episodes (id TEXT PRIMARY KEY, feed_id TEXT, guid TEXT, title TEXT, published TEXT,
    audio_url TEXT, duration_sec INTEGER, link TEXT, description TEXT, transcripts TEXT DEFAULT '[]',
    audio_path TEXT, audio_bytes INTEGER DEFAULT 0, transcript_source TEXT, listened_at REAL, accessed_at REAL,
    status TEXT DEFAULT 'new', error TEXT);
CREATE INDEX IF NOT EXISTS ep_feed ON episodes(feed_id, published);
CREATE TABLE IF NOT EXISTS ratings (ep_id TEXT, feed_id TEXT, level TEXT, rating TEXT, ts REAL);
CREATE TABLE IF NOT EXISTS plan (date TEXT, mode TEXT, ep_id TEXT, why TEXT, PRIMARY KEY (date, ep_id));
"""


class Store:
    def __init__(self, path=None):
        self.path = path or config.DB_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as con:
            con.executescript(SCHEMA)

    @contextmanager
    def db(self):
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()

    # feeds
    def feed_state(self, feed_id: str) -> dict:
        with self.db() as c:
            r = c.execute("SELECT * FROM feed_state WHERE feed_id = ?", (feed_id,)).fetchone()
        return dict(r) if r else {}

    def set_feed_state(self, feed_id: str, **kw) -> None:
        cur = self.feed_state(feed_id)
        cur.update(kw, feed_id=feed_id)
        cols = ["feed_id", "etag", "modified", "checked_at", "status", "latest_published", "error"]
        with self.db() as c:
            c.execute(f"INSERT OR REPLACE INTO feed_state ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                      [cur.get(k) for k in cols])

    # episodes
    def upsert_episode(self, ep: dict) -> bool:
        """Insert a new episode, or refresh metadata of a known one. Returns True if it is new."""
        with self.db() as c:
            known = c.execute("SELECT 1 FROM episodes WHERE id = ?", (ep["id"],)).fetchone()
            if known:
                c.execute("UPDATE episodes SET title=?, audio_url=?, duration_sec=COALESCE(?, duration_sec), link=?, description=?, transcripts=? WHERE id=?",
                          (ep["title"], ep["audio_url"], ep.get("duration_sec"), ep.get("link", ""), ep.get("description", ""),
                           json.dumps(ep.get("transcripts", [])), ep["id"]))
                return False
            c.execute("INSERT INTO episodes (id, feed_id, guid, title, published, audio_url, duration_sec, link, description, transcripts) VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (ep["id"], ep["feed_id"], ep["guid"], ep["title"], ep["published"], ep["audio_url"], ep.get("duration_sec"),
                       ep.get("link", ""), ep.get("description", ""), json.dumps(ep.get("transcripts", []))))
            return True

    def episode(self, ep_id: str) -> dict | None:
        with self.db() as c:
            r = c.execute("SELECT * FROM episodes WHERE id = ?", (ep_id,)).fetchone()
        return self._ep(r) if r else None

    def episodes(self, feed_id: str | None = None, unlistened: bool = False, limit: int = 200) -> list[dict]:
        q, args = "SELECT * FROM episodes WHERE 1=1", []
        if feed_id:
            q += " AND feed_id = ?"
            args.append(feed_id)
        if unlistened:
            q += " AND listened_at IS NULL"
        q += " ORDER BY published DESC LIMIT ?"
        with self.db() as c:
            return [self._ep(r) for r in c.execute(q, [*args, limit])]

    @staticmethod
    def _ep(r) -> dict:
        d = dict(r)
        d["transcripts"] = json.loads(d.get("transcripts") or "[]")
        return d

    def update_episode(self, ep_id: str, **kw) -> None:
        if not kw:
            return
        sets = ", ".join(f"{k} = ?" for k in kw)
        with self.db() as c:
            c.execute(f"UPDATE episodes SET {sets} WHERE id = ?", [*kw.values(), ep_id])

    def touch(self, ep_id: str) -> None:
        self.update_episode(ep_id, accessed_at=time.time())

    # ratings
    def add_rating(self, ep_id: str, feed_id: str, level: str, rating: str, ts: float | None = None) -> None:
        with self.db() as c:
            c.execute("DELETE FROM ratings WHERE ep_id = ?", (ep_id,))
            c.execute("INSERT INTO ratings VALUES (?,?,?,?,?)", (ep_id, feed_id, level, rating, ts or time.time()))

    def ratings(self) -> list[dict]:
        with self.db() as c:
            return [dict(r) for r in c.execute("SELECT * FROM ratings ORDER BY ts")]

    # plan
    def save_plan(self, date: str, items: list[dict]) -> None:
        with self.db() as c:
            c.execute("DELETE FROM plan WHERE date = ?", (date,))
            c.executemany("INSERT INTO plan VALUES (?,?,?,?)", [(date, i["mode"], i["episode"], json.dumps(i["why"])) for i in items])

    def plan(self, date: str) -> list[dict]:
        with self.db() as c:
            return [{"mode": r["mode"], "episode": r["ep_id"], "why": json.loads(r["why"])}
                    for r in c.execute("SELECT * FROM plan WHERE date = ?", (date,))]

    def planned_ids(self) -> set[str]:
        with self.db() as c:
            return {r["ep_id"] for r in c.execute("SELECT ep_id FROM plan")}
