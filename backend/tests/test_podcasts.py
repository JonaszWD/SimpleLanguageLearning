import json
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.podcasts import audio, chunks, cli, config, fetcher, planner, prepare, questions, registry, resolve, transcripts
from app.podcasts.store import Store


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "FEEDS_FILE", tmp_path / "feeds.yaml")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "data" / "p.sqlite")
    monkeypatch.setattr(config, "AUDIO_DIR", tmp_path / "data" / "audio")
    monkeypatch.setattr(config, "TRANSCRIPT_DIR", tmp_path / "data" / "transcripts")
    monkeypatch.setattr(config, "CLIP_DIR", tmp_path / "data" / "clips")
    monkeypatch.setattr(questions, "CACHE", tmp_path / "q")
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)     # never touch the real key in tests
    config.ensure_dirs()
    return tmp_path


def feed(**kw):
    base = dict(id="show", title="Show", feed_url="https://x.test/rss", level="B1")
    return registry.Feed(**{**base, **kw})


RSS = """<?xml version="1.0"?><rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
 xmlns:podcast="https://podcastindex.org/namespace/1.0"><channel><title>T</title>
 <item><title>Ep 2</title><guid>g2</guid><pubDate>Fri, 30 Oct 2026 08:00:00 +0000</pubDate><itunes:duration>00:12:30</itunes:duration>
  <enclosure url="https://x.test/2.mp3" type="audio/mpeg" length="1"/>
  <podcast:transcript url="https://x.test/2.srt" type="application/x-subrip"/></item>
 <item><title>Ep 1</title><guid>g1</guid><pubDate>Fri, 23 Oct 2026 08:00:00 +0000</pubDate><itunes:duration>754</itunes:duration>
  <enclosure url="https://x.test/1.mp3" type="audio/mpeg" length="1"/></item></channel></rss>"""


# ── registry ────────────────────────────────────────────────────────────────
def test_registry_roundtrip_and_validation(env):
    registry.save([feed(), feed(id="other", title="Other", feed_url="")])
    got = registry.load()
    assert [f.id for f in got] == ["show", "other"] and got[1].usable is False and got[0].usable
    with pytest.raises(ValueError):
        feed(id="Bad Id")
    with pytest.raises(ValueError):
        feed(feed_url="ftp://nope")
    registry.save([feed(), feed()])
    with pytest.raises(ValueError, match="duplicate"):
        registry.load()


def test_feed_url_is_never_invented(env):
    registry.save([feed(feed_url="")])
    assert registry.load()[0].feed_url == ""


# ── resolve ─────────────────────────────────────────────────────────────────
def itunes_client(payload):
    return httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload)))


def test_itunes_candidates_skip_results_without_feed(env, monkeypatch):
    monkeypatch.delenv("PODCASTINDEX_API_KEY", raising=False)
    c = itunes_client({"results": [{"collectionName": "A", "artistName": "x", "feedUrl": "https://a/rss", "country": "ESP"},
                                   {"collectionName": "B", "artistName": "y"}]})
    got = resolve.candidates("a", client=c)
    assert [g.feed_url for g in got] == ["https://a/rss"]


def test_podcastindex_needs_keys_and_signs_requests(monkeypatch):
    assert resolve.search_podcastindex("x") == []
    monkeypatch.setenv("PODCASTINDEX_API_KEY", "k")
    monkeypatch.setenv("PODCASTINDEX_API_SECRET", "s")
    seen = {}

    def handler(r):
        seen.update(r.headers)
        return httpx.Response(200, json={"feeds": [{"title": "T", "url": "https://t/rss", "author": "me"}]})
    got = resolve.search_podcastindex("x", client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert got[0].source == "podcastindex" and seen["x-auth-key"] == "k" and len(seen["authorization"]) == 40


def run_resolve(env, answers, found):
    registry.save([feed(feed_url="")])
    it = iter(answers)
    ns = cli.build_parser().parse_args(["feeds", "resolve", "Show"])
    rc = cli.cmd_resolve(ns, input_fn=lambda _p: next(it), search=lambda *a: found,
                         client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=RSS))))
    return rc, registry.load()[0].feed_url


