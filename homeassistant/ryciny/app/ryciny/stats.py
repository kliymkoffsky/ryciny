"""Statistics for the panel, the app and the public page: one place, so all three show the same numbers.

The chance of hearing a bird comes from the history of whole days: for each species, on how many of the days
the add-on was listening it was heard at all, and in each hour of the day. "Now" is the current hour's share.
"""

from __future__ import annotations

from .store import local, now_ms

CHANCE_DAYS = 30
TOP = 12


def compute(journal: dict, history: dict, sounds: dict, sound_on, private: set[str] = frozenset()) -> dict:
    now = now_ms()
    t = local(now)
    today = t.strftime("%Y-%m-%d")
    day_start = int(t.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
    week = now - 7 * 86_400_000

    # Birds: from the history (longer than the journal), by day.
    days = sorted(history)
    last = lambda n: [d for d in days if d > local(now - n * 86_400_000).strftime("%Y-%m-%d")]  # noqa: E731
    species = lambda ds: {s for d in ds for s in history[d]}  # noqa: E731
    names = {s: b["n"] for d in days for s, b in history[d].items()}
    # Average BirdNET confidence per species over the last 30 days (every detection, not just the best ones).
    sums: dict[str, list[float]] = {}
    for d in last(30):
        for s, b in history[d].items():
            if "c" in b:
                acc = sums.setdefault(s, [0.0, 0])
                acc[0] += b["c"]
                acc[1] += sum(b["h"])
    conf = {s: round(c / n, 3) for s, (c, n) in sums.items() if n}
    week_days = last(7)
    top: dict[str, int] = {}
    hours = [0] * 24
    for d in week_days:
        for s, b in history[d].items():
            top[s] = top.get(s, 0) + sum(b["h"])
            hours = [a + c for a, c in zip(hours, b["h"])]

    # Chance: whole days only (today is not over yet), unless today is all there is.
    past = [d for d in last(CHANCE_DAYS) if d != today] or [d for d in days if d == today]
    n = len(past)
    chance = []
    for s in species(past):
        heard = [history[d][s]["h"] for d in past if s in history[d]]
        by_hour = [round(sum(1 for h in heard if h[i] > 0) / n, 3) for i in range(24)]
        best = max(range(24), key=lambda i: by_hour[i])
        chance.append({"sci": s, "name": names.get(s, s), "day": round(len(heard) / n, 3), "hours": by_hour,
                       "now": by_hour[t.hour], "bestHour": best, "conf": conf.get(s)})

    planes = [p for p in journal["planes"] if p.get("heard")]
    shown = [e for e in journal["sounds"] if e["key"] in sounds and e["key"] not in private and sound_on(e["key"])]
    return {
        "updatedAt": now,
        "hour": t.hour,
        "daysObserved": n,
        "birds": {
            "today": len(history.get(today, {})),
            "week": len(species(week_days)),
            "month": len(species(last(30))),
            "top": [{"sci": s, "name": names.get(s, s), "count": c, "conf": conf.get(s)} for s, c in sorted(top.items(), key=lambda x: -x[1])[:TOP]],
            "confidence": [{"sci": s, "name": names.get(s, s), "conf": c, "count": sums[s][1]}
                           for s, c in sorted(conf.items(), key=lambda x: -x[1])],
            "hours": hours,
            "chanceNow": sorted((c for c in chance if c["now"] > 0), key=lambda c: -c["now"])[:TOP],
            "chanceDay": sorted(chance, key=lambda c: -c["day"])[:30],
        },
        "planes": {
            "today": sum(1 for p in planes if p["at"] >= day_start),
            "week": sum(1 for p in planes if p["at"] >= week),
            "airlinesToday": len({p["airline"] for p in planes if p["at"] >= day_start and p["airline"]}),
        },
        "sounds": {
            "kindsToday": len({e["key"] for e in shown if e["lastAt"] >= day_start}),
            "trainsToday": sum(1 for e in shown if e["key"] == "train" and e["lastAt"] >= day_start),
            "week": sum(1 for e in shown if e["lastAt"] >= week),
        },
    }
