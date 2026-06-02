from __future__ import annotations

from collections import defaultdict


def detect_winner(
    battle_result_team: int | None,
    sink_events: list[dict],
    team_population: dict[int, int],
) -> tuple[int | None, int]:
    if battle_result_team in (0, 1):
        return battle_result_team, 0

    destroyed = defaultdict(set)
    for sink in sink_events:
        team = int(sink.get("team", -1))
        entity_id = int(sink.get("entity_id", -1))
        if team in (0, 1) and entity_id >= 0:
            destroyed[team].add(entity_id)

    for team in (0, 1):
        pop = team_population.get(team, 0)
        if pop > 0 and len(destroyed[team]) >= pop:
            return (1 if team == 0 else 0), 0

    return None, 1