CAND = [resolve.Candidate("Show", "me", "https://x.test/rss", "ESP", "itunes"), resolve.Candidate("Show 2", "me", "https://y.test/rss", "ESP", "itunes")]


def test_resolve_saves_only_after_confirmation(env):
    assert run_resolve(env, ["2", "n"], CAND) == (1, "")          # refused
    assert run_resolve(env, ["", ], CAND) == (1, "")              # cancelled at the choice
    assert run_resolve(env, ["9"], CAND) == (1, "")               # not a valid number
    rc, url = run_resolve(env, ["2", "y"], CAND)
    assert url == "https://y.test/rss"


def test_resolve_unknown_show_is_not_guessed(env):
    registry.save([feed(feed_url="")])
    ns = cli.build_parser().parse_args(["feeds", "resolve", "Nonexistent"])
    assert cli.cmd_resolve(ns, input_fn=lambda _p: "1", search=lambda *a: CAND) == 1


# ── fetching ────────────────────────────────────────────────────────────────
def test_parse_episodes_durations_and_transcript_tags(env):
    eps = fetcher.parse(feed(), RSS.encode())
    by = {e["guid"]: e for e in eps}
    assert by["g2"]["duration_sec"] == 750 and by["g1"]["duration_sec"] == 754
    assert by["g2"]["transcripts"][0]["url"] == "https://x.test/2.srt" and by["g1"]["transcripts"] == []
    assert by["g2"]["id"] == fetcher.episode_id("show", "g2")


def test_poll_uses_etag_and_respects_interval(env):
    calls = []

    def handler(r):
        calls.append(dict(r.headers))
        if r.headers.get("if-none-match") == '"v1"':
            return httpx.Response(304)
        return httpx.Response(200, content=RSS.encode(), headers={"etag": '"v1"'})
    c = httpx.Client(transport=httpx.MockTransport(handler))
    s, f = Store(), feed()
    first = fetcher.poll(f, s, c)
    assert (first.status, first.new) == ("updated", 2) and first.latest.startswith("2026-10-30")
    assert fetcher.poll(f, s, c).status == "skipped" and len(calls) == 1             # polling interval
    again = fetcher.poll(f, s, c, force=True)
    assert again.status == "not-modified" and calls[1]["if-none-match"] == '"v1"'    # conditional GET
    assert fetcher.poll(feed(feed_url=""), s, c).status == "skipped"


def test_poll_reports_dead_feeds(env):
    c = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    res = fetcher.poll(feed(), Store(), c, force=True)
    assert res.status == "error" and Store().feed_state("show")["status"] == "error"


def test_validate_flags_dead_and_unresolved(env, capsys):
    registry.save([feed(), feed(id="dead", title="Dead", feed_url="https://dead.test/rss"), feed(id="new", title="New", feed_url="")])
    c = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404) if "dead" in str(r.url) else httpx.Response(200, text=RSS)))
    assert cli.cmd_validate(None, client=c) == 1
    out = capsys.readouterr().out
    assert "ok show" in out and "DEAD dead" in out and "not resolved yet" in out


# ── audio + cache ───────────────────────────────────────────────────────────
def seed_episode(s, ep_id="e1", feed_id="show", published="2026-10-30T00:00:00+00:00", **kw):
    s.upsert_episode({"id": ep_id, "feed_id": feed_id, "guid": ep_id, "title": ep_id, "published": published,
                      "audio_url": f"https://x.test/{ep_id}.mp3", "duration_sec": 600, **kw})
    return s.episode(ep_id)


def test_download_streams_to_disk_and_caps_size(env, monkeypatch):
    s = Store()
    ep = seed_episode(s)
    ok = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"ID3" + b"\0" * 5000)))
    path = audio.download(ep, s, ok)
    assert path.exists() and s.episode("e1")["audio_bytes"] > 0
    monkeypatch.setattr(config, "MAX_AUDIO_MB", 0)
    ep2 = seed_episode(s, "e2")
    with pytest.raises(audio.AudioError):
        audio.download(ep2, s, ok)
    assert not list(config.AUDIO_DIR.glob("e2*")) and s.episode("e2")["status"] == "error"


