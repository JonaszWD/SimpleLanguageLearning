"""Command line: feeds, polling, planning and preparing episodes.

    uv run python -m app.podcasts feeds list
    uv run python -m app.podcasts feeds add hoy-hablamos --title "Hoy Hablamos" --level A2 --accent Spain
    uv run python -m app.podcasts feeds resolve "Hoy Hablamos"      # shows candidates, saves only after you confirm
    uv run python -m app.podcasts feeds validate
    uv run python -m app.podcasts poll | plan | prepare | cleanup | transcribe <episode-id>
"""

import argparse
import sys
from datetime import date as Date
from datetime import datetime, timedelta, timezone

import httpx

from . import audio, config, fetcher, planner, prepare, registry, resolve, transcripts
from .store import Store


def _confirm(prompt: str, input_fn=input) -> bool:
    return input_fn(f"{prompt} [y/N] ").strip().lower() in ("y", "yes")


def cmd_list(_a) -> int:
    feeds = registry.load()
    if not feeds:
        print(f"No feeds yet. Add one with `feeds add`, or edit {config.FEEDS_FILE}")
    for f in feeds:
        flag = "on " if f.active else "off"
        print(f"{flag} {f.id:<24} {f.level}  {f.accent:<14} {f.mode:<9} {'transcript' if f.has_official_transcript else '-':<10} "
              f"{f.feed_url or '(feed_url not resolved)'}")
    return 0


def cmd_add(a) -> int:
    feeds = registry.load()
    if any(f.id == a.id for f in feeds):
        print(f"{a.id} already exists")
        return 1
    feeds.append(registry.Feed(id=a.id, title=a.title, level=a.level, accent=a.accent, mode=a.mode,
                               has_official_transcript=a.transcript, episode_length_min=a.length, notes=a.notes))
    registry.save(feeds)
    print(f"added {a.id} (feed_url empty: run `feeds resolve \"{a.title}\"`)")
    return 0


def cmd_resolve(a, input_fn=input, search=resolve.candidates, client=None) -> int:
    feeds = registry.load()
    needle = a.name.lower()
    target = next((f for f in feeds if f.id == a.id), None) if a.id else next(
        (f for f in feeds if needle in f.title.lower() or needle == f.id), None)
    if target is None:
        print(f"'{a.name}' is not in the registry. Add it first: feeds add <id> --title \"{a.name}\" --level B1")
        return 1
    found = search(a.name, a.country)
    if not found:
        print("No candidates found. Try another spelling or --country.")
        return 1
    print(f"Candidates for '{a.name}' (registry entry: {target.id}):\n")
    for i, c in enumerate(found, 1):
        print(f"  {i}. {c.line()}")
    choice = input_fn("\nWhich one is the right show? Number, or Enter to cancel: ").strip()
    if not choice.isdigit() or not 1 <= int(choice) <= len(found):
        print("Nothing saved.")
        return 1
    pick = found[int(choice) - 1]
    if target.feed_url and target.feed_url != pick.feed_url:
        print(f"Note: replaces the current URL {target.feed_url}")
    if not _confirm(f"Save {pick.feed_url} as the feed for '{target.title}'?", input_fn):
        print("Nothing saved.")
        return 1
    registry.set_url(target.id, pick.feed_url)
    print("Saved. Checking it…")
    res = fetcher.poll(registry.get(target.id), Store(), client, force=True)
    print(f"  {res.status}: latest episode {res.latest or 'unknown'}" + (f" ({res.error})" if res.error else ""))
    return 0 if res.status != "error" else 1


def cmd_validate(_a, client=None) -> int:
    feeds = registry.load()
    bad = 0
    own = client is None
    client = client or httpx.Client(follow_redirects=True, timeout=30)
    for f in feeds:
        if not f.feed_url:
            print(f"?  {f.id:<24} not resolved yet")
            continue
        try:
            r = client.get(f.feed_url, headers={"User-Agent": config.USER_AGENT})
            r.raise_for_status()
            eps = fetcher.parse(f, r.content)
            if not eps:
                raise ValueError("parsed, but no audio episodes")
            latest = max(e["published"] for e in eps if e["published"])[:10]
            old = (datetime.now(timezone.utc) - datetime.fromisoformat(max(e["published"] for e in eps if e["published"]))).days
            print(f"ok {f.id:<24} {len(eps):>4} episodes, latest {latest}" + (f"  (stale: {old} days)" if old > 60 else ""))
        except (httpx.HTTPError, ValueError) as exc:
            bad += 1
            print(f"DEAD {f.id:<22} {str(exc)[:90]}")
    if own:
        client.close()
    print(f"\n{len(feeds)} feeds, {bad} dead")
    return 1 if bad else 0


