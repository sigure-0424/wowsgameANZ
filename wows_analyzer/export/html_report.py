from __future__ import annotations

import importlib
import math
from pathlib import Path

import pandas as pd

from wows_analyzer.analysis.labels import metric_label, slice_label


METRIC_DESCRIPTIONS: dict[str, str] = {
    "own_damage": "Total damage dealt by you.",
    "own_kills": "Ships destroyed by you.",
    "own_kd": "Your kills divided by deaths.",
    "own_survived": "Whether you survived the battle.",
    "own_dmg_share": "Your share of allied total damage.",
    "ally_avg_winrate": "Average ally historical win rate.",
    "enemy_avg_winrate": "Average enemy historical win rate.",
    "winrate_delta": "Ally avg win rate minus enemy avg.",
    "damage_delta": "Ally total damage minus enemy total.",
    "kill_delta": "Ally total kills minus enemy total.",
    "sink_delta_t5": "Team sink lead at 5 minutes.",
    "sink_delta_t10": "Team sink lead at 10 minutes.",
    "sink_delta_t15": "Team sink lead at 15 minutes.",
    "own_tier_disadvantage": "How many tiers above your ship the max tier was.",
}


COLUMN_RENAME = {
    "slice_name": "Scope",
    "metric_name": "Metric",
    "metric_note": "Meaning",
    "r": "Correlation (r)",
    "p": "p-value",
    "n": "Samples",
    "class": "Signal",
}


def _format_corr_table(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["Correlation (r)"] = out["r"].map(lambda v: f"{float(v):+.3f}")
    out["p-value"] = out["p"].map(lambda v: f"{float(v):.4f}")
    out["Samples"] = out["n"].astype(int)
    out = out.rename(columns=COLUMN_RENAME)
    keep = ["Scope", "Metric", "Meaning", "Correlation (r)", "p-value", "Samples", "Signal"]
    return out[keep]


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
        corr_df["metric_name"] = corr_df["metric"].map(metric_label)
        corr_df["metric_note"] = corr_df["metric"].map(lambda m: METRIC_DESCRIPTIONS.get(m, ""))
        corr_df["slice_name"] = corr_df["slice"].map(slice_label)

    if corr_df.empty:
        chart_html = "<h2>No correlation results available.</h2>"
        sig_table_html = ""
        nonsig_table_html = ""
    else:
        corr_df["abs_r"] = corr_df["r"].abs()
        corr_df = corr_df.sort_values("abs_r", ascending=False)
        overall_df = corr_df[corr_df["slice"] == "overall"].copy()
        if overall_df.empty:
            overall_df = corr_df.copy()
        significant = overall_df[overall_df["p"] <= 0.05].copy()
        nonsignificant = overall_df[overall_df["p"] > 0.05].copy()

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
                x="metric_name",
                y="r",
                color="class",
                title="Top Correlations With Win (|r| sorted)",
            )
            chart_html = fig.to_html(full_html=False, include_plotlyjs="cdn")

        sig_cols = ["slice_name", "metric_name", "metric_note", "r", "p", "n", "class"]
        nonsig_cols = ["slice_name", "metric_name", "metric_note", "r", "p", "n", "class"]
        sig_pretty = _format_corr_table(significant.head(15)[sig_cols]) if not significant.empty else pd.DataFrame()
        nonsig_pretty = _format_corr_table(nonsignificant.head(15)[nonsig_cols]) if not nonsignificant.empty else pd.DataFrame()
        sig_table_html = sig_pretty.to_html(index=False) if not sig_pretty.empty else "<p>No significant metrics in overall scope.</p>"
        nonsig_table_html = nonsig_pretty.to_html(index=False) if not nonsig_pretty.empty else "<p>No non-significant metrics in overall scope.</p>"

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
        <p>Positive r means "higher metric tends to increase win chance"; negative r means the opposite.</p>
        {chart_html}
    </div>
    <div class=\"section\">
        <h2>Significant Metrics (Overall, p <= 0.05)</h2>
        {sig_table_html}
    </div>
    <div class=\"section\">
        <h2>Non-significant Metrics (Overall, reference)</h2>
        {nonsig_table_html}
    </div>
</body>
</html>
"""
    (output_path / "report.html").write_text(html, encoding="utf-8")
