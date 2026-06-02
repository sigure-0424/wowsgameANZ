from __future__ import annotations

import pandas as pd


def add_tier_band(df: pd.DataFrame) -> pd.DataFrame:
    def band(tier: float | int | None) -> str:
        if tier is None or pd.isna(tier):
            return "Unknown"
        t = int(float(tier))
        if t <= 5:
            return "Low"
        if t <= 8:
            return "Mid"
        return "High"

    out = df.copy()
    out["tier_band"] = out["own_ship_tier"].apply(band)
    return out


def build_slices(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    df = add_tier_band(df)
    slices: dict[str, pd.DataFrame] = {"overall": df}

    for value in sorted(df["tier_band"].dropna().unique()):
        slices[f"tier_band:{value}"] = df[df["tier_band"] == value]

    for value in sorted(df["own_ship_type"].dropna().unique()):
        slices[f"ship_type:{value}"] = df[df["own_ship_type"] == value]

    for value in sorted(df["own_ship_name"].dropna().unique()):
        slices[f"vessel:{value}"] = df[df["own_ship_name"] == value]

    return slices
