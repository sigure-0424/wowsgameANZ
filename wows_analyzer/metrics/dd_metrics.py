from __future__ import annotations


def compute_dd_metrics(ribbons: list[dict]) -> dict[str, int | float | None]:
    torp_hits = 0
    smoke_deployed = 0

    for r in ribbons:
        event = r.get("event", {})
        text = str(event).lower()
        if "torpedo" in text and "hit" in text:
            torp_hits += 1
        if "smoke" in text:
            smoke_deployed += 1

    return {
        "own_torp_hits": torp_hits,
        "own_spotting_damage": None,
        "own_cap_time_estimate": None,
        "own_smoke_deployed": smoke_deployed,
    }
