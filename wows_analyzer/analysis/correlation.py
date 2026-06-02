from __future__ import annotations

import importlib
import math
from typing import Any

import pandas as pd

METRICS = [
    "own_damage",
    "own_kills",
    "own_kd",
    "own_survived",
    "own_dmg_share",
    "ally_avg_winrate",
    "ally_winrate_top",
    "ally_winrate_worst",
    "enemy_avg_winrate",
    "enemy_winrate_worst",
    "winrate_delta",
    "damage_delta",
    "kill_delta",
    "sink_delta_t5",
    "sink_delta_t10",
    "sink_delta_t15",
    "own_tier_disadvantage",
]


def correlation_table(df: pd.DataFrame, min_battles: int) -> list[dict[str, Any]]:
    scipy_stats = importlib.import_module("scipy.stats")
    valid = df[df["won"].notna()].copy()
    if len(valid) < min_battles:
        return []

    rows: list[dict[str, Any]] = []
    for metric in METRICS:
        if metric not in valid.columns:
            continue
        subset = valid[[metric, "won"]].dropna()
        if len(subset) < min_battles:
            continue
        if subset[metric].nunique(dropna=True) < 2:
            continue
        if subset["won"].nunique(dropna=True) < 2:
            continue
        try:
            r, p = scipy_stats.pearsonr(subset[metric], subset["won"])
        except Exception:  # noqa: BLE001
            continue
        if not math.isfinite(float(r)) or not math.isfinite(float(p)):
            continue
        rows.append(
            {
                "metric": metric,
                "r": float(r),
                "p": float(p),
                "n": int(len(subset)),
                "significant_5pct": bool(p <= 0.05),
            }
        )

    rows.sort(key=lambda x: abs(x["r"]), reverse=True)
    return rows