def test_cleanup_removes_old_listened_then_lru_and_keeps_planned(env):
    s = Store()
    now = time.time()
    for i, (ep_id, listened, accessed) in enumerate([("old", now - 30 * 86400, now - 30 * 86400), ("recent", now - 86400, now - 86400),
                                                      ("unheard", None, now - 5 * 86400), ("planned", None, now - 99 * 86400)]):
        seed_episode(s, ep_id)
        p = config.AUDIO_DIR / f"{ep_id}.mp3"
        p.write_bytes(b"x" * 1_000_000)
        s.update_episode(ep_id, audio_path=str(p), audio_bytes=1_000_000, listened_at=listened, accessed_at=accessed)
    s.save_plan("2026-11-02", [{"mode": "extensive", "episode": "planned", "why": []}])
    r = audio.cleanup(s, max_mb=100, keep_days=14, now=now)
    assert r["removed"] == ["old"]                                  # listened > 14 days ago
    r = audio.cleanup(s, max_mb=1, keep_days=14, now=now)           # 3 files left, cap is 1 MB
    assert set(r["removed"]) == {"recent", "unheard"} and (config.AUDIO_DIR / "planned.mp3").exists()   # planned is safe


# ── transcripts ─────────────────────────────────────────────────────────────
SRT = """1
00:00:01,000 --> 00:00:03,500
Hola a todos,

2
00:00:03,600 --> 00:00:06,000
bienvenidos al programa.

3
00:00:07,000 --> 00:00:09,000
¿Cómo estáis hoy?
"""
VTT = "WEBVTT\n\n00:01.000 --> 00:03.000\nHola <v Ana>amigos.\n\n00:03.500 --> 00:05.000\nQué tal.\n"


def test_srt_and_vtt_become_timed_sentences():
    s = transcripts.sentences_from_cues(transcripts.parse_cues(SRT))
    assert [x["text"] for x in s] == ["Hola a todos, bienvenidos al programa.", "¿Cómo estáis hoy?"]
    assert (s[0]["start"], s[0]["end"]) == (1.0, 6.0)
    v = transcripts.sentences_from_cues(transcripts.parse_cues(VTT))
    assert v[0]["text"] == "Hola amigos." and v[0]["start"] == 1.0


def test_podcasting20_json_and_plain_text():
    cues = transcripts.parse_podcast_json({"segments": [{"startTime": 0, "endTime": 2.5, "body": "Hola."}, {"startTime": 3, "endTime": 4, "body": "  "}]})
    assert cues == [{"start": 0.0, "end": 2.5, "text": "Hola."}]
    plain = transcripts.sentences_from_plain("<p>Primera frase. ¿Segunda frase? Tercera</p>")
    assert [p["text"] for p in plain] == ["Primera frase.", "¿Segunda frase?", "Tercera"] and plain[0]["start"] is None


def test_whisper_words_split_on_punctuation_and_pauses():
    words = [{"word": " Hola", "start": 0.0, "end": 0.4}, {"word": " amigos.", "start": 0.4, "end": 1.0},
             {"word": " Qué", "start": 1.2, "end": 1.4}, {"word": " tal", "start": 1.4, "end": 1.8},
             {"word": " bien", "start": 5.0, "end": 5.4}]           # 3.2 s pause = new sentence
    s = transcripts.sentences_from_words(words)
    assert [x["text"] for x in s] == ["Hola amigos.", "Qué tal", "bien"]


def srt_client(body=SRT, status=200):
    return httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(status, text=body)))


