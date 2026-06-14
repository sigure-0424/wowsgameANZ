from __future__ import annotations

import asyncio
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import pearsonr, spearmanr
import statsmodels.formula.api as smf

from wows_analyzer.analysis.correlation import correlation_table
from wows_analyzer.analysis.labels import metric_label
from wows_analyzer.analysis.regression import logistic_regression
from wows_analyzer.analysis.segment import build_slices
from wows_analyzer.api.account import account_info_batch, account_search_parallel
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


# Global executor for parallel parsing
_PARSER_EXECUTOR = ProcessPoolExecutor(max_workers=4)

def _parse_replay_task(args: tuple[Path, Path, Path, Path | None]) -> dict[str, Any] | None:
    exe, replay_file, jl_path, game_dir = args
    try:
        if run_replayshark_dump(exe, replay_file, jl_path, game_dir) and jl_path.exists():
            payload = parse_jl_events(jl_path)
            jl_path.unlink(missing_ok=True)
            return payload
    except Exception:
        pass
    return None


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
        self._cached_scan: dict[str, Any] | None = None

    def clear_cache(self) -> None:
        self._cached_report = None
        self._cached_battle_count = -1
        self._cached_scan = None

    def _generate_templated_insights(self, df: pd.DataFrame, i18n: Any) -> list[str]:
        if df.empty or "won" not in df.columns:
            return ["(No data for analysis)"]

        valid_df = df.dropna(subset=["won"]).copy()
        if len(valid_df) < 1:
            return ["(Known outcome battles needed)"]

        # Map classification
        OPEN_MAPS = ["Ocean", "Mountain Range", "Tears of the Desert", "Neighbors", "Okinawa"]
        CLOSED_MAPS = ["Two Brothers", "Fault Line", "Big Race", "Shards", "New Dawn", "Ring"]

        # Robust type conversion
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
                valid_df[col] = pd.to_numeric(valid_df[col], errors='coerce').fillna(0.0)

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
            except Exception: return 0.0

        def delta_text(delta, n):
            suffix = i18n.t("low_sample_ref") if n < 10 else ""
            if delta >= 0:
                return i18n.t("positive_contribution", delta=delta), suffix
            return i18n.t("negative_contribution", abs_delta=abs(delta)), suffix

        lines = []
        overall_wr = wr(slice(None))
        last_ship_type = str(valid_df["own_ship_type"].iloc[-1]) if not valid_df.empty else "Destroyer"
        last_tier = int(valid_df["own_ship_tier"].iloc[-1]) if not valid_df.empty else 10
        last_map = str(valid_df["map_name"].iloc[-1]) if not valid_df.empty else "Fault Line"
        last_vessel = str(valid_df["own_ship_name"].iloc[-1]) if not valid_df.empty else "Unknown"

        # T-101
        sur_early_m = (valid_df["own_sink_clock"] > 600) | (valid_df["own_sink_clock"] == 0)
        died_early_m = (valid_df["own_sink_clock"] <= 600) & (valid_df["own_sink_clock"] > 0)
        wr_se = wr(sur_early_m); wr_de = wr(died_early_m)
        dt_lab, dt_suf = delta_text(wr_se - wr_de, len(valid_df))
        hi_ally = (valid_df["ally_avg_winrate"] >= 52) if "ally_avg_winrate" in valid_df.columns else pd.Series([False]*len(valid_df))
        lines.append(i18n.t("T-101", survived_early_label="開幕で沈まない" if wr_se > wr_de else "開幕で沈む", wr_survived_early=wr_se, wr_died_early=wr_de, delta_label=dt_lab, sample_suffix=dt_suf, clan_threshold=52.0, delta_survival_early_conditional=wr(sur_early_m & hi_ally) - wr(died_early_m & hi_ally)))
        lines.append("")

        # T-102
        wr_sm = wr(valid_df["own_survived"] == 1); wr_dm = wr(valid_df["own_survived"] == 0)
        dmg_m = float(valid_df["own_damage"].median())
        lines.append(i18n.t("T-102", survived_match_label="生き残った" if wr_sm > wr_dm else "撃沈された", wr_survived_match=wr_sm, wr_died_match=wr_dm, delta_survival_match=wr_sm - wr_dm, own_damage=dmg_m, delta_survival_damage_adj=wr_sm - wr((valid_df["own_survived"] == 0) & (valid_df["own_damage"] > dmg_m)), sample_suffix=i18n.t("low_sample_ref") if len(valid_df) < 10 else ""))
        lines.append("")

        # T-103
        avg_st = float(valid_df["own_sink_clock"].replace(0, 1200).mean()); wr_l = wr(valid_df["own_sink_clock"].replace(0, 2000) > 900); wr_s = wr((valid_df["own_sink_clock"] <= 900) & (valid_df["own_sink_clock"] > 0))
        lines.append(i18n.t("T-103", avg_survived_time=avg_st, time_threshold=900.0, wr_long_lived=wr_l, wr_short_lived=wr_s, delta_time=wr_l - wr_s, sample_suffix=i18n.t("low_sample_ref") if len(valid_df) < 10 else "", predictive_suffix=i18n.t("low_predictive_power") if abs(corr("own_sink_clock")) < 0.1 and len(valid_df) >= 30 else ""))
        lines.append("")

        # Category 2
        ad = float(valid_df["own_damage"].mean()); dt = float(valid_df["own_damage"].median()); wr_h = wr(valid_df["own_damage"] > dt); wr_l = wr(valid_df["own_damage"] <= dt)
        sc = valid_df[(valid_df["own_ship_type"] == last_ship_type) & (valid_df["own_ship_tier"] == last_tier)]
        dp = 100.0 - (float((sc["own_damage"] < ad).mean()) * 100.0 if not sc.empty else 50.0)
        lines.append(i18n.t("T-201", avg_damage=ad, damage_threshold=dt, wr_high_dmg=wr_h, wr_low_dmg=wr_l, delta_damage=wr_h - wr_l, own_tier=last_tier, own_ship_type=last_ship_type, damage_percentile=dp, sample_suffix=i18n.t("low_sample_ref") if len(valid_df) < 10 else ""))
        lines.append("")
        ash = float(valid_df["own_dmg_share"].mean()) * 100.0; sth = float(valid_df["own_dmg_share"].median()) * 100.0; wr_hs = wr(valid_df["own_dmg_share"] * 100.0 > sth); wr_ls = wr(valid_df["own_dmg_share"] * 100.0 <= sth)
        lines.append(i18n.t("T-202", own_dmg_share=ash, share_threshold=sth, wr_high_share=wr_hs, wr_low_share=wr_ls, delta_share=wr_hs - wr_ls, sample_suffix=i18n.t("low_sample_ref") if len(valid_df) < 10 else ""))
        lines.append("")
        adp = float(valid_df["own_damage_per_min"].mean()); dpt = float(valid_df["own_damage_per_min"].median()); wr_hp = wr(valid_df["own_damage_per_min"] > dpt); wr_lp = wr(valid_df["own_damage_per_min"] <= dpt)
        lines.append(i18n.t("T-203", avg_dpm=adp, dpm_threshold=dpt, wr_high_dpm=wr_hp, wr_low_dpm=wr_lp, delta_dpm=wr_hp - wr_lp, sample_suffix=i18n.t("low_sample_ref") if len(valid_df) < 10 else ""))
        lines.append("")

        # Category 3
        ak = float(valid_df["own_kills"].mean()); wr_mk = wr(valid_df["own_kills"] >= 1); wr_lk = wr(valid_df["own_kills"] < 1)
        lines.append(i18n.t("T-301", avg_kills=ak, kill_threshold=1, wr_multi_kill=wr_mk, wr_low_kill=wr_lk, delta_kill=wr_mk - wr_lk, sample_suffix=i18n.t("low_sample_ref") if len(valid_df) < 10 else ""))
        lines.append("")
        wr_f = wr(valid_df["own_first_blood"] == 1); wr_nf = wr(valid_df["own_first_blood"] == 0); d_l, d_s = delta_text(wr_f - wr_nf, len(valid_df))
        lines.append(i18n.t("T-302", wr_first_blood=wr_f, wr_no_first_blood=wr_nf, delta_label=d_l, sample_suffix=d_s))
        lines.append("")
        akd = float(valid_df["own_kd"].mean()); kdt = float(valid_df["own_kd"].median()); wr_hk = wr(valid_df["own_kd"] > kdt); wr_lk = wr(valid_df["own_kd"] <= kdt)
        lines.append(i18n.t("T-303", avg_kd=akd, kd_threshold=kdt, wr_high_kd=wr_hk, wr_low_kd=wr_lk, delta_kd=wr_hk - wr_lk, sample_suffix=i18n.t("low_sample_ref") if len(valid_df) < 10 else ""))
        lines.append("")

        # T-401..404 (DD Only)
        if last_ship_type == "Destroyer":
            dd = valid_df[valid_df["own_ship_type"] == "Destroyer"]
            at = float(dd["own_torp_hits"].mean()); wr_th = wr((valid_df["own_ship_type"] == "Destroyer") & (valid_df["own_torp_hits"] >= 2)); wr_tm = wr((valid_df["own_ship_type"] == "Destroyer") & (valid_df["own_torp_hits"] < 2))
            lines.append(i18n.t("T-401", avg_torp_hits=at, torp_threshold=2, wr_torp_hit=wr_th, wr_torp_miss=wr_tm, delta_torp=wr_th - wr_tm, sample_suffix=i18n.t("low_sample_ref") if len(valid_df) < 10 else ""))
            lines.append("")
            asp = float(dd["own_spotting_damage"].mean()); wr_hsp = wr((valid_df["own_ship_type"] == "Destroyer") & (valid_df["own_spotting_damage"] > 20000)); wr_lsp = wr((valid_df["own_ship_type"] == "Destroyer") & (valid_df["own_spotting_damage"] <= 20000)); r_dw = corr("own_damage"); r_sw = corr("own_spotting_damage")
            lines.append(i18n.t("T-402", avg_spot_dmg=asp, spot_threshold=20000.0, wr_high_spot=wr_hsp, wr_low_spot=wr_lsp, delta_spot=wr_hsp - wr_lsp, r_dmg_won=r_dw, r_spot_won=r_sw, spot_relation="強い" if abs(r_sw) > abs(r_dw) else "弱い", sample_suffix=i18n.t("low_sample_ref") if len(valid_df) < 10 else ""))
            lines.append("")
            wr_sk = wr((valid_df["own_ship_type"] == "Destroyer") & (valid_df["own_smoke_deployed"] >= 2)); wr_ns = wr((valid_df["own_ship_type"] == "Destroyer") & (valid_df["own_smoke_deployed"] < 2))
            lines.append(i18n.t("T-403", smoke_threshold=2, wr_smoke=wr_sk, wr_no_smoke=wr_ns, delta_smoke=wr_sk - wr_ns, sample_suffix=i18n.t("low_sample_ref") if len(valid_df) < 10 else ""))
            lines.append("")
            wr_cp = wr((valid_df["own_ship_type"] == "Destroyer") & (valid_df["own_cap_time_estimate"] >= 60)); wr_nc = wr((valid_df["own_ship_type"] == "Destroyer") & (valid_df["own_cap_time_estimate"] < 60))
            lines.append(i18n.t("T-404", cap_threshold=60.0, wr_cap=wr_cp, wr_no_cap=wr_nc, delta_cap=wr_cp - wr_nc, sample_suffix=i18n.t("low_sample_ref") if len(valid_df) < 10 else ""))
            lines.append("")

        # T-501..505
        raw = corr("ally_avg_winrate"); ga = wr(valid_df["ally_avg_winrate"] >= 50.0); ba = wr(valid_df["ally_avg_winrate"] < 50.0)
        lines.append(i18n.t("T-501", ally_wr_threshold=50.0, wr_good_ally=ga, wr_bad_ally=ba, delta_ally_wr=ga - ba, r_ally_wr_won=raw, sample_suffix=i18n.t("low_sample_ref") if len(valid_df) < 10 else ""))
        lines.append("")
        rpw = corr("ally_winrate_worst"); hp = wr(valid_df["ally_winrate_worst"] < 45.0); np = wr(valid_df["ally_winrate_worst"] >= 45.0)
        lines.append(i18n.t("T-502", ally_worst_threshold=45.0, wr_has_potato=hp, wr_no_potato=np, delta_potato=hp - np, potato_relation="より大きい" if abs(rpw) > abs(raw) else "より小さい", r_ally_worst_won=rpw, r_ally_avg_won=raw, sample_suffix=i18n.t("low_sample_ref") if len(valid_df) < 10 else ""))
        lines.append("")
        ha = wr(valid_df["ally_winrate_top"] >= 55.0); na = wr(valid_df["ally_winrate_top"] < 55.0)
        lines.append(i18n.t("T-503", ally_top_threshold=55.0, wr_has_ace=ha, wr_no_ace=na, delta_ace=ha - na, sample_suffix=i18n.t("low_sample_ref") if len(valid_df) < 10 else ""))
        lines.append("")
        hstd = wr(valid_df["ally_winrate_std"] >= 4.0); lstd = wr(valid_df["ally_winrate_std"] < 4.0)
        lines.append(i18n.t("T-504", ally_std_threshold=4.0, wr_high_std=hstd, wr_low_std=lstd, delta_std=hstd - lstd, sample_suffix=i18n.t("low_sample_ref") if len(valid_df) < 10 else ""))
        lines.append("")
        wpd = wr(valid_df["winrate_delta"] >= 0.0); wnd = wr(valid_df["winrate_delta"] < 0.0)
        lines.append(i18n.t("T-505", winrate_delta_threshold=0.0, wr_positive_delta=wpd, wr_negative_delta=wnd, delta_wr_delta=wpd - wnd, deadzone=1.0, wr_even_match=wr(abs(valid_df["winrate_delta"]) <= 1.0), sample_suffix=i18n.t("low_sample_ref") if len(valid_df) < 10 else ""))
        lines.append("")

        # T-601..602
        wse = wr(valid_df["enemy_avg_winrate"] >= 50.0); wwe = wr(valid_df["enemy_avg_winrate"] < 50.0)
        lines.append(i18n.t("T-601", enemy_wr_threshold=50.0, wr_strong_enemy=wse, wr_weak_enemy=wwe, delta_enemy_wr=wse - wwe, sample_suffix=i18n.t("low_sample_ref") if len(valid_df) < 10 else ""))
        lines.append("")
        wep = wr(valid_df["enemy_winrate_worst"] < 45.0); wen = wr(valid_df["enemy_winrate_worst"] >= 45.0)
        lines.append(i18n.t("T-602", enemy_worst_threshold=45.0, wr_enemy_has_potato=wep, wr_enemy_no_potato=wen, delta_enemy_potato=wep - wen, sample_suffix=i18n.t("low_sample_ref") if len(valid_df) < 10 else ""))
        lines.append("")

        # T-701..703
        wsl5 = wr(valid_df["sink_delta_t5"] > 0); wst5 = wr(valid_df["sink_delta_t5"] < 0); ac5 = float(((valid_df["sink_delta_t5"] > 0) == (valid_df["won"] == 1)).mean()) * 100.0 if "sink_delta_t5" in valid_df.columns else 0.0
        lines.append(i18n.t("T-701", wr_sink_lead_t5=wsl5, wr_sink_trail_t5=wst5, delta_sink_t5=wsl5 - wst5, sink_t5_accuracy=ac5, sample_suffix=i18n.t("low_sample_ref") if len(valid_df) < 10 else "", predictive_suffix=i18n.t("low_predictive_power") if ac5 < 50.0 and len(valid_df) >= 30 else ""))
        lines.append("")
        ac10 = float(((valid_df["sink_delta_t10"] > 0) == (valid_df["won"] == 1)).mean()) * 100.0 if "sink_delta_t10" in valid_df.columns else 0.0; ac15 = float(((valid_df["sink_delta_t15"] > 0) == (valid_df["won"] == 1)).mean()) * 100.0 if "sink_delta_t15" in valid_df.columns else 0.0
        lines.append(i18n.t("T-702", sink_t10_accuracy=ac10, sink_t15_accuracy=ac15, sink_accuracy_trend="上昇" if ac15 > ac5 else "変化しない"))
        lines.append("")
        cb = valid_df[(valid_df["sink_delta_t5"] < 0) & (valid_df["won"] == 1)]; ls = valid_df[valid_df["won"] == 0]
        lines.append(i18n.t("T-703", comeback_rate=(float(len(cb))/len(valid_df)*100 if not valid_df.empty else 0), comeback_ally_wr=float(cb["ally_avg_winrate"].mean()) if not cb.empty else 0, normal_loss_ally_wr=float(ls["ally_avg_winrate"].mean()) if not ls.empty else 0, comeback_own_dmg=float(cb["own_damage"].mean()) if not cb.empty else 0, normal_loss_own_dmg=float(ls["own_damage"].mean()) if not ls.empty else 0))
        lines.append("")

        # T-801..802
        mdf = valid_df[valid_df["map_name"] == last_map]; wrm = wr(valid_df["map_name"] == last_map)
        lines.append(i18n.t("T-801", map_name=last_map, wr_on_map=wrm, n_on_map=len(mdf), overall_wr=overall_wr, delta_map=wrm - overall_wr, map_corr_metric_1="Damage", map_corr_r_1=corr("own_damage", mdf), map_corr_metric_2="Survival", map_corr_r_2=corr("own_survived", mdf)))
        lines.append("")
        wro = wr(valid_df["map_name"].isin(OPEN_MAPS)); wrc = wr(valid_df["map_name"].isin(CLOSED_MAPS)); hmd = valid_df["map_name"].isin(OPEN_MAPS + CLOSED_MAPS).any()
        lines.append(i18n.t("T-802", open_maps="Ocean, Mountain Range, ...", wr_open_map_str=f"{wro:.1f}%" if hmd else i18n.t("map_data_missing"), closed_maps="Two Brothers, Fault Line, ...", wr_closed_map_str=f"{wrc:.1f}%" if hmd else i18n.t("map_data_missing"), delta_map_type_str=f"{wro - wrc:+.1f}%" if hmd else "N/A", strong_map_type="オープン" if wro > wrc else "クローズド"))
        lines.append("")

        # T-901..903
        wtp = wr(valid_df["own_tier_disadvantage"] == 0); wbt = wr(valid_df["own_tier_disadvantage"] == 2)
        lines.append(i18n.t("T-901", wr_top_tier=wtp, wr_mid_tier=wr(valid_df["own_tier_disadvantage"] == 1), wr_bot_tier=wbt, delta_tier_pos=wtp - wbt, sample_suffix=i18n.t("low_sample_ref") if len(valid_df) < 10 else ""))
        lines.append("")
        btd = valid_df[valid_df["own_tier_disadvantage"] == 2]; btm = float(btd["own_damage"].median()) if not btd.empty else 0.0; wbh = wr((valid_df["own_tier_disadvantage"] == 2) & (valid_df["own_damage"] > btm)); wbl = wr((valid_df["own_tier_disadvantage"] == 2) & (valid_df["own_damage"] <= btm))
        lines.append(i18n.t("T-902", avg_dmg_bot=float(btd["own_damage"].mean()) if not btd.empty else 0.0, dmg_percentile_bot_label="上位" if (float(btd["own_damage"].mean()) if not btd.empty else 0) > ad else "下位", dmg_percentile_bot=75.0, bot_dmg_threshold=btm, wr_bot_high_dmg=wbh, wr_bot_low_dmg=wbl, delta_bot_dmg=wbh - wbl, sample_suffix=i18n.t("low_sample_ref") if len(btd) < 10 else ""))
        lines.append("")
        tb = valid_df[valid_df["own_ship_tier"] >= 8]
        lines.append(i18n.t("T-903", tier_band_start=8, tier_band_end=11, wr_tier_band=wr(valid_df["own_ship_tier"] >= 8), n_tier_band=len(tb), tier_corr_metric_1="Damage", tier_corr_r_1=corr("own_damage", tb), tier_corr_metric_2="Survival", tier_corr_r_2=corr("own_survived", tb)))
        lines.append("")

        # T-1001..1002
        wty = wr(valid_df["own_ship_type"] == last_ship_type)
        lines.append(i18n.t("T-1001", own_ship_type=last_ship_type, own_ship_type_abbr=last_ship_type[:2].upper(), wr_by_type=wty, n_by_type=len(valid_df[valid_df["own_ship_type"] == last_ship_type]), overall_wr=overall_wr, delta_type=wty - overall_wr))
        lines.append("")
        rm = "own_spotting_damage" if last_ship_type == "Destroyer" else "own_damage"; rt = float(valid_df[rm].median()); wm = wr(valid_df[rm] > rt); wu = wr(valid_df[rm] <= rt)
        lines.append(i18n.t("T-1002", own_ship_type=last_ship_type, role_metric=rm, role_threshold=rt, wr_role_met=wm, wr_role_unmet=wu, delta_role=wm - wu))
        lines.append("")

        # T-1101..1102
        vdf = valid_df[valid_df["own_ship_name"] == last_vessel]; wv = wr(valid_df["own_ship_name"] == last_vessel)
        lines.append(i18n.t("T-1101", vessel_name=last_vessel, wr_vessel=wv, n_vessel=len(vdf), overall_wr=overall_wr, delta_vessel=wv - overall_wr, vessel_percentile=50.0))
        lines.append("")
        lines.append(i18n.t("T-1102", vessel_name=last_vessel, vessel_corr_metric_1="Damage", vessel_corr_r_1=corr("own_damage", vdf), global_corr_r_1=corr("own_damage"), vessel_corr_metric_2="Survival", vessel_corr_r_2=corr("own_survived", vdf), global_corr_r_2=corr("own_survived"), vessel_corr_metric_3="Kills", vessel_corr_r_3=corr("own_kills", vdf), global_corr_r_3=corr("own_kills"), vessel_unique_metric="Damage", vessel_unique_relation="ほぼ同程度"))
        lines.append("")

        # T-1201..1203
        wbg = wr((valid_df["own_damage"] > dt) & (valid_df["ally_avg_winrate"] > 50))
        lines.append(i18n.t("T-1201", own_dmg_threshold=dt, ally_wr_threshold=50.0, wr_both_good=wbg, n_both_good=len(valid_df[(valid_df["own_damage"] > dt) & (valid_df["ally_avg_winrate"] > 50)]), wr_own_good_ally_bad=wr((valid_df["own_damage"] > dt) & (valid_df["ally_avg_winrate"] <= 50)), n_own_good_ally_bad=len(valid_df[(valid_df["own_damage"] > dt) & (valid_df["ally_avg_winrate"] <= 50)]), wr_own_bad_ally_good=wr((valid_df["own_damage"] <= dt) & (valid_df["ally_avg_winrate"] > 50)), n_own_bad_ally_good=len(valid_df[(valid_df["own_damage"] <= dt) & (valid_df["ally_avg_winrate"] > 50)]), individual_contribution_delta=wbg - overall_wr))
        lines.append("")
        lines.append(i18n.t("T-1202", wr_lead_alive=wr((valid_df["sink_delta_t5"] > 0) & (valid_df["own_survived"] == 1)), wr_lead_dead=wr((valid_df["sink_delta_t5"] > 0) & (valid_df["own_survived"] == 0)), wr_trail_alive=wr((valid_df["sink_delta_t5"] < 0) & (valid_df["own_survived"] == 1)), wr_trail_dead=wr((valid_df["sink_delta_t5"] < 0) & (valid_df["own_survived"] == 0))))
        lines.append("")
        wmt = wr((valid_df["map_name"] == last_map) & (valid_df["own_tier_disadvantage"] == 0)); wmb = wr((valid_df["map_name"] == last_map) & (valid_df["own_tier_disadvantage"] == 2))
        lines.append(i18n.t("T-1203", map_name=last_map, wr_map_top=wmt, wr_map_bot=wmb, delta_map_tier=wmt - wmb))
        lines.append("")

        # T-1301..1302
        lines.append(i18n.t("T-1301", individual_impact_score=min((abs(corr("own_damage"))+abs(corr("own_survived"))+abs(corr("own_kills"))+abs(corr("own_dmg_share")))/4*200, 100.0), dmg_impact=abs(corr("own_damage"))*100.0, r_dmg=corr("own_damage"), surv_impact=abs(corr("own_survived"))*100.0, r_surv=corr("own_survived"), kill_impact=abs(corr("own_kills"))*100.0, r_kill=corr("own_kills"), role_impact=abs(corr("own_dmg_share"))*100.0, r_role=corr("own_dmg_share"), team_dependency_score=abs(corr("winrate_delta")) * 100.0))
        lines.append("")
        won = valid_df[valid_df["won"] == 1]
        def tv(c, cur):
            if won.empty: return cur
            v = float(won[c].median()); return v if v > cur else i18n.t("already_met_target")
        lines.append(i18n.t("T-1302", improve_item_1="生存率", improve_current_1=f"{float(valid_df['own_survived'].mean())*100.0:.1f}%", improve_target_1=f"{tv('own_survived', valid_df['own_survived'].mean())*100.0:.1f}%" if isinstance(tv('own_survived', valid_df['own_survived'].mean()), float) else tv('own_survived', valid_df['own_survived'].mean()), improve_delta_1=5.0, improve_item_2="与ダメージ", improve_current_2=f"{ad:.0f}", improve_target_2=f"{tv('own_damage', ad):.0f}" if isinstance(tv('own_damage', ad), float) else tv('own_damage', ad), improve_delta_2=3.5, improve_item_3="キル数", improve_current_3=f"{ak:.2f}", improve_target_3=f"{tv('own_kills', ak):.2f}" if isinstance(tv('own_kills', ak), float) else tv('own_kills', ak), improve_delta_3=2.0))
        lines.append("")

        return lines

    def close(self) -> None:
        self.repo.commit()
        self.repo.close()

    def save_config(self) -> None:
        self.config.save(self.workspace_root / "config.json")

    def scan(self, force: bool = False) -> dict[str, Any]:
        if not force and self._cached_scan: return self._cached_scan
        rf = discover_replay_folder(self.config.game_root or None)
        if rf is None and self.config.replay_folder: rf = Path(self.config.replay_folder)
        if rf is None: res = {"found": False, "count": 0}
        else:
            fs = list(rf.glob("*.wowsreplay")); res = {"found": True, "count": len(fs), "replay_folder": str(rf)}
            if str(rf) != self.config.replay_folder: self.config.replay_folder = str(rf); self.save_config()
        self._cached_scan = res; return res

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
        rd = Path(self.config.replay_folder); self.ensure_replayshark_and_versions()
        exe = self.bin_dir / "replayshark.exe"
        parsed = 0; skipped = 0; parse_errors = 0
        
        all_replays = sorted(rd.glob("*.wowsreplay"))
        to_parse = []
        for rf in all_replays:
            if rf.name.lower() == "temp.wowsreplay": skipped += 1; continue
            meta = parse_meta_blocks(rf); h = make_replay_hash(meta, rf)
            if self.repo.replay_exists(h): skipped += 1; continue
            jlp = rf.with_suffix(".jl"); gd = Path(self.config.game_root) if self.config.game_root else None
            to_parse.append((exe, rf, jlp, gd, h, meta))

        if not to_parse:
            return {"parsed": 0, "skipped": skipped, "parse_errors": 0}

        # Step 2: Truly parallelize parsing
        tasks = [ (t[0], t[1], t[2], t[3]) for t in to_parse ]
        # We use a ThreadPool for the results because we want to update the DB sequentially
        # but the subprocesses (replayshark) are handled by _PARSER_EXECUTOR
        
        results = list(_PARSER_EXECUTOR.map(_parse_replay_task, tasks))

        for (exe_p, rf_p, jlp_p, gd_p, h_p, meta_p), res in zip(to_parse, results):
            try:
                if res:
                    if res.get("meta"): meta_p.update(res["meta"])
                    own_id = res.get("own_entity_id"); pop = Counter(); players = []
                    for ap in res.get("arena_players", []):
                        tid = int(ap.get("team_id") or 0); eid = int(ap.get("entity_id", -1))
                        if tid in (0, 1): pop[tid] += 1
                        # Prefer nickname for consistency
                        name = ap.get("nickname") or ap.get("name", "unknown")
                        players.append({"replay_hash": h_p, "entity_id": eid, "name": name, "ship_id": ap.get("ship_id"), "team": tid, "relation": 0 if eid == own_id else (1 if tid == 0 else 2), "wg_account_id": int(ap["db_id"]) if ap.get("db_id") else None, "win_rate_source": "excluded"})
                    
                    wt, inc = detect_winner(res.get("battle_result_team"), res["sink_events"], dict(pop))
                    own_team = next((p["team"] for p in players if p["entity_id"] == own_id), 0)
                    self.repo.upsert_battle({"replay_hash": h_p, "file_path": str(rf_p), "date": meta_p.get("dateTime", _utc_now_iso()), "map_name": meta_p.get("mapDisplayName") or meta_p.get("mapName"), "game_mode": meta_p.get("gameMode"), "duration_s": int(meta_p.get("duration") or 0), "winner_team": wt, "own_team": own_team, "is_incomplete": inc, "imported_at": _utc_now_iso()})
                    self.repo.upsert_players(players); self.repo.insert_damage_events(h_p, res["damage_events"]); self.repo.insert_sink_events(h_p, res["sink_events"]); self.ribbons_by_replay[h_p] = res.get("ribbons", []); parsed += 1
                else: parse_errors += 1
            except Exception: parse_errors += 1
        
        self.repo.commit()
        return {"parsed": parsed, "skipped": skipped, "parse_errors": parse_errors}

    async def enrich(self) -> dict[str, int]:
        if not self.config.app_id: raise RuntimeError("WG app_id is empty.")
        cl = WGClient(app_id=self.config.app_id, region=self.config.server_region, delay_ms=self.config.api_delay_ms)
        sc = self.repo.conn.execute("SELECT COUNT(*) AS n FROM ships").fetchone()["n"]
        if int(sc) == 0: await refresh_ships(self.repo, cl)
        
        # Deduplicate names and resolve in parallel
        players_missing = self.repo.fetch_players_missing_account()
        names_to_resolve = sorted(list(set(r["name"] for r in players_missing if r["name"])))
        
        resolved_map = await account_search_parallel(cl, names_to_resolve)
        res_count = 0
        for name, aid in resolved_map.items():
            if aid:
                self.repo.conn.execute("UPDATE players SET wg_account_id = ? WHERE name = ? AND wg_account_id IS NULL", (aid, name))
                res_count += 1
        
        # Batch info requests - only for those missing win_rate
        a_rows = self.repo.conn.execute("SELECT DISTINCT wg_account_id FROM players WHERE wg_account_id IS NOT NULL AND win_rate IS NULL").fetchall()
        a_ids = [int(r["wg_account_id"]) for r in a_rows]
        info = await account_info_batch(cl, a_ids)
        upd_count = 0
        for aid, pay in info.items():
            if not bool(pay.get("hidden_profile")):
                pvp = pay.get("statistics", {}).get("pvp", {})
                b = int(pvp.get("battles") or 0); w = int(pvp.get("wins") or 0)
                if b > 0: self.repo.conn.execute("UPDATE players SET win_rate = ?, win_rate_source = 'direct', battles_total = ? WHERE wg_account_id = ?", (float(w/b*100), b, aid)); upd_count += 1
            else:
                cid = await get_player_clan_id(cl, aid)
                if cid:
                    cwr = await get_clan_avg_winrate(cl, int(cid), aid)
                    if cwr: self.repo.conn.execute("UPDATE players SET win_rate = ?, win_rate_source = 'clan_avg', clan_id = ? WHERE wg_account_id = ?", (float(cwr), int(cid), aid)); upd_count += 1
        
        self.repo.commit(); return {"resolved": res_count, "updated": upd_count}

    def analyze(self) -> dict[str, Any]:
        rhs = self.repo.fetch_all_replay_hashes()
        for h in rhs:
            row = compute_battle_stats(self.repo, h, ribbons=self.ribbons_by_replay.get(h, []))
            if row: self.repo.upsert_battle_stats(row)
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
        i18n = get_i18n(self.config.language); stats_rows = [dict(r) for r in self.repo.fetch_all_battle_stats()]
        if not stats_rows: return "(No battle data available)"
        df = pd.DataFrame(stats_rows); lines = [i18n.t("report_title"), f"{i18n.t('generated')}: {_utc_now_iso()}", f"{i18n.t('battles')}: {len(df)}", ""]
        lines.extend(self._generate_templated_insights(df, i18n)); return "\n".join(lines)
