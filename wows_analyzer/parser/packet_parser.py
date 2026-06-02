from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any


def run_replayshark_dump(
    replayshark_exe: Path,
    replay_path: Path,
    jl_output_path: Path,
    game_dir: Path | None = None,
) -> bool:
    cmd = [
        str(replayshark_exe),
    ]
    if game_dir:
        cmd.extend(["-g", str(game_dir)])
    cmd.extend([
        "dump",
        str(replay_path),
        "--output",
        str(jl_output_path),
    ])
    try:
        result = subprocess.run(cmd, capture_output=False, timeout=120)
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False
    except Exception:
        return False


def parse_jl_events(jl_path: Path) -> dict[str, Any]:
    damage_events: list[dict[str, Any]] = []
    sink_events: list[dict[str, Any]] = []
    ribbons: list[dict[str, Any]] = []
    battle_result_team: int | None = None
    meta: dict[str, Any] = {}
    entity_team_map: dict[int, int] = {}
    own_entity_id: int | None = None
    arena_players: list[dict[str, Any]] = []

    with jl_path.open("r", encoding="utf-8", errors="replace") as f:
        for idx, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if idx == 0 and isinstance(obj, dict) and "payload" not in obj:
                meta = obj
                continue

            clock = float(obj.get("clock", 0.0))
            payload = obj.get("payload", {})
            if not isinstance(payload, dict):
                continue

            if "DamageReceived" in payload:
                dr = payload["DamageReceived"]
                victim = dr.get("victim")
                for aggressor in dr.get("aggressors", []):
                    damage_events.append(
                        {
                            "clock": clock,
                            "aggressor": int(aggressor.get("aggressor", -1)),
                            "victim": int(victim),
                            "damage": float(aggressor.get("damage", 0.0)),
                        }
                    )

            if "EntityDestroyed" in payload:
                ed = payload["EntityDestroyed"]
                sink_events.append(
                    {
                        "clock": clock,
                        "entity_id": int(ed.get("entity_id", -1)),
                    }
                )

            if "ShipDestroyed" in payload:
                sd = payload["ShipDestroyed"]
                sink_events.append(
                    {
                        "clock": clock,
                        "entity_id": int(sd.get("victim", -1)),
                    }
                )

            if "EntityCreate" in payload:
                ec = payload["EntityCreate"]
                entity_id = int(ec.get("entity_id", -1))
                props = ec.get("props", {})
                if isinstance(props, dict):
                    team_id = props.get("teamId")
                    if entity_id >= 0 and team_id in (0, 1):
                        entity_team_map[entity_id] = int(team_id)

            if "OwnShip" in payload:
                own = payload["OwnShip"]
                own_entity_id = int(own.get("entity_id", -1))
                if own_entity_id < 0:
                    own_entity_id = None

            if "OnArenaStateReceived" in payload and not arena_players:
                arena = payload["OnArenaStateReceived"]
                player_states = arena.get("player_states", []) if isinstance(arena, dict) else []
                if isinstance(player_states, list):
                    for player in player_states:
                        if not isinstance(player, dict):
                            continue
                        entity_id = int(player.get("entity_id", -1))
                        if entity_id < 0:
                            continue

                        raw_with_names = player.get("raw_with_names", {})
                        ship_id = None
                        if isinstance(raw_with_names, dict):
                            for key in ("shipParamsId", "shipId"):
                                if key in raw_with_names and raw_with_names[key] is not None:
                                    ship_id = int(raw_with_names[key])
                                    break

                        arena_players.append(
                            {
                                "entity_id": entity_id,
                                "name": player.get("username") or "unknown",
                                "team_id": player.get("team_id"),
                                "db_id": player.get("db_id"),
                                "ship_id": ship_id,
                            }
                        )

            if "BattleResults" in payload:
                br_raw = payload["BattleResults"]
                try:
                    br = json.loads(br_raw) if isinstance(br_raw, str) else br_raw
                    winner = br.get("winner_team_id") if isinstance(br, dict) else None
                    if winner in (0, 1):
                        battle_result_team = int(winner)
                    elif isinstance(br, dict):
                        common = br.get("commonList", [])
                        if isinstance(common, list) and len(common) >= 4 and common[3] in (0, 1):
                            battle_result_team = int(common[3])
                except Exception:
                    pass

            if "OnRibbon" in payload:
                ribbons.append({"clock": clock, "event": payload["OnRibbon"]})
            if "RibbonReceived" in payload:
                ribbons.append({"clock": clock, "event": payload["RibbonReceived"]})

    own_raw_team: int | None = None
    if own_entity_id is not None:
        own_raw_team = entity_team_map.get(own_entity_id)

    if own_raw_team in (0, 1):
        for ev in sink_events:
            raw_team = entity_team_map.get(int(ev.get("entity_id", -1)))
            if raw_team in (0, 1):
                ev["team"] = 0 if int(raw_team) == int(own_raw_team) else 1

    return {
        "meta": meta,
        "arena_players": arena_players,
        "own_entity_id": own_entity_id,
        "damage_events": damage_events,
        "sink_events": sink_events,
        "ribbons": ribbons,
        "battle_result_team": battle_result_team,
    }