def test_priority_publisher_then_whisper_then_none(env):
    s = Store()
    ep = seed_episode(s, transcripts=[{"url": "https://x.test/t.srt", "type": "application/x-subrip", "language": "es"}])
    called = []
    fake = lambda path: (called.append(path), transcripts.Transcript("whisper", True, [{"i": 0, "start": 0, "end": 1, "text": "x"}], model="tiny"))[1]
    got = transcripts.ensure(ep, s, Path("a.mp3"), client=srt_client(), whisper=fake)
    assert got["source"] == "publisher" and got["timed"] and not called              # Whisper not used
    # no publisher transcript → Whisper, with the warning attached
    ep2 = seed_episode(s, "e2")
    got2 = transcripts.ensure(ep2, s, Path("a.mp3"), whisper=fake)
    assert got2["source"] == "whisper" and "errors" in got2["warning"]
    # nothing available at all
    ep3 = seed_episode(s, "e3")
    assert transcripts.ensure(ep3, s, None) is None and s.episode("e3")["transcript_source"] == "none"


def test_untimed_publisher_text_falls_back_to_whisper_for_timestamps(env):
    s = Store()
    ep = seed_episode(s, transcripts=[{"url": "https://x.test/t.txt", "type": "text/plain", "language": "es"}])
    fake = lambda path: transcripts.Transcript("whisper", True, [{"i": 0, "start": 0, "end": 1, "text": "x"}])
    assert transcripts.ensure(ep, s, Path("a.mp3"), client=srt_client("Una frase. Otra."), whisper=fake)["source"] == "whisper"


def test_whisper_failure_keeps_publisher_text_and_records_error(env):
    s = Store()
    ep = seed_episode(s, transcripts=[{"url": "https://x.test/t.txt", "type": "text/plain", "language": "es"}])
    def boom(path): raise RuntimeError("no model")
    got = transcripts.ensure(ep, s, Path("a.mp3"), client=srt_client("Una frase. Otra."), whisper=boom)
    assert got["source"] == "publisher" and got["timed"] is False and "whisper: no model" in s.episode(ep["id"])["error"]


# ── chunks ──────────────────────────────────────────────────────────────────
def episode_sentences(total_s, sentence_s=7.0, pause_every=20, pause_s=3.0):
    out, t, i = [], 0.0, 0
    while t < total_s:
        out.append({"i": i, "start": round(t, 2), "end": round(t + sentence_s, 2), "text": f"Frase {i}."})
        t += sentence_s + (pause_s if i % pause_every == pause_every - 1 else 0.4)
        i += 1
    return out


def test_chunks_are_5_to_10_minutes_and_cut_between_sentences():
    sents = episode_sentences(2400)
    cs = chunks.chunk(sents)
    assert len(cs) >= 4
    for c in cs[:-1]:
        assert 300 <= c["end"] - c["start"] <= 600
    for a, b in zip(cs, cs[1:]):
        assert b["first"] == a["last"] + 1                                   # contiguous: nothing cut mid-sentence or skipped
        assert sents[b["first"]]["start"] >= sents[a["last"]]["end"]
    assert cs[0]["first"] == 0 and cs[-1]["last"] == len(sents) - 1


def test_chunks_prefer_the_longest_pause():
    sents = episode_sentences(1500)
    c = chunks.chunk(sents)[0]
    gap = sents[c["last"] + 1]["start"] - sents[c["last"]]["end"]
    assert gap >= 3.0                                                         # the cut sits on a real pause


def test_short_episode_is_one_chunk_and_untimed_has_none():
    assert len(chunks.chunk(episode_sentences(400))) == 1
    assert chunks.chunk([{"i": 0, "start": None, "end": None, "text": "x"}]) == []
    tail = chunks.chunk(episode_sentences(640))
    assert len(tail) == 1 or tail[-1]["end"] - tail[-1]["start"] >= 150      # no tiny leftover chunk


# ── planner ─────────────────────────────────────────────────────────────────
def planner_env(env, **extra):
    s = Store()
    feeds = [feed(id="easy", title="Easy", level="A2", has_official_transcript=True), feed(id="mid", title="Mid", level="B1"),
             feed(id="native", title="Native", level="C1", accent="Spain"), feed(id="hard", title="Hard", level="B2")]
    for f in feeds:
        for n in range(3):
            seed_episode(s, f"{f.id}{n}", f.id, f"2026-10-{20 + n}T00:00:00+00:00", duration_sec=900)
    return s, feeds


