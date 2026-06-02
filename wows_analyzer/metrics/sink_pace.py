from __future__ import annotations


def sink_delta_at(sink_events: list[dict], t_seconds: int) -> int:
    ally_sinks = sum(1 for e in sink_events if int(e.get("team", -1)) == 0 and float(e.get("clock", 0)) <= t_seconds)
    enemy_sinks = sum(1 for e in sink_events if int(e.get("team", -1)) == 1 and float(e.get("clock", 0)) <= t_seconds)
    return ally_sinks - enemy_sinks
