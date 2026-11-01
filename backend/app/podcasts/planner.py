"""Level-aware, deterministic and explainable episode selection.

Stage (months since the start date) sets how much of each level is wanted. "Learner" content is
A2-B1 shows, "native" content is B2-C1. Your "too easy / right / too hard" ratings nudge the mix,
and shows you struggle with or leave unfinished are skipped. Every pick says why.
"""

from datetime import date as Date
from datetime import datetime, timedelta, timezone

from . import config
from .registry import LEVEL_ORDER, Feed
from .store import Store

# Level weights per stage: months 1-3 learner, 4-6 a mix, 7+ mostly native.
STAGES = [
    (3, "Months 1–3 · learner content", {"A2": 0.45, "B1": 0.45, "B2": 0.10, "C1": 0.0}),
    (6, "Months 4–6 · a mix of learner and native", {"A2": 0.05, "B1": 0.35, "B2": 0.40, "C1": 0.20}),
    (99, "Months 7–8 · mostly native", {"A2": 0.0, "B1": 0.05, "B2": 0.35, "C1": 0.60}),
]
DEFAULT_MAP = {1: "extensive", 2: "intensive", 3: "extensive", 4: "intensive", 5: "extensive"}   # ISO weekday → mode
EXTENSIVE_TARGET_MIN = 30
RECENT = 5


def months_since(start: Date, today: Date) -> int:
    return max(0, (today - start).days) * 12 // 365 + 1


def stage_for(month: int) -> tuple[str, dict[str, float]]:
    for upto, label, weights in STAGES:
        if month <= upto:
            return label, dict(weights)
    return STAGES[-1][1], dict(STAGES[-1][2])


def parse_map(text: str | None) -> dict[int, str]:
    """'1:e,2:i,3:e' → {1: 'extensive', 2: 'intensive', 3: 'extensive'}; missing days have no listening."""
    if not text:
        return dict(DEFAULT_MAP)
    names = {"e": "extensive", "i": "intensive", "x": "extensive", "n": "none"}
    out = {}
    for part in text.split(","):
        day, _, m = part.partition(":")
        if day.strip().isdigit() and m.strip():
            out[int(day)] = names.get(m.strip()[0].lower(), "none")
    return out


def rating_multipliers(ratings: list[dict]) -> tuple[dict[str, float], list[str]]:
    """'Too hard' at a level lifts the levels below it; 'too easy' lifts those above (caps 0.25-2x)."""
    mult = {l: 1.0 for l in LEVEL_ORDER}
    notes = []
    for level in LEVEL_ORDER:
        recent = [r["rating"] for r in ratings if r["level"] == level][-RECENT:]
        hard, easy = recent.count("too hard"), recent.count("too easy")
        i = LEVEL_ORDER.index(level)
        if hard:
            mult[level] -= 0.25 * hard
            for lower in LEVEL_ORDER[:i]:
                mult[lower] += 0.25 * hard
            notes.append(f"{hard} of your last {len(recent)} {level} episodes were 'too hard', so lower levels are weighted up")
        if easy:
            mult[level] -= 0.15 * easy
            for higher in LEVEL_ORDER[i + 1:]:
                mult[higher] += 0.25 * easy
            notes.append(f"{easy} of your last {len(recent)} {level} episodes were 'too easy', so higher levels are weighted up")
    return {l: min(2.0, max(0.25, m)) for l, m in mult.items()}, notes


def avoided(feed: Feed, ratings: list[dict], store: Store, today: Date) -> str | None:
    last = [r["rating"] for r in ratings if r["feed_id"] == feed.id][-3:]
    if last.count("too hard") >= 2:
        return f"{feed.title}: 2 of your last {len(last)} ratings were 'too hard'"
    today = min(today, Date.today())   # only days that have actually passed can be "unfinished"
    since = (datetime.combine(today, datetime.min.time(), timezone.utc) - timedelta(days=14)).isoformat()
    with store.db() as c:
        # planned on an earlier day, never marked listened → unfinished
        rows = c.execute("""SELECT COUNT(*) FROM plan p JOIN episodes e ON e.id = p.ep_id
                            WHERE e.feed_id = ? AND p.date < ? AND p.date >= ? AND e.listened_at IS NULL""",
                         (feed.id, today.isoformat(), since[:10])).fetchone()[0]
    return f"{feed.title}: {rows} recent episodes left unfinished" if rows >= 2 else None


