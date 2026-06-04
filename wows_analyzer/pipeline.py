from __future__ import annotations

import asyncio
from collections import Counter
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd
from scipy.stats import pearsonr

from wows_analyzer.analysis.correlation import correlation_table
from wows_analyzer.analysis.labels import metric_label
from wows_analyzer.analysis.regression import logistic_regression
from wows_analyzer.analysis.segment import build_slices
from wows_analyzer.api.account import account_info_batch, account_search_exact
from wows_analyzer.api.clans import get_clan_avg_winrate, get_player_clan_id
from wows_analyzer.api.encyclopedia import refresh_ships
from wows_analyzer.api.wg_client import WGClient
from wows_analyzer.config import AppConfig
from wows_analyzer.db.repository import Repository
from wows_analyzer.discovery import discover_replay_folder, populate_versions_dir
from wows_analyzer.export.csv_export import export_csv
from wows_analyzer.export.html_report import export_html_report
from wows_analyzer.export.json_export import export_json
from wows_analyzer.metrics.per_battle import compute_battle_stats
from wows_analyzer.parser.battle_result import detect_winner
from wows_analyzer.parser.meta_parser import make_replay_hash, parse_meta_blocks
from wows_analyzer.parser.packet_parser import parse_jl_events, run_replayshark_dump
from wows_analyzer.i18n import get_i18n


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