START = date(2026, 11, 2)   # a Monday


def test_stage_weights_follow_the_programme(env):
    s, feeds = planner_env(env)
    early = planner.plan_for(s, feeds, date(2026, 11, 2), START, save=False)
    late = planner.plan_for(s, feeds, date(2027, 6, 7), START, save=False)         # month 8, a Monday
    assert early["items"][0]["level"] in ("A2", "B1") and "Months 1–3" in early["stage"]
    assert late["items"][0]["level"] in ("B2", "C1") and "mostly native" in late["stage"]


def test_weekday_mapping_and_explanations(env):
    s, feeds = planner_env(env)
    assert planner.plan_for(s, feeds, date(2026, 11, 3), START, save=False)["mode"] == "intensive"   # Tuesday
    assert planner.plan_for(s, feeds, date(2026, 11, 7), START, save=False)["items"] == []           # Saturday: none
    custom = planner.parse_map("1:i,2:e")
    assert planner.plan_for(s, feeds, date(2026, 11, 2), START, custom, save=False)["mode"] == "intensive"
    p = planner.plan_for(s, feeds, date(2026, 11, 2), START, save=False)
    assert all(i["why"] and any("weighted" in w for w in i["why"]) for i in p["items"])
    assert sum(i["minutes"] for i in p["items"]) >= 30                                              # extensive fills ~30 min


def test_planner_is_deterministic(env):
    s, feeds = planner_env(env)
    a = planner.plan_for(s, feeds, date(2026, 11, 2), START, save=False)
    b = planner.plan_for(s, feeds, date(2026, 11, 2), START, save=False)
    assert a == b


def test_ratings_shift_the_level_mix(env):
    s, feeds = planner_env(env)
    day = date(2027, 3, 15)                      # month 5: B2 is the favourite
    base = planner.plan_for(s, feeds, day, START, save=False)
    assert base["items"][0]["level"] == "B2"
    for i in range(3):
        s.add_rating(f"hard{i}", "hard", "B2", "too hard")
    shifted = planner.plan_for(s, feeds, day, START, save=False)
    assert shifted["items"][0]["level"] != "B2" and any("too hard" in n for n in shifted["notes"])


def test_disliked_and_unfinished_shows_are_avoided(env):
    s, feeds = planner_env(env)
    day = date(2026, 11, 2)
    for i in range(2):
        s.add_rating(f"mid{i}", "mid", "B1", "too hard")
    p = planner.plan_for(s, feeds, day, START, save=False)
    assert "mid" not in {i["feed"] for i in p["items"]} and any("too hard" in x for x in p["skipped"])
    # unfinished: planned on past days, never listened
    s2, feeds2 = planner_env(env)
    recent = (date.today() - timedelta(days=3)).isoformat()
    s2.save_plan(recent, [{"mode": "extensive", "episode": "easy0", "why": []}, {"mode": "extensive", "episode": "easy1", "why": []}])
    p2 = planner.plan_for(s2, feeds2, date(2026, 11, 2), START, save=False)
    assert "easy" not in {i["feed"] for i in p2["items"]} and any("unfinished" in x for x in p2["skipped"])
    s2.update_episode("easy0", listened_at=time.time())          # finishing one of them clears the flag
    s2.update_episode("easy1", listened_at=time.time())
    assert "easy" in {i["feed"] for i in planner.plan_for(s2, feeds2, date(2026, 11, 2), START, save=False)["items"]}


def test_intensive_prefers_official_transcripts(env, monkeypatch):
    s, feeds = planner_env(env)
    p = planner.plan_for(s, feeds, date(2026, 11, 3), START, save=False, whisper_ok=False)
    assert p["items"][0]["feed"] == "easy" and "official transcript" in p["items"][0]["why"]


