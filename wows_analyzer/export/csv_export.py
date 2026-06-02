from __future__ import annotations

from pathlib import Path

import pandas as pd


def export_csv(
    output_path: Path,
    battle_stats_df: pd.DataFrame,
    correlation_rows: list[dict],
    per_vessel_rows: list[dict],
) -> None:
    csv_dir = output_path / "csv"
    csv_dir.mkdir(parents=True, exist_ok=True)

    battle_stats_df.to_csv(csv_dir / "battle_stats.csv", index=False)
    pd.DataFrame(correlation_rows).to_csv(csv_dir / "correlation_results.csv", index=False)

    sink_cols = [
        "replay_hash",
        "sink_delta_t5",
        "sink_delta_t10",
        "sink_delta_t15",
        "sink_delta_t20",
    ]
    if battle_stats_df.empty:
        pd.DataFrame(columns=sink_cols).to_csv(csv_dir / "sink_pace.csv", index=False)
    else:
        existing_cols = [c for c in sink_cols if c in battle_stats_df.columns]
        if existing_cols:
            battle_stats_df[existing_cols].to_csv(csv_dir / "sink_pace.csv", index=False)
        else:
            pd.DataFrame(columns=sink_cols).to_csv(csv_dir / "sink_pace.csv", index=False)

    pd.DataFrame(per_vessel_rows).to_csv(csv_dir / "per_vessel.csv", index=False)
