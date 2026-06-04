from __future__ import annotations

from typing import Any


METRIC_LABELS: dict[str, str] = {
    "own_damage": "Your Damage",
    "own_kills": "Your Kills",
    "own_kd": "Your K/D",
    "own_survived": "You Survived",
    "own_dmg_share": "Your Team Damage Share",
    "ally_avg_winrate": "Allies Avg Win Rate",
    "ally_winrate_top": "Best Ally Win Rate",
    "ally_winrate_worst": "Worst Ally Win Rate",
    "enemy_avg_winrate": "Enemies Avg Win Rate",
    "enemy_winrate_worst": "Worst Enemy Win Rate",
    "winrate_delta": "Team Win Rate Gap (Ally - Enemy)",
    "damage_delta": "Team Damage Gap (Ally - Enemy)",
    "kill_delta": "Team Kills Gap (Ally - Enemy)",
    "sink_delta_t5": "Sink Pace Gap @5m",
    "sink_delta_t10": "Sink Pace Gap @10m",
    "sink_delta_t15": "Sink Pace Gap @15m",
    "own_tier_disadvantage": "Tier Disadvantage",
}


def metric_label(metric_id: str, i18n: Any | None = None) -> str:
    if i18n:
        localized = i18n.t(f"metric_{metric_id}")
        if localized != f"metric_{metric_id}":
            return localized
    return METRIC_LABELS.get(metric_id, metric_id)


def slice_label(slice_id: str) -> str:
    if slice_id == "overall":
        return "Overall"
    if slice_id.startswith("tier_band:"):
        return f"Tier Band: {slice_id.split(':', 1)[1]}"
    if slice_id.startswith("ship_type:"):
        return f"Ship Type: {slice_id.split(':', 1)[1]}"
    if slice_id.startswith("vessel:"):
        return f"Ship: {slice_id.split(':', 1)[1]}"
    return slice_id