# ── questions (Claude, faked) ───────────────────────────────────────────────
class FakeClaude:
    calls = 0

    class messages:  # noqa: N801
        @staticmethod
        def create(**kw):
            FakeClaude.calls += 1
            q = {"question": "¿De qué habla?", "options": ["a", "b", "c"], "correct": 1, "explanation": "Dice b."}

            class B:
                type = "tool_use"
                input = {"questions": [q, q, q]}
            return type("M", (), {"content": [B]})


def test_questions_are_cached_marked_llm_and_need_no_key_for_dry_run(env, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert questions.generate("texto", dry_run=True) is None
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        questions.generate("texto")
    FakeClaude.calls = 0
    a = questions.generate("texto", client=FakeClaude)
    b = questions.generate("texto", client=FakeClaude)
    assert FakeClaude.calls == 1 and b["cached"] and a["source"] == "llm" and all(q["source"] == "llm" for q in a["questions"])


# ── API ─────────────────────────────────────────────────────────────────────
@pytest.fixture
def api(env, monkeypatch):
    from app.main import app
    registry.save([feed(), feed(id="mid", title="Mid", level="B1")])
    s = Store()
    for n in range(3):
        seed_episode(s, f"show{n}", "show", f"2026-10-2{n}T00:00:00+00:00")
    monkeypatch.setattr(audio, "download", lambda ep, store, client=None: _fake_audio(ep, store))
    return TestClient(app), s


def _fake_audio(ep, store):
    p = config.AUDIO_DIR / f"{ep['id']}.mp3"
    p.write_bytes(b"ID3" + bytes(range(256)) * 40)
    store.update_episode(ep["id"], audio_path=str(p), audio_bytes=p.stat().st_size, status="audio")
    return p


def test_api_plan_prepare_audio_transcript_and_state(api, monkeypatch):
    client, s = api
    monkeypatch.setattr(transcripts, "whisper_available", lambda: False)
    plan = client.get("/api/podcasts/plan", params={"date": "2026-11-02", "start": "2026-11-02"}).json()
    assert plan["mode"] == "extensive" and plan["items"] and plan["offline"]["all_ready"] is False
    ids = [i["episode"] for i in plan["items"]]
    assert client.post("/api/podcasts/prepare", json={"episodes": ids}).status_code == 202   # background task runs inside TestClient
    plan2 = client.get("/api/podcasts/plan", params={"date": "2026-11-02", "start": "2026-11-02"}).json()
    assert plan2["offline"]["all_ready"] is True and all(i["ready"] for i in plan2["items"])
    # audio with Range support (the app downloads it, and can resume)
    full = client.get(f"/api/podcasts/episodes/{ids[0]}/audio")
    part = client.get(f"/api/podcasts/episodes/{ids[0]}/audio", headers={"Range": "bytes=0-9"})
    assert full.status_code == 200 and part.status_code == 206 and len(part.content) == 10
    assert client.get("/api/podcasts/episodes/nope/audio").status_code == 404
    assert client.get(f"/api/podcasts/episodes/{ids[0]}/transcript").status_code == 404        # none yet
    assert client.get("/api/podcasts/status").json()["cached_episodes"] >= 1


def test_api_ratings_and_listened_feed_back_into_the_planner(api):
    client, s = api
    ep = s.episodes("show")[0]["id"]
    assert client.post("/api/podcasts/ratings", json={"episode": ep, "rating": "meh"}).status_code == 422
    assert client.post("/api/podcasts/ratings", json={"episode": ep, "rating": "too hard"}).status_code == 200
    assert s.ratings()[0]["rating"] == "too hard" and s.ratings()[0]["level"] == "B1"
    assert client.post("/api/podcasts/listened", json={"episode": ep}).status_code == 200
    assert s.episode(ep)["listened_at"]


def test_api_questions_need_a_transcript_and_a_key(api, monkeypatch):
    client, s = api
    ep = s.episodes("show")[0]["id"]
    config.TRANSCRIPT_DIR.mkdir(exist_ok=True, parents=True)
    (config.TRANSCRIPT_DIR / f"{ep}.json").write_text(json.dumps({"source": "publisher", "timed": True, "sentences": episode_sentences(400)}))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = client.get(f"/api/podcasts/episodes/{ep}/questions")
    assert r.status_code == 503 and "ANTHROPIC_API_KEY" in r.json()["detail"]
    tr = client.get(f"/api/podcasts/episodes/{ep}/transcript").json()
    assert tr["chunks"] and tr["source"] == "publisher"


# ── ElevenLabs Scribe ───────────────────────────────────────────────────────
SCRIBE = {"language_code": "spa", "words": [
    {"text": "Hola", "start": 0.0, "end": 0.4, "type": "word", "speaker_id": "speaker_0"},
    {"text": " ", "start": 0.4, "end": 0.5, "type": "spacing", "speaker_id": "speaker_0"},
    {"text": "amigos.", "start": 0.5, "end": 1.0, "type": "word", "speaker_id": "speaker_0"},
    {"text": "(risas)", "start": 1.0, "end": 1.4, "type": "audio_event", "speaker_id": "speaker_1"},
    {"text": "¿Qué", "start": 1.5, "end": 1.8, "type": "word", "speaker_id": "speaker_1"},
    {"text": "tal?", "start": 1.8, "end": 2.2, "type": "word", "speaker_id": "speaker_1"},
    {"text": "Bien", "start": 2.3, "end": 2.6, "type": "word", "speaker_id": "speaker_0"},
    {"text": "gracias", "start": 2.6, "end": 3.0, "type": "word", "speaker_id": "speaker_0"},
]}


def test_scribe_words_become_timed_sentences_with_speakers():
    s = transcripts.sentences_from_words(transcripts.words_from_scribe(SCRIBE))
    assert [x["text"] for x in s] == ["Hola amigos.", "¿Qué tal?", "Bien gracias"]
    assert [x["speaker"] for x in s] == ["A", "B", "A"]
    assert s[1]["start"] == 1.5 and s[1]["end"] == 2.2


def test_elevenlabs_request_and_priority(env, monkeypatch, tmp_path):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    seen = {}

    def handler(req):
        seen["key"] = req.headers["xi-api-key"]
        seen["body"] = req.content
        return httpx.Response(200, json=SCRIBE)

    audio_file = tmp_path / "a.mp3"
    audio_file.write_bytes(b"x")
    tr = transcripts.elevenlabs_transcribe(audio_file, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert seen["key"] == "k" and b"diarize" in seen["body"] and b'name="language_code"' in seen["body"]
    assert tr.source == "elevenlabs" and tr.timed and tr.to_json()["warning"].startswith("Automatic (ElevenLabs)")

    s = Store()
    ep = seed_episode(s, "show0", "show", "2026-10-20T00:00:00+00:00")
    boom = lambda path: (_ for _ in ()).throw(AssertionError("whisper must not run when ElevenLabs works"))
    got = transcripts.ensure(ep, s, audio_file, scribe=lambda p: tr, whisper=boom)
    assert got["source"] == "elevenlabs"


def test_elevenlabs_failure_falls_back_to_whisper(env, monkeypatch, tmp_path):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    s = Store()
    ep = seed_episode(s, "show0", "show", "2026-10-20T00:00:00+00:00")
    fake = lambda path: transcripts.Transcript("whisper", True, [{"i": 0, "start": 0, "end": 1, "text": "x"}])

    def bad(path):
        raise RuntimeError("quota")
    got = transcripts.ensure(ep, s, tmp_path / "a.mp3", scribe=bad, whisper=fake)
    assert got["source"] == "whisper"


def test_episode_list_endpoint_shows_transcript_state(api):
    client, s = api
    r = client.get("/api/podcasts/episodes?limit=2")
    assert r.status_code == 200
    rows = r.json()
    assert rows and {"id", "show", "level", "transcript", "ready"} <= set(rows[0])
    assert all(len([x for x in rows if x["feed"] == f]) <= 2 for f in {x["feed"] for x in rows})