def cmd_poll(a) -> int:
    store = Store()
    for f in registry.load():
        r = fetcher.poll(f, store, force=a.force)
        print(f"{f.id:<24} {r.status:<13} +{r.new} new" + (f"  {r.error}" if r.error else ""))
    return 0


def _start(a) -> Date:
    return Date.fromisoformat(a.start) if a.start else config_start()


def config_start() -> Date:
    f = config.DATA_DIR / "start.txt"
    if f.exists():
        return Date.fromisoformat(f.read_text().strip())
    config.ensure_dirs()
    f.write_text(Date.today().isoformat())
    return Date.today()


def cmd_plan(a) -> int:
    day = Date.fromisoformat(a.date) if a.date else Date.today()
    p = planner.plan_for(Store(), registry.load(), day, _start(a), planner.parse_map(a.map), whisper_ok=transcripts.asr_available())
    print(f"{p['date']}  mode: {p['mode']}  stage: {p['stage']}")
    for n in p["notes"]:
        print("  note:", n)
    for s in p["skipped"]:
        print("  skipped:", s)
    for i in p["items"]:
        print(f"  - [{i['level']}] {i['show']}: {i['title']} ({i['minutes']} min)")
        for w in i["why"]:
            print("      ·", w)
    return 0


def cmd_prepare(a) -> int:
    day = Date.fromisoformat(a.date) if a.date else prepare.tomorrow()
    out = prepare.prepare_date(day, Store(), _start(a), planner.parse_map(a.map), allow_whisper=not a.no_whisper)
    for r in out["prepared"]:
        print(r)
    print(prepare.status(Store(), day))
    return 0


def cmd_cleanup(_a) -> int:
    print(audio.cleanup(Store()))
    return 0


def cmd_transcribe(a) -> int:
    store = Store()
    ep = store.episode(a.episode)
    if not ep:
        print("unknown episode")
        return 1
    path = audio.download(ep, store)
    tr = transcripts.ensure(ep, store, path)
    print(f"{tr['source'] if tr else 'none'}: {len(tr['sentences']) if tr else 0} sentences")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="podcasts", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    feeds = sub.add_parser("feeds").add_subparsers(dest="sub", required=True)
    feeds.add_parser("list").set_defaults(fn=cmd_list)
    ad = feeds.add_parser("add")
    ad.add_argument("id"); ad.add_argument("--title", required=True)
    ad.add_argument("--level", required=True, choices=registry.LEVEL_ORDER)
    ad.add_argument("--accent", default="mixed", choices=["Spain", "Latin America", "mixed"])
    ad.add_argument("--mode", default="both", choices=["extensive", "intensive", "both"])
    ad.add_argument("--transcript", action="store_true", help="the publisher provides an official transcript")
    ad.add_argument("--length", type=int, default=20); ad.add_argument("--notes", default="")
    ad.set_defaults(fn=cmd_add)
    rs = feeds.add_parser("resolve"); rs.add_argument("name"); rs.add_argument("--id"); rs.add_argument("--country")
    rs.set_defaults(fn=cmd_resolve)
    feeds.add_parser("validate").set_defaults(fn=cmd_validate)
    po = sub.add_parser("poll"); po.add_argument("--force", action="store_true"); po.set_defaults(fn=cmd_poll)
    for name, fn in (("plan", cmd_plan), ("prepare", cmd_prepare)):
        sp = sub.add_parser(name); sp.add_argument("--date"); sp.add_argument("--start", help="programme start date (stage)")
        sp.add_argument("--map", help="weekday modes, e.g. 1:e,2:i,3:e,4:i,5:e"); sp.set_defaults(fn=fn)
        if name == "prepare":
            sp.add_argument("--no-whisper", action="store_true")
    sub.add_parser("cleanup").set_defaults(fn=cmd_cleanup)
    tr = sub.add_parser("transcribe"); tr.add_argument("episode"); tr.set_defaults(fn=cmd_transcribe)
    return p


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
