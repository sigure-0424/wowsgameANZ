from __future__ import annotations

import importlib
import math
from pathlib import Path

import pandas as pd


def export_html_report(output_path: Path, battle_stats_df: pd.DataFrame, correlation_rows: list[dict]) -> None:
    output_path.mkdir(parents=True, exist_ok=True)

    corr_df = pd.DataFrame(correlation_rows)
    px = None
    try:
        px = importlib.import_module("plotly.express")
    except Exception:  # noqa: BLE001
        px = None

    if not corr_df.empty:
        corr_df = corr_df[pd.to_numeric(corr_df["r"], errors="coerce").notna()].copy()
        corr_df = corr_df[pd.to_numeric(corr_df["p"], errors="coerce").notna()].copy()
        corr_df["r"] = corr_df["r"].astype(float)
        corr_df["p"] = corr_df["p"].astype(float)
        corr_df = corr_df[corr_df["r"].apply(lambda v: math.isfinite(v))]
        corr_df = corr_df[corr_df["p"].apply(lambda v: math.isfinite(v))]

    if corr_df.empty:
        chart_html = "<h2>No correlation results available.</h2>"
        sig_table_html = ""
        nonsig_table_html = ""
    else:
        corr_df["abs_r"] = corr_df["r"].abs()
        corr_df = corr_df.sort_values("abs_r", ascending=False)
        significant = corr_df[corr_df["p"] <= 0.05].copy()
        nonsignificant = corr_df[corr_df["p"] > 0.05].copy()

        def classify(row: pd.Series) -> str:
            r = abs(float(row["r"]))
            p = float(row["p"])
            if p <= 0.05 and r >= 0.3:
                return "Strong"
            if p <= 0.1 and r >= 0.2:
                return "Weak"
            return "Ignore"

        corr_df["class"] = corr_df.apply(classify, axis=1)
        significant["class"] = significant.apply(classify, axis=1)
        nonsignificant["class"] = nonsignificant.apply(classify, axis=1)

        if px is None:
            chart_html = corr_df.to_html(index=False)
        else:
            fig = px.bar(
                corr_df.head(12),
                x="metric",
                y="r",
                color="class",
                title="Top Correlations With Win (|r| sorted)",
            )
            chart_html = fig.to_html(full_html=False, include_plotlyjs="cdn")

        sig_table_html = significant.head(15).to_html(index=False)
        nonsig_table_html = nonsignificant.head(15).to_html(index=False)

    known_outcome = 0
    if "won" in battle_stats_df.columns:
        known_outcome = int(battle_stats_df["won"].notna().sum())

    win_rate = None
    if "won" in battle_stats_df.columns and known_outcome > 0:
        win_rate = float(battle_stats_df["won"].dropna().mean() * 100.0)

    avg_own_damage = (
        float(battle_stats_df["own_damage"].mean())
        if "own_damage" in battle_stats_df.columns and not battle_stats_df.empty
        else 0.0
    )
    survival_rate = (
        float(battle_stats_df["own_survived"].mean() * 100.0)
        if "own_survived" in battle_stats_df.columns and not battle_stats_df.empty
        else 0.0
    )

    summary = (
        f"""
    <div class="cards">
      <div class="card"><h3>Total Battles</h3><p>{len(battle_stats_df)}</p></div>
      <div class="card"><h3>Known Outcomes</h3><p>{known_outcome}</p></div>
      <div class="card"><h3>Win Rate</h3><p>{win_rate:.1f}%</p></div>
      <div class="card"><h3>Avg Own Damage</h3><p>{avg_own_damage:,.0f}</p></div>
      <div class="card"><h3>Survival Rate</h3><p>{survival_rate:.1f}%</p></div>
    </div>
    """
        if win_rate is not None
        else f"""
    <div class="cards">
      <div class="card"><h3>Total Battles</h3><p>{len(battle_stats_df)}</p></div>
      <div class="card"><h3>Known Outcomes</h3><p>{known_outcome}</p></div>
      <div class="card"><h3>Win Rate</h3><p>N/A</p></div>
      <div class="card"><h3>Avg Own Damage</h3><p>{avg_own_damage:,.0f}</p></div>
      <div class="card"><h3>Survival Rate</h3><p>{survival_rate:.1f}%</p></div>
    </div>
    """
    )

    html = f"""
<!doctype html>
<html>
<head>
  <meta charset=\"utf-8\" />
  <title>WoWS Replay Analyzer Report</title>
  <style>
        body {{ font-family: Segoe UI, sans-serif; margin: 24px; background: #f6f8fb; color: #132033; }}
    h1, h2 {{ margin-bottom: 8px; }}
        .cards {{ display: grid; grid-template-columns: repeat(auto-fit,minmax(160px,1fr)); gap: 12px; margin: 12px 0 20px; }}
        .card {{ background: #ffffff; border: 1px solid #d9e1ec; border-radius: 10px; padding: 12px; }}
        .card h3 {{ font-size: 13px; margin: 0 0 6px; color: #4d6480; }}
        .card p {{ font-size: 22px; font-weight: 700; margin: 0; }}
        .section {{ background: #ffffff; border: 1px solid #d9e1ec; border-radius: 10px; padding: 12px; margin: 14px 0; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ border-bottom: 1px solid #e8edf5; padding: 6px 8px; text-align: left; }}
  </style>
</head>
<body>
  <h1>WoWS Replay Analyzer Report</h1>
  {summary}
    <div class=\"section\">
        <h2>Correlation Overview</h2>
        {chart_html}
    </div>
    <div class=\"section\">
        <h2>Significant Metrics (p <= 0.05)</h2>
        {sig_table_html}
    </div>
    <div class=\"section\">
        <h2>Non-significant Metrics (Reference)</h2>
        {nonsig_table_html}
    </div>
</body>
</html>
"""
    (output_path / "report.html").write_text(html, encoding="utf-8")
