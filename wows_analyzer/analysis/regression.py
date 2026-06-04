from __future__ import annotations

import importlib
from typing import Any

import pandas as pd

FORMULA = (
    "won ~ own_damage + own_survived + winrate_delta"
    " + ally_winrate_worst + enemy_winrate_worst"
    " + sink_delta_t5 + own_tier_disadvantage"
)


def logistic_regression(df: pd.DataFrame) -> dict[str, Any]:
    np = importlib.import_module("numpy")
    smf = importlib.import_module("statsmodels.formula.api")

    cols = [
        "won",
        "own_damage",
        "own_survived",
        "winrate_delta",
        "ally_winrate_worst",
        "enemy_winrate_worst",
        "sink_delta_t5",
        "own_tier_disadvantage",
    ]
    
    # Check if all columns exist
    missing = [c for c in cols if c not in df.columns]
    if missing:
        return {"error": f"missing_columns: {missing}", "n": int(len(df))}

    data = df[cols].dropna()

    if len(data) < 30:
        return {"error": "insufficient_rows", "n": int(len(data))}
    if data["won"].nunique() < 2:
        return {"error": "insufficient_outcome_variance", "n": int(len(data))}

    try:
        model = smf.logit(FORMULA, data=data).fit(disp=False)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "n": int(len(data))}

    conf = model.conf_int()
    out_rows = []
    for coef_name, coef in model.params.items():
        pvalue = model.pvalues[coef_name]
        ci_low = conf.loc[coef_name, 0]
        ci_high = conf.loc[coef_name, 1]
        out_rows.append(
            {
                "predictor": coef_name,
                "coef": float(coef),
                "odds_ratio": float(np.exp(coef)),
                "ci95_low": float(np.exp(ci_low)),
                "ci95_high": float(np.exp(ci_high)),
                "p": float(pvalue),
            }
        )

    return {
        "n": int(len(data)),
        "pseudo_r2_mcfadden": float(model.prsquared),
        "predictors": out_rows,
    }