def duration_min(ep: dict, feed: Feed) -> float:
    return (ep.get("duration_sec") or feed.episode_length_min * 60) / 60


def plan_for(store: Store, feeds: list[Feed], day: Date, start: Date, mode_map: dict[int, str] | None = None,
             target_min: int = EXTENSIVE_TARGET_MIN, whisper_ok: bool = False, save: bool = True) -> dict:
    mode = (mode_map or DEFAULT_MAP).get(day.isoweekday(), "none")
    month = months_since(start, day)
    label, weights = stage_for(month)
    ratings = store.ratings()
    mult, notes = rating_multipliers(ratings)
    result = {"date": day.isoformat(), "mode": mode, "month": month, "stage": label, "weights": weights,
              "notes": notes, "skipped": [], "items": []}
    if mode == "none":
        result["notes"].append("No listening planned for this weekday.")
        return result

    candidates = [f for f in feeds if f.usable and f.mode in (mode, "both")]
    for f in list(candidates):
        why_not = avoided(f, ratings, store, day)
        if why_not:
            result["skipped"].append(why_not)
            candidates.remove(f)
    if not candidates:
        result["notes"].append("No usable feeds: add feed URLs with `feeds resolve`.")
        return result

    planned_recent = store.planned_ids()
    used_feeds: dict[str, int] = {}
    total = 0.0
    need_one = mode == "intensive"
    for _ in range(3):
        best = None
        for f in sorted(candidates, key=lambda f: f.id):
            eps = [e for e in store.episodes(f.id, unlistened=True, limit=30) if e["id"] not in {i["episode"] for i in result["items"]}
                   and (e["id"] not in planned_recent or e["id"] in {p["episode"] for p in store.plan(day.isoformat())})]
            if not eps:
                continue
            ep = eps[0]   # newest first
            base = weights.get(f.level, 0) * mult[f.level]
            if base <= 0:
                nearest = min(LEVEL_ORDER, key=lambda l: (weights[l] <= 0, abs(LEVEL_ORDER.index(l) - LEVEL_ORDER.index(f.level))))
                base = 0.02 / (1 + abs(LEVEL_ORDER.index(f.level) - LEVEL_ORDER.index(nearest)))
            score = base * (0.5 ** used_feeds.get(f.id, 0))
            reasons = [f"{label}: {f.level} weighted {weights.get(f.level, 0):.0%}"]
            if mult[f.level] != 1.0:
                reasons.append(f"adjusted ×{mult[f.level]:.2f} from your ratings")
            if need_one:
                if f.has_official_transcript:
                    score *= 1.5
                    reasons.append("official transcript")
                elif whisper_ok:
                    reasons.append("transcript will be generated automatically (may contain errors)")
                else:
                    score *= 0.2
                    reasons.append("no official transcript and no speech-to-text engine configured")
            if used_feeds.get(f.id):
                reasons.append("same show again, weighted down")
            reasons.append(f"newest unheard episode ({ep['published'][:10]})")
            key = (score, ep["published"], f.id)
            if best is None or key > best[0]:
                best = (key, f, ep, reasons)
        if best is None:
            break
        _, f, ep, reasons = best
        mins = duration_min(ep, f)
        result["items"].append({"mode": mode, "episode": ep["id"], "feed": f.id, "title": ep["title"], "show": f.title,
                                "level": f.level, "accent": f.accent, "minutes": round(mins), "why": reasons})
        used_feeds[f.id] = used_feeds.get(f.id, 0) + 1
        total += mins
        if need_one or total >= target_min:
            break
    if save:
        store.save_plan(day.isoformat(), result["items"])
    return result