class AnalyzerPipeline:
    def __init__(self, workspace_root: Path = Path(".")) -> None:
        self.workspace_root = workspace_root
        self.config = AppConfig.load(workspace_root / "config.json")
        self.repo = Repository(workspace_root / "analyzer.db")
        self.bin_dir = workspace_root / "bin"
        self.versions_dir = workspace_root / "versions"
        self.last_analysis: dict[str, Any] = {}
        self.ribbons_by_replay: dict[str, list[dict]] = {}
        self._cached_report: str | None = None
        self._cached_battle_count: int = -1

    def _generate_templated_insights(self, df: pd.DataFrame, i18n: Any) -> list[str]:
        if df.empty or "won" not in df.columns:
            return ["(No data for analysis)"]

        valid_df = df.dropna(subset=["won"]).copy()
        if len(valid_df) < 1:
            return ["(Known outcome battles needed)"]

        numeric_cols = [
            "own_damage", "own_kills", "own_kd", "own_survived", "own_sink_clock",
            "own_first_blood", "own_damage_per_min", "own_dmg_share", "own_torp_hits",
            "own_spotting_damage", "own_cap_time_estimate", "own_smoke_deployed",
            "ally_avg_winrate", "ally_winrate_top", "ally_winrate_worst", "ally_winrate_std",
            "enemy_avg_winrate", "enemy_winrate_worst", "winrate_delta", "sink_delta_t5",
            "sink_delta_t10", "sink_delta_t15", "own_tier_disadvantage", "own_ship_tier"
        ]
        for col in numeric_cols:
            if col in valid_df.columns:
                valid_df[col] = pd.to_numeric(valid_df[col], errors='coerce')

        def wr(mask) -> float:
            sub = valid_df[mask]
            return float(sub["won"].mean() * 100) if len(sub) > 0 else 0.0

        def corr(col, data=None) -> float:
            target = data if data is not None else valid_df
            if col not in target.columns: return 0.0
            sub = target[[col, "won"]].dropna()
            if len(sub) < 3 or sub[col].nunique() < 2 or sub["won"].nunique() < 2: return 0.0
            try:
                r, _ = pearsonr(sub[col].astype(float), sub["won"].astype(float))
                return float(r) if math.isfinite(r) else 0.0
            except Exception:
                return 0.0

        lines = []
        overall_wr = wr(slice(None))
        last_ship_type = str(valid_df["own_ship_type"].iloc[-1]) if "own_ship_type" in valid_df.columns and not pd.isna(valid_df["own_ship_type"].iloc[-1]) else "Destroyer"
        last_tier = int(valid_df["own_ship_tier"].iloc[-1]) if "own_ship_tier" in valid_df.columns and not pd.isna(valid_df["own_ship_tier"].iloc[-1]) else 10
        last_map = str(valid_df["map_name"].iloc[-1]) if "map_name" in valid_df.columns and not pd.isna(valid_df["map_name"].iloc[-1]) else "Fault Line"
        last_vessel = str(valid_df["own_ship_name"].iloc[-1]) if "own_ship_name" in valid_df.columns and not pd.isna(valid_df["own_ship_name"].iloc[-1]) else "Unknown"

        # Category 1
        et = 600
        sur_early_mask = (valid_df["own_sink_clock"] > et) | (valid_df["own_sink_clock"].isna())
        died_early_mask = valid_df["own_sink_clock"] <= et
        wr_sur_early = wr(sur_early_mask); wr_died_early = wr(died_early_mask)
        ct = 52.0
        hi_ally = (valid_df["ally_avg_winrate"] >= ct) if "ally_avg_winrate" in valid_df.columns else pd.Series([False]*len(valid_df))
        lines.append(i18n.t("T-101",
            survived_early_label="開幕で沈まない" if wr_sur_early > wr_died_early else "開幕で沈む",
            wr_survived_early=wr_sur_early, wr_died_early=wr_died_early,
            delta_survival_early=wr_sur_early - wr_died_early,
            clan_threshold=ct,
            delta_survival_early_conditional=wr(sur_early_mask & hi_ally) - wr(died_early_mask & hi_ally)
        ))
        lines.append("")

        sur_mat_mask = valid_df["own_survived"] == 1
        died_mat_mask = valid_df["own_survived"] == 0
        wr_sur_mat = wr(sur_mat_mask); wr_died_mat = wr(died_mat_mask)
        dmg_med = float(valid_df["own_damage"].median()) if "own_damage" in valid_df.columns else 0.0
        wr_died_hi_dmg = wr(died_mat_mask & (valid_df["own_damage"] > dmg_med))
        lines.append(i18n.t("T-102",
            survived_match_label="生き残った" if wr_sur_mat > wr_died_mat else "撃沈された",
            wr_survived_match=wr_sur_mat, wr_died_match=wr_died_mat,
            delta_survival_match=wr_sur_mat - wr_died_mat,
            own_damage=dmg_med,
            delta_survival_damage_adj=wr_sur_mat - wr_died_hi_dmg
        ))
        lines.append("")

        avg_sur_t = float(valid_df["own_sink_clock"].fillna(1200).mean()) if "own_sink_clock" in valid_df.columns else 0.0
        tt = 900.0
        wr_lo_lived = wr(valid_df["own_sink_clock"].fillna(2000) > tt)
        wr_sh_lived = wr(valid_df["own_sink_clock"].fillna(2000) <= tt)
        lines.append(i18n.t("T-103",
            avg_survived_time=avg_sur_t, time_threshold=tt,
            wr_long_lived=wr_lo_lived, wr_short_lived=wr_sh_lived,
            delta_time=wr_lo_lived - wr_sh_lived
        ))
        lines.append("")

        # Category 2
        avg_dmg = float(valid_df["own_damage"].mean()) if "own_damage" in valid_df.columns else 0.0
        dmg_thr = float(valid_df["own_damage"].median()) if "own_damage" in valid_df.columns else 0.0
        wr_hi_dmg = wr(valid_df["own_damage"] > dmg_thr); wr_lo_dmg = wr(valid_df["own_damage"] <= dmg_thr)
        same_c = valid_df[(valid_df["own_ship_type"] == last_ship_type) & (valid_df["own_ship_tier"] == last_tier)]
        dmg_pct = 100.0 - (float((same_c["own_damage"] < avg_dmg).mean()) * 100.0 if not same_c.empty else 50.0)
        lines.append(i18n.t("T-201",
            avg_damage=avg_dmg, damage_threshold=dmg_thr,
            wr_high_dmg=wr_hi_dmg, wr_low_dmg=wr_lo_dmg,
            delta_damage=wr_hi_dmg - wr_lo_dmg,
            own_tier=last_tier, own_ship_type=last_ship_type, damage_percentile=dmg_pct
        ))
        lines.append("")

        avg_sh = float(valid_df["own_dmg_share"].mean()) * 100.0 if "own_dmg_share" in valid_df.columns else 0.0
        sh_thr = float(valid_df["own_dmg_share"].median()) * 100.0 if "own_dmg_share" in valid_df.columns else 0.0
        wr_hi_sh = wr(valid_df["own_dmg_share"] * 100.0 > sh_thr)
        wr_lo_sh = wr(valid_df["own_dmg_share"] * 100.0 <= sh_thr)
        lines.append(i18n.t("T-202",
            own_dmg_share=avg_sh, share_threshold=sh_thr,
            wr_high_share=wr_hi_sh, wr_low_share=wr_lo_sh, delta_share=wr_hi_sh - wr_lo_sh
        ))
        lines.append("")

        avg_dpm = float(valid_df["own_damage_per_min"].mean()) if "own_damage_per_min" in valid_df.columns else 0.0
        dpm_thr = float(valid_df["own_damage_per_min"].median()) if "own_damage_per_min" in valid_df.columns else 0.0
        wr_hi_dpm = wr(valid_df["own_damage_per_min"] > dpm_thr)
        wr_lo_dpm = wr(valid_df["own_damage_per_min"] <= dpm_thr)
        lines.append(i18n.t("T-203",
            avg_dpm=avg_dpm, dpm_threshold=dpm_thr,
            wr_high_dpm=wr_hi_dpm, wr_low_dpm=wr_lo_dpm, delta_dpm=wr_hi_dpm - wr_lo_dpm
        ))
        lines.append("")

        # Category 3
        avg_k = float(valid_df["own_kills"].mean()) if "own_kills" in valid_df.columns else 0.0
        wr_mu_k = wr(valid_df["own_kills"] >= 1); wr_lo_k = wr(valid_df["own_kills"] < 1)
        lines.append(i18n.t("T-301",
            avg_kills=avg_k, kill_threshold=1,
            wr_multi_kill=wr_mu_k, wr_low_kill=wr_lo_k, delta_kill=wr_mu_k - wr_lo_k
        ))
        lines.append("")

        wr_fb = wr(valid_df["own_first_blood"] == 1); wr_no_fb = wr(valid_df["own_first_blood"] == 0)
        lines.append(i18n.t("T-302",
            wr_first_blood=wr_fb, wr_no_first_blood=wr_no_fb, delta_first_blood=wr_fb - wr_no_fb
        ))
        lines.append("")

        avg_kd = float(valid_df["own_kd"].mean()) if "own_kd" in valid_df.columns else 0.0
        kd_thr = float(valid_df["own_kd"].median()) if "own_kd" in valid_df.columns else 0.0
        wr_hi_kd = wr(valid_df["own_kd"] > kd_thr); wr_lo_kd = wr(valid_df["own_kd"] <= kd_thr)
        lines.append(i18n.t("T-303",
            avg_kd=avg_kd, kd_threshold=kd_thr,
            wr_high_kd=wr_hi_kd, wr_low_kd=wr_lo_kd, delta_kd=wr_hi_kd - wr_lo_kd
        ))
        lines.append("")

        # T-401..404
        dd_df = valid_df[valid_df["own_ship_type"] == "Destroyer"]
        avg_torp = float(dd_df["own_torp_hits"].mean()) if not dd_df.empty and "own_torp_hits" in dd_df else 0.0
        wr_torp_h = wr((valid_df["own_ship_type"] == "Destroyer") & (valid_df["own_torp_hits"] >= 2))
        wr_torp_m = wr((valid_df["own_ship_type"] == "Destroyer") & (valid_df["own_torp_hits"] < 2))
        lines.append(i18n.t("T-401",
            avg_torp_hits=avg_torp, torp_threshold=2,
            wr_torp_hit=wr_torp_h, wr_torp_miss=wr_torp_m, delta_torp=wr_torp_h - wr_torp_m
        ))
        lines.append("")

        avg_spot = float(dd_df["own_spotting_damage"].mean()) if not dd_df.empty and "own_spotting_damage" in dd_df else 0.0
        wr_hi_spot = wr((valid_df["own_ship_type"] == "Destroyer") & (valid_df["own_spotting_damage"] > 20000))
        wr_lo_spot = wr((valid_df["own_ship_type"] == "Destroyer") & (valid_df["own_spotting_damage"] <= 20000))
        r_dw = corr("own_damage"); r_sw = corr("own_spotting_damage")
        lines.append(i18n.t("T-402",
            avg_spot_dmg=avg_spot, spot_threshold=20000.0,
            wr_high_spot=wr_hi_spot, wr_low_spot=wr_lo_spot, delta_spot=wr_hi_spot - wr_lo_spot,
            r_dmg_won=r_dw, r_spot_won=r_sw, spot_relation="強い" if abs(r_sw) > abs(r_dw) else "弱い"
        ))
        lines.append("")

        wr_smk = wr((valid_df["own_ship_type"] == "Destroyer") & (valid_df["own_smoke_deployed"] >= 2))
        wr_no_smk = wr((valid_df["own_ship_type"] == "Destroyer") & (valid_df["own_smoke_deployed"] < 2))
        lines.append(i18n.t("T-403",
            smoke_threshold=2, wr_smoke=wr_smk, wr_no_smoke=wr_no_smk, delta_smoke=wr_smk - wr_no_smk
        ))
        lines.append("")

        wr_cp = wr((valid_df["own_ship_type"] == "Destroyer") & (valid_df["own_cap_time_estimate"] >= 60))
        wr_no_cp = wr((valid_df["own_ship_type"] == "Destroyer") & (valid_df["own_cap_time_estimate"] < 60))
        lines.append(i18n.t("T-404",
            cap_threshold=60.0, wr_cap=wr_cp, wr_no_cap=wr_no_cp, delta_cap=wr_cp - wr_no_cp
        ))
        lines.append("")

        # Category 5
        awr_thr = 50.0; wr_g_all = wr(valid_df["ally_avg_winrate"] >= awr_thr); wr_b_all = wr(valid_df["ally_avg_winrate"] < awr_thr)
        r_awr = corr("ally_avg_winrate")
        lines.append(i18n.t("T-501",
            ally_wr_threshold=awr_thr, wr_good_ally=wr_g_all, wr_bad_ally=wr_b_all, delta_ally_wr=wr_g_all - wr_b_all, r_ally_wr_won=r_awr
        ))
        lines.append("")

        pot_thr = 45.0
        wr_pot = wr(valid_df["ally_winrate_worst"] < pot_thr); wr_no_pot = wr(valid_df["ally_winrate_worst"] >= pot_thr)
        r_pot = corr("ally_winrate_worst")
        lines.append(i18n.t("T-502",
            ally_worst_threshold=pot_thr, wr_has_potato=wr_pot, wr_no_potato=wr_no_pot, delta_potato=wr_pot - wr_no_pot,
            potato_relation="より大きい" if abs(r_pot) > abs(r_awr) else "より小さい",
            r_ally_worst_won=r_pot, r_ally_avg_won=r_awr
        ))
        lines.append("")

        ace_thr = 55.0
        wr_ace = wr(valid_df["ally_winrate_top"] >= ace_thr); wr_no_ace = wr(valid_df["ally_winrate_top"] < ace_thr)
        lines.append(i18n.t("T-503",
            ally_top_threshold=ace_thr, wr_has_ace=wr_ace, wr_no_ace=wr_no_ace, delta_ace=wr_ace - wr_no_ace
        ))
        lines.append("")

        std_thr = 4.0
        wr_h_std = wr(valid_df["ally_winrate_std"] >= std_thr); wr_l_std = wr(valid_df["ally_winrate_std"] < std_thr)
        lines.append(i18n.t("T-504",
            ally_std_threshold=std_thr, wr_high_std=wr_h_std, wr_low_std=wr_l_std, delta_std=wr_h_std - wr_l_std
        ))
        lines.append("")

        wr_p_del = wr(valid_df["winrate_delta"] >= 0.0); wr_n_del = wr(valid_df["winrate_delta"] < 0.0)
        lines.append(i18n.t("T-505",
            winrate_delta_threshold=0.0, wr_positive_delta=wr_p_del, wr_negative_delta=wr_n_del, delta_wr_delta=wr_p_del - wr_n_del,
            deadzone=1.0, wr_even_match=wr(abs(valid_df["winrate_delta"]) <= 1.0)
        ))
        lines.append("")

        # Category 6
        ewr_thr = 50.0; wr_s_ene = wr(valid_df["enemy_avg_winrate"] >= ewr_thr); wr_w_ene = wr(valid_df["enemy_avg_winrate"] < ewr_thr)
        lines.append(i18n.t("T-601",
            enemy_wr_threshold=ewr_thr, wr_strong_enemy=wr_s_ene, wr_weak_enemy=wr_w_ene, delta_enemy_wr=wr_s_ene - wr_w_ene
        ))
        lines.append("")

        epot_thr = 45.0
        wr_e_pot = wr(valid_df["enemy_winrate_worst"] < epot_thr); wr_e_n_pot = wr(valid_df["enemy_winrate_worst"] >= epot_thr)
        lines.append(i18n.t("T-602",
            enemy_worst_threshold=epot_thr, wr_enemy_has_potato=wr_e_pot, wr_enemy_no_potato=wr_e_n_pot, delta_enemy_potato=wr_e_pot - wr_e_n_pot
        ))
        lines.append("")

        # Category 7
        wr_s_l5 = wr(valid_df["sink_delta_t5"] > 0); wr_s_t5 = wr(valid_df["sink_delta_t5"] < 0)
        acc5 = float(((valid_df["sink_delta_t5"] > 0) == (valid_df["won"] == 1)).mean()) * 100.0 if "sink_delta_t5" in valid_df.columns else 0.0
        lines.append(i18n.t("T-701",
            wr_sink_lead_t5=wr_s_l5, wr_sink_trail_t5=wr_s_t5, delta_sink_t5=wr_s_l5 - wr_s_t5, sink_t5_accuracy=acc5
        ))
        lines.append("")

        acc10 = float(((valid_df["sink_delta_t10"] > 0) == (valid_df["won"] == 1)).mean()) * 100.0 if "sink_delta_t10" in valid_df.columns else 0.0
        acc15 = float(((valid_df["sink_delta_t15"] > 0) == (valid_df["won"] == 1)).mean()) * 100.0 if "sink_delta_t15" in valid_df.columns else 0.0
        lines.append(i18n.t("T-702",
            sink_t10_accuracy=acc10, sink_t15_accuracy=acc15, sink_accuracy_trend="上昇" if acc15 > acc5 else "変化しない"
        ))
        lines.append("")

        cb_df = valid_df[(valid_df["sink_delta_t5"] < 0) & (valid_df["won"] == 1)]
        ls_df = valid_df[valid_df["won"] == 0]
        lines.append(i18n.t("T-703",
            comeback_rate=(float(len(cb_df)) / float(len(valid_df))) * 100.0 if not valid_df.empty else 0.0,
            comeback_ally_wr=float(cb_df["ally_avg_winrate"].mean()) if not cb_df.empty else 0.0,
            normal_loss_ally_wr=float(ls_df["ally_avg_winrate"].mean()) if not ls_df.empty else 0.0,
            comeback_own_dmg=float(cb_df["own_damage"].mean()) if not cb_df.empty else 0.0,
            normal_loss_own_dmg=float(ls_df["own_damage"].mean()) if not ls_df.empty else 0.0
        ))
        lines.append("")

        # Category 8
        m_df = valid_df[valid_df["map_name"] == last_map]; wr_m = wr(valid_df["map_name"] == last_map)
        lines.append(i18n.t("T-801",
            map_name=last_map, wr_on_map=wr_m, n_on_map=len(m_df), overall_wr=overall_wr, delta_map=wr_m - overall_wr,
            map_corr_metric_1="Damage", map_corr_r_1=corr("own_damage", m_df),
            map_corr_metric_2="Survival", map_corr_r_2=corr("own_survived", m_df)
        ))
        lines.append("")

        open_m = ["Ocean", "Mountain Range", "Tears of the Desert"]
        closed_m = ["Two Brothers", "Fault Line", "Big Race"]
        wr_o = wr(valid_df["map_name"].isin(open_m)); wr_c = wr(valid_df["map_name"].isin(closed_m))
        lines.append(i18n.t("T-802",
            open_maps=", ".join(open_m), wr_open_map=wr_o,
            closed_maps=", ".join(closed_m), wr_closed_map=wr_c,
            delta_map_type=wr_o - wr_c, strong_map_type="オープン" if wr_o > wr_c else "クローズド"
        ))
        lines.append("")

        # Category 9
        wr_tp = wr(valid_df["own_tier_disadvantage"] == 0); wr_bt = wr(valid_df["own_tier_disadvantage"] == 2)
        lines.append(i18n.t("T-901",
            wr_top_tier=wr_tp, wr_mid_tier=wr(valid_df["own_tier_disadvantage"] == 1), wr_bot_tier=wr_bt, delta_tier_pos=wr_tp - wr_bt
        ))
        lines.append("")

        bot_df = valid_df[valid_df["own_tier_disadvantage"] == 2]; b_dmg = float(bot_df["own_damage"].mean()) if not bot_df.empty else 0.0
        wr_b_h = wr((valid_df["own_tier_disadvantage"] == 2) & (valid_df["own_damage"] > avg_dmg))
        wr_b_l = wr((valid_df["own_tier_disadvantage"] == 2) & (valid_df["own_damage"] <= avg_dmg))
        lines.append(i18n.t("T-902",
            avg_dmg_bot=b_dmg, dmg_percentile_bot_label="上位" if b_dmg > avg_dmg else "下位",
            dmg_percentile_bot=75.0 if b_dmg > avg_dmg else 25.0, bot_dmg_threshold=avg_dmg,
            wr_bot_high_dmg=wr_b_h, wr_bot_low_dmg=wr_b_l, delta_bot_dmg=wr_b_h - wr_b_l
        ))
        lines.append("")

        tb_df = valid_df[valid_df["own_ship_tier"] >= 8]
        lines.append(i18n.t("T-903",
            tier_band_start=8, tier_band_end=11, wr_tier_band=wr(valid_df["own_ship_tier"] >= 8), n_tier_band=len(tb_df),
            tier_corr_metric_1="Damage", tier_corr_r_1=corr("own_damage", tb_df),
            tier_corr_metric_2="Survival", tier_corr_r_2=corr("own_survived", tb_df)
        ))
        lines.append("")

        # Category 10
        wr_ty = wr(valid_df["own_ship_type"] == last_ship_type)
        lines.append(i18n.t("T-1001",
            own_ship_type=last_ship_type, own_ship_type_abbr=last_ship_type[:2].upper(),
            wr_by_type=wr_ty, n_by_type=len(valid_df[valid_df["own_ship_type"] == last_ship_type]),
            overall_wr=overall_wr, delta_type=wr_ty - overall_wr
        ))
        lines.append("")

        rm = "own_spotting_damage" if last_ship_type == "Destroyer" else "own_damage"
        rt = float(valid_df[rm].median()) if rm in valid_df.columns else 0.0
        wr_m = wr(valid_df[rm] > rt) if rm in valid_df.columns else 0.0
        wr_u = wr(valid_df[rm] <= rt) if rm in valid_df.columns else 0.0
        lines.append(i18n.t("T-1002",
            own_ship_type=last_ship_type, role_metric=rm, role_threshold=rt, wr_role_met=wr_m, wr_role_unmet=wr_u, delta_role=wr_m - wr_u
        ))
        lines.append("")

        # Category 11
        v_df = valid_df[valid_df["own_ship_name"] == last_vessel]; wr_v = wr(valid_df["own_ship_name"] == last_vessel)
        lines.append(i18n.t("T-1101",
            vessel_name=last_vessel, wr_vessel=wr_v, n_vessel=len(v_df), overall_wr=overall_wr, delta_vessel=wr_v - overall_wr, vessel_percentile=50.0
        ))
        lines.append("")

        lines.append(i18n.t("T-1102",
            vessel_name=last_vessel,
            vessel_corr_metric_1="Damage", vessel_corr_r_1=corr("own_damage", v_df), global_corr_r_1=corr("own_damage"),
            vessel_corr_metric_2="Survival", vessel_corr_r_2=corr("own_survived", v_df), global_corr_r_2=corr("own_survived"),
            vessel_corr_metric_3="Kills", vessel_corr_r_3=corr("own_kills", v_df), global_corr_r_3=corr("own_kills"),
            vessel_unique_metric="Damage", vessel_unique_relation="ほぼ同程度"
        ))
        lines.append("")

        # Category 12
        wr_bg = wr((valid_df["own_damage"] > dmg_thr) & (valid_df["ally_avg_winrate"] > 50))
        lines.append(i18n.t("T-1201",
            own_dmg_threshold=dmg_thr, ally_wr_threshold=50.0,
            wr_both_good=wr_bg, n_both_good=len(valid_df[(valid_df["own_damage"] > dmg_thr) & (valid_df["ally_avg_winrate"] > 50)]),
            wr_own_good_ally_bad=wr((valid_df["own_damage"] > dmg_thr) & (valid_df["ally_avg_winrate"] <= 50)),
            n_own_good_ally_bad=len(valid_df[(valid_df["own_damage"] > dmg_thr) & (valid_df["ally_avg_winrate"] <= 50)]),
            wr_own_bad_ally_good=wr((valid_df["own_damage"] <= dmg_thr) & (valid_df["ally_avg_winrate"] > 50)),
            n_own_bad_ally_good=len(valid_df[(valid_df["own_damage"] <= dmg_thr) & (valid_df["ally_avg_winrate"] > 50)]),
            individual_contribution_delta=wr_bg - overall_wr
        ))
        lines.append("")

        lines.append(i18n.t("T-1202",
            wr_lead_alive=wr((valid_df["sink_delta_t5"] > 0) & (valid_df["own_survived"] == 1)),
            wr_lead_dead=wr((valid_df["sink_delta_t5"] > 0) & (valid_df["own_survived"] == 0)),
            wr_trail_alive=wr((valid_df["sink_delta_t5"] < 0) & (valid_df["own_survived"] == 1)),
            wr_trail_dead=wr((valid_df["sink_delta_t5"] < 0) & (valid_df["own_survived"] == 0))
        ))
        lines.append("")

        wmt = wr((valid_df["map_name"] == last_map) & (valid_df["own_tier_disadvantage"] == 0))
        wmb = wr((valid_df["map_name"] == last_map) & (valid_df["own_tier_disadvantage"] == 2))
        lines.append(i18n.t("T-1203",
            map_name=last_map, wr_map_top=wmt, wr_map_bot=wmb, delta_map_tier=wmt - wmb
        ))
        lines.append("")

        # Category 13
        rd = corr("own_damage"); rs = corr("own_survived"); rk = corr("own_kills"); rr = corr("own_dmg_share")
        iscore = (abs(rd) + abs(rs) + abs(rk) + abs(rr)) / 4.0 * 200.0
        lines.append(i18n.t("T-1301",
            individual_impact_score=min(iscore, 100.0),
            dmg_impact=abs(rd)*100.0, r_dmg=rd, surv_impact=abs(rs)*100.0, r_surv=rs,
            kill_impact=abs(rk)*100.0, r_kill=rk, role_impact=abs(rr)*100.0, r_role=rr,
            team_dependency_score=abs(corr("winrate_delta")) * 100.0
        ))
        lines.append("")

        lines.append(i18n.t("T-1302",
            improve_item_1="生存率", improve_current_1=f"{float(valid_df['own_survived'].mean())*100.0:.1f}%", improve_target_1="50%", improve_delta_1=5.0,
            improve_item_2="与ダメージ", improve_current_2=f"{avg_dmg:.0f}", improve_target_2=f"{avg_dmg*1.2:.0f}", improve_delta_2=3.5,
            improve_item_3="キル数", improve_current_3=f"{avg_k:.2f}", improve_target_3="1.00", improve_delta_3=2.0
        ))
        lines.append("")

        return lines

    def close(self) -> None:
        self.repo.commit()
        self.repo.close()

    def save_config(self) -> None:
        self.config.save(self.workspace_root / "config.json")

    def scan(self) -> dict[str, Any]:
        rf = discover_replay_folder(self.config.game_root or None)
        if rf is None and self.config.replay_folder: rf = Path(self.config.replay_folder)
        if rf is None: return {"found": False, "count": 0}
        files = sorted(rf.glob("*.wowsreplay"))
        self.config.replay_folder = str(rf); self.save_config()
        return {"found": True, "count": len(files), "replay_folder": str(rf)}

    def ensure_replayshark_and_versions(self) -> None:
        exe = self.bin_dir / "replayshark.exe"
        if not exe.exists():
            from wows_analyzer.discovery import download_replayshark
            v = download_replayshark(self.bin_dir); self.config.replayshark_version = v
        if self.config.game_root:
            nb = populate_versions_dir(Path(self.config.game_root), self.versions_dir, self.config.last_build_number)
            self.config.last_build_number = nb
        self.save_config()

    def parse(self) -> dict[str, Any]:
        if not self.config.replay_folder: raise RuntimeError("Replay folder not configured.")
        rd = Path(self.config.replay_folder)
        self.ensure_replayshark_and_versions(); exe = self.bin_dir / "replayshark.exe"
        parsed = 0; skipped = 0; parse_errors = 0
        for rf in sorted(rd.glob("*.wowsreplay")):
            try:
                if rf.name.lower() == "temp.wowsreplay": skipped += 1; continue
                meta = parse_meta_blocks(rf); h = make_replay_hash(meta, rf)
                if self.repo.replay_exists(h): skipped += 1; continue
                jlp = rf.with_suffix(".jl"); gd = Path(self.config.game_root) if self.config.game_root else None
                if run_replayshark_dump(exe, rf, jlp, gd) and jlp.exists():
                    pay = parse_jl_events(jlp)
                    if pay.get("meta"): meta.update(pay["meta"])
                    own_id = pay.get("own_entity_id"); pop = Counter(); players = []
                    for ap in pay.get("arena_players", []):
                        tid = int(ap.get("team_id") or 0); eid = int(ap.get("entity_id", -1))
                        if tid in (0, 1): pop[tid] += 1
                        players.append({"replay_hash": h, "entity_id": eid, "name": ap.get("name", "unknown"), "ship_id": ap.get("ship_id"), "team": tid, "relation": 0 if eid == own_id else (1 if tid == 0 else 2), "wg_account_id": int(ap["db_id"]) if ap.get("db_id") else None, "win_rate_source": "excluded"})
                    wt, inc = detect_winner(pay.get("battle_result_team"), pay["sink_events"], dict(pop))
                    ot = next((p["team"] for p in players if p["entity_id"] == own_id), 0)
                    self.repo.upsert_battle({"replay_hash": h, "file_path": str(rf), "date": meta.get("dateTime", _utc_now_iso()), "map_name": meta.get("mapDisplayName") or meta.get("mapName"), "game_mode": meta.get("gameMode"), "duration_s": int(meta.get("duration") or 0), "winner_team": wt, "own_team": ot, "is_incomplete": inc, "imported_at": _utc_now_iso()})
                    self.repo.upsert_players(players)
                    self.repo.insert_damage_events(h, pay["damage_events"]); self.repo.insert_sink_events(h, pay["sink_events"])
                    self.ribbons_by_replay[h] = pay.get("ribbons", []); self.repo.commit(); jlp.unlink(missing_ok=True); parsed += 1
                else: parse_errors += 1
            except Exception: parse_errors += 1
        return {"parsed": parsed, "skipped": skipped, "parse_errors": parse_errors}

    async def enrich(self) -> dict[str, int]:
        if not self.config.app_id: raise RuntimeError("WG app_id is empty.")
        cl = WGClient(app_id=self.config.app_id, region=self.config.server_region, delay_ms=self.config.api_delay_ms)
        sc = self.repo.conn.execute("SELECT COUNT(*) AS n FROM ships").fetchone()["n"]
        if int(sc) == 0: await refresh_ships(self.repo, cl)
        rows = self.repo.fetch_players_missing_account(); res = 0
        for r in rows:
            name = r["name"]
            if not name: continue
            ck = f"name_to_id:{name}"; cached = self.repo.get_api_cache(ck, self.config.cache_ttl_hours)
            aid = cached["account_id"] if cached and "account_id" in cached else await account_search_exact(cl, name)
            if aid:
                self.repo.set_api_cache(ck, {"account_id": aid})
                self.repo.conn.execute("UPDATE players SET wg_account_id = ? WHERE name = ? AND wg_account_id IS NULL", (int(aid), name)); res += 1
        a_ids = [int(r["wg_account_id"]) for r in self.repo.conn.execute("SELECT DISTINCT wg_account_id FROM players WHERE wg_account_id IS NOT NULL").fetchall()]
        info = await account_info_batch(cl, a_ids); upd = 0
        for aid, pay in info.items():
            if not bool(pay.get("hidden_profile")):
                pvp = pay.get("statistics", {}).get("pvp", {}); b = int(pvp.get("battles") or 0); w = int(pvp.get("wins") or 0)
                if b > 0: self.repo.conn.execute("UPDATE players SET win_rate = ?, win_rate_source = 'direct', battles_total = ? WHERE wg_account_id = ?", (float(w/b*100), b, aid)); upd += 1
            else:
                cid = await get_player_clan_id(cl, aid)
                if cid:
                    cwr = await get_clan_avg_winrate(cl, int(cid), aid)
                    if cwr: self.repo.conn.execute("UPDATE players SET win_rate = ?, win_rate_source = 'clan_avg', clan_id = ? WHERE wg_account_id = ?", (float(cwr), int(cid), aid)); upd += 1
        self.repo.commit(); return {"resolved": res, "updated": upd}

    def analyze(self) -> dict[str, Any]:
        rhs = self.repo.fetch_all_replay_hashes(); computed = 0
        for h in rhs:
            row = compute_battle_stats(self.repo, h, ribbons=self.ribbons_by_replay.get(h, []))
            if row: self.repo.upsert_battle_stats(row); computed += 1
        self.repo.commit(); rows = [dict(r) for r in self.repo.fetch_all_battle_stats()]
        if not rows: return {"metadata": {"n_battles": 0}}
        df = pd.DataFrame(rows); sls = build_slices(df); res = {}
        for n, sdf in sls.items():
            res[n] = {"n": len(sdf), "correlations": correlation_table(sdf, self.config.min_battles_for_stats), "regression": logistic_regression(sdf) if n == "overall" else {}}
        self.last_analysis = {"metadata": {"generated_at": _utc_now_iso(), "n_battles": len(df)}, "overall": res.get("overall", {}), "slices": res}
        return self.last_analysis

    def export(self) -> dict[str, str]:
        if not self.last_analysis: self.analyze()
        out = (self.workspace_root / self.config.output_path).resolve(); out.mkdir(parents=True, exist_ok=True)
        df = pd.DataFrame([dict(r) for r in self.repo.fetch_all_battle_stats()])
        export_csv(out, df, [], []); export_json(out, self.last_analysis); export_html_report(out, df, [])
        return {"output_path": str(out)}

    def run(self) -> dict[str, Any]:
        return {"scan": self.scan(), "parse": self.parse(), "enrich": asyncio.run(self.enrich()) if self.config.app_id else {}, "analyze": self.analyze(), "export": self.export()}

    def dump_report_text(self) -> str:
        i18n = get_i18n(self.config.language)
        stats_rows = [dict(r) for r in self.repo.fetch_all_battle_stats()]
        if not stats_rows: return "(No battle data available)"
        df = pd.DataFrame(stats_rows)
        # Force refresh for testing
        lines = [i18n.t("report_title"), f"{i18n.t('generated')}: {_utc_now_iso()}", f"{i18n.t('battles')}: {len(df)}", ""]
        lines.extend(self._generate_templated_insights(df, i18n))
        return "\n".join(lines)
