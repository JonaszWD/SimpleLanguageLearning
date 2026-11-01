"""Split an episode into 5-10 minute segments for intensive listening, cutting at sentence ends."""

MIN_S, MAX_S = 300.0, 600.0


def chunk(sentences: list[dict], min_s: float = MIN_S, max_s: float = MAX_S) -> list[dict]:
    """Cut after at least `min_s` and before `max_s`, at the longest pause between sentences in
    that window (so never mid-sentence). The final remainder is merged into the previous chunk if short."""
    timed = [s for s in sentences if s.get("start") is not None]
    if not timed:
        return []
    chunks, first = [], 0
    n = len(timed)
    while first < n:
        t0 = timed[first]["start"]
        window = [i for i in range(first, n) if timed[i]["end"] - t0 >= min_s and timed[i]["end"] - t0 <= max_s]
        if timed[-1]["end"] - t0 <= max_s:          # the rest fits in one chunk
            last = n - 1
        elif window:
            # cut after sentence i; prefer the longest silence before the next sentence, and leave a
            # remainder worth a chunk of its own (so 10.5 minutes becomes 2 x ~5, not one 10.5)
            gap = lambda i: (timed[i + 1]["start"] - timed[i]["end"]) if i + 1 < n else 0
            roomy = [i for i in window if timed[-1]["end"] - timed[i]["end"] >= min_s / 2] or window
            last = max(roomy, key=lambda i: (round(gap(i), 2), -i))
        else:                                       # one very long sentence: cut at the first sentence end past max
            last = next((i for i in range(first, n) if timed[i]["end"] - t0 > max_s), n - 1)
        chunks.append({"first": first, "last": last})
        first = last + 1
    if len(chunks) > 1 and timed[chunks[-1]["last"]]["end"] - timed[chunks[-1]["first"]]["start"] < min_s / 2:
        tail = chunks.pop()                         # a tiny remainder joins the previous chunk
        chunks[-1]["last"] = tail["last"]
    return [{"index": k, "first": c["first"], "last": c["last"], "start": timed[c["first"]]["start"],
             "end": timed[c["last"]]["end"], "sentences": c["last"] - c["first"] + 1} for k, c in enumerate(chunks)]
