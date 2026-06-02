from __future__ import annotations

from collections import defaultdict
from statistics import mean, pstdev
from typing import Any

from wows_analyzer.db.repository import Repository
from wows_analyzer.metrics.dd_metrics import compute_dd_metrics
from wows_analyzer.metrics.sink_pace import sink_delta_at


def _safe_mean(values: list[float]) -> float | None:
    return float(mean(values)) if values else None


def _safe_std(values: list[float]) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return 0.0
    return float(pstdev(values))


def _kill_map(damage_events: list[dict[str, Any]], sink_events: list[dict[str, Any]]) -> dict[int, int]:
    by_victim: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for ev in damage_events:
        by_victim[int(ev["victim"])].append(ev)

    out: dict[int, int] = {}
    for sink in sink_events:
        victim = int(sink["entity_id"])
        sink_clock = float(sink["clock"])
        hits = [e for e in by_victim.get(victim, []) if float(e["clock"]) <= sink_clock]
        if not hits:
            continue
        finisher = max(hits, key=lambda e: float(e["clock"]))
        out[victim] = int(finisher["aggressor"])
    return out


def compute_battle_stats(repo: Repository, replay_hash: str, ribbons: list[dict] | None = None) -> dict[str, Any] | None:
    battle = repo.fetch_battle(replay_hash)
    if not battle:
        return None

    players = [dict(r) for r in repo.fetch_players_by_replay(replay_hash)]
    if not players:
        return None

    ships = repo.fetch_ships_lookup()
    damage_rows = [dict(r) for r in repo.fetch_damage_events(replay_hash)]
    sink_rows = [dict(r) for r in repo.fetch_sink_events(replay_hash)]

    own = next((p for p in players if p.get("relation") is not None and int(p["relation"]) == 0), None)
    if own is None:
        return None

    own_entity_id = int(own["entity_id"])
    own_team = int(battle["own_team"] or 0)
    winner_team = battle["winner_team"]

    # Per-attacker damage totals.
    dmg_by_attacker: dict[int, float] = defaultdict(float)
    for ev in damage_rows:
        dmg_by_attacker[int(ev["aggressor"])] += float(ev["damage"])

    kill_map = _kill_map(damage_rows, sink_rows)
    kills_by_attacker: dict[int, int] = defaultdict(int)
    for aggressor in kill_map.values():
        kills_by_attacker[int(aggressor)] += 1

    sunk_ids = {int(s["entity_id"]) for s in sink_rows}

    own_damage = float(dmg_by_attacker.get(own_entity_id, 0.0))
    own_kills = int(kills_by_attacker.get(own_entity_id, 0))
    own_deaths = 1 if own_entity_id in sunk_ids else 0
    own_survived = 1 - own_deaths

    duration_s = int(battle["duration_s"] or 0)
    own_damage_per_min = own_damage / (duration_s / 60) if duration_s > 0 else 0.0

    ally_players = [p for p in players if p.get("team") is not None and int(p["team"]) == 0 and p.get("relation") is not None and int(p["relation"]) != 0]
    enemy_players = [p for p in players if p.get("team") is not None and int(p["team"]) == 1]

    def team_winrate_stats(team_players: list[dict[str, Any]]) -> tuple[int, float | None, float | None, float | None, float | None, int]:
        count = len(team_players)
        valid_rates = [float(p["win_rate"]) for p in team_players if p.get("win_rate") is not None]
        hidden_count = sum(1 for p in team_players if (p.get("win_rate_source") or "") == "excluded")
        return (
            count,
            _safe_mean(valid_rates),
            max(valid_rates) if valid_rates else None,
            min(valid_rates) if valid_rates else None,
            _safe_std(valid_rates),
            hidden_count,
        )

    def team_damage_kills_survival(team_players: list[dict[str, Any]]) -> tuple[float, int, int]:
        team_ids = {int(p["entity_id"]) for p in team_players}
        total_damage = float(sum(dmg_by_attacker.get(i, 0.0) for i in team_ids))
        total_kills = int(sum(kills_by_attacker.get(i, 0) for i in team_ids))
        survival_count = int(sum(1 for i in team_ids if i not in sunk_ids))
        return total_damage, total_kills, survival_count

    ally_count, ally_avg_wr, ally_top_wr, ally_worst_wr, ally_std_wr, ally_hidden = team_winrate_stats(ally_players)
    enemy_count, enemy_avg_wr, enemy_top_wr, enemy_worst_wr, enemy_std_wr, enemy_hidden = team_winrate_stats(enemy_players)

    ally_total_damage, ally_kills, ally_survival_count = team_damage_kills_survival(ally_players)
    enemy_total_damage, enemy_kills, enemy_survival_count = team_damage_kills_survival(enemy_players)

    own_dmg_share = own_damage / (own_damage + ally_total_damage) if (own_damage + ally_total_damage) > 0 else 0.0

    sink_rows_team = sink_rows
    sink_t5 = sink_delta_at(sink_rows_team, 300)
    sink_t10 = sink_delta_at(sink_rows_team, 600)
    sink_t15 = sink_delta_at(sink_rows_team, 900)
    sink_t20 = sink_delta_at(sink_rows_team, 1200)

    own_ship_id = int(own.get("ship_id") or 0)
    own_ship = ships.get(own_ship_id)
    own_ship_name = own_ship["name"] if own_ship else "Unknown"
    own_ship_tier = int(own_ship["tier"]) if own_ship else None
    own_ship_type = own_ship["type"] if own_ship else None

    known_tiers = []
    for p in players:
        sid = int(p.get("ship_id") or 0)
        ship = ships.get(sid)
        if ship is not None:
            known_tiers.append(int(ship["tier"]))
    max_tier = max(known_tiers) if known_tiers else own_ship_tier
    tier_disadvantage = (max_tier - own_ship_tier) if (max_tier is not None and own_ship_tier is not None) else None

    winrate_delta = None
    if ally_avg_wr is not None and enemy_avg_wr is not None:
        winrate_delta = float(ally_avg_wr - enemy_avg_wr)

    won = None
    if winner_team in (0, 1):
        won = 1 if int(winner_team) == own_team else 0

    dd_defaults = {
        "own_torp_hits": None,
        "own_spotting_damage": None,
        "own_cap_time_estimate": None,
        "own_smoke_deployed": None,
    }
    dd = compute_dd_metrics(ribbons or []) if own_ship_type == "Destroyer" else dd_defaults

    row = {
        "replay_hash": replay_hash,
        "won": won,
        "own_ship_id": own_ship_id,
        "own_ship_name": own_ship_name,
        "own_ship_tier": own_ship_tier,
        "own_ship_type": own_ship_type,
        "own_tier_disadvantage": tier_disadvantage,
        "own_damage": own_damage,
        "own_kills": own_kills,
        "own_deaths": own_deaths,
        "own_kd": own_kills / max(own_deaths, 1),
        "own_survived": own_survived,
        "own_damage_per_min": own_damage_per_min,
        "own_dmg_share": own_dmg_share,
        "own_torp_hits": dd["own_torp_hits"],
        "own_spotting_damage": dd["own_spotting_damage"],
        "own_cap_time_estimate": dd["own_cap_time_estimate"],
        "own_smoke_deployed": dd["own_smoke_deployed"],
        "ally_count": ally_count,
        "ally_avg_winrate": ally_avg_wr,
        "ally_winrate_top": ally_top_wr,
        "ally_winrate_worst": ally_worst_wr,
        "ally_winrate_std": ally_std_wr,
        "ally_hidden_count": ally_hidden,
        "ally_total_damage": ally_total_damage,
        "ally_kills": ally_kills,
        "ally_survival_count": ally_survival_count,
        "enemy_count": enemy_count,
        "enemy_avg_winrate": enemy_avg_wr,
        "enemy_winrate_top": enemy_top_wr,
        "enemy_winrate_worst": enemy_worst_wr,
        "enemy_winrate_std": enemy_std_wr,
        "enemy_hidden_count": enemy_hidden,
        "enemy_total_damage": enemy_total_damage,
        "enemy_kills": enemy_kills,
        "enemy_survival_count": enemy_survival_count,
        "winrate_delta": winrate_delta,
        "damage_delta": (ally_total_damage + own_damage) - enemy_total_damage,
        "kill_delta": (ally_kills + own_kills) - enemy_kills,
        "sink_delta_t5": sink_t5,
        "sink_delta_t10": sink_t10,
        "sink_delta_t15": sink_t15,
        "sink_delta_t20": sink_t20,
        "map_name": battle["map_name"],
        "game_mode": battle["game_mode"],
        "date": battle["date"],
    }
    return row
