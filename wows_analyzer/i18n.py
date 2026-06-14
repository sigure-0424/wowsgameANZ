from __future__ import annotations

import math
from typing import Any


TRANSLATIONS = {
    "en": {
        "app_title": "WoWS Replay Analyzer",
        "replays": "Replays",
        "parsed": "Parsed",
        "errors": "Errors",
        "hidden_profiles": "Hidden profiles",
        "settings": "Settings",
        "app_id": "app_id",
        "server_region": "server_region",
        "game_root": "game_root",
        "replay_folder": "replay_folder",
        "min_battles_for_stats": "min_battles_for_stats",
        "api_delay_ms": "api_delay_ms",
        "cache_ttl_hours": "cache_ttl_hours",
        "language": "language",
        "empty": "<empty>",
        "set": "<set>",
        "report_title": "WoWS Replay Analyzer Report",
        "generated": "Generated",
        "battles": "Battles",
        "summary": "Summary",
        "known_outcome_battles": "Known outcome battles",
        "win_rate": "Win rate",
        "avg_damage": "Avg own damage",
        "survival_rate": "Survival rate",
        "significant_metrics": "Significant metrics (p<=0.05)",
        "top_positive_correlations": "Top Positive Correlations",
        "top_negative_correlations": "Top Negative Correlations",
        "significant_p005": "Significant (p<=0.05)",
        "non_significant": "Non-significant (reference)",
        "insight_early_sink_win": "By NOT sinking early, you avoided a loss in {percentage:.1f}% of matches.",
        "insight_early_sink_loss": "By sinking early, you are losing {percentage:.1f}% of the time.",
        "insight_early_sink_override": "This only changes if the average win rate of your allies is above {threshold:.1f}% and {condition}.",
        "metric_own_damage": "Your Damage",
        "metric_own_kills": "Your Kills",
        "metric_own_kd": "Your K/D",
        "metric_own_survived": "You Survived",
        "metric_own_dmg_share": "Your Team Damage Share",
        "metric_ally_avg_winrate": "Allies Avg Win Rate",
        "metric_ally_winrate_top": "Best Ally Win Rate",
        "metric_ally_winrate_worst": "Worst Ally Win Rate",
        "metric_enemy_avg_winrate": "Enemies Avg Win Rate",
        "metric_enemy_winrate_worst": "Worst Enemy Win Rate",
        "metric_winrate_delta": "Team Win Rate Gap (Ally - Enemy)",
        "metric_damage_delta": "Team Damage Gap (Ally - Enemy)",
        "metric_kill_delta": "Team Kills Gap (Ally - Enemy)",
        "metric_sink_delta_t5": "Sink Pace Gap @5m",
        "metric_sink_delta_t10": "Sink Pace Gap @10m",
        "metric_sink_delta_t15": "Sink Pace Gap @15m",
        "metric_own_tier_disadvantage": "Tier Disadvantage",
    },
    "ja": {
        "app_title": "WoWSリプレイ分析ツール",
        "replays": "リプレイ数",
        "parsed": "解析済み",
        "errors": "エラー",
        "hidden_profiles": "非公開プロフ",
        "settings": "設定",
        "app_id": "アプリケーションID",
        "server_region": "サーバー地域",
        "game_root": "ゲームインストール先",
        "replay_folder": "リプレイフォルダ",
        "min_battles_for_stats": "統計に必要な最小戦闘数",
        "api_delay_ms": "API遅延(ms)",
        "cache_ttl_hours": "キャッシュ有効期限(時)",
        "language": "言語",
        "empty": "<未設定>",
        "set": "<設定済み>",
        "report_title": "WoWSリプレイ分析レポート",
        "generated": "生成日時",
        "battles": "戦闘数",
        "summary": "要約",
        "known_outcome_battles": "勝敗確定済みの戦闘",
        "win_rate": "勝率",
        "avg_damage": "平均与ダメージ",
        "survival_rate": "生存率",
        "significant_metrics": "有意な指標 (p<=0.05)",
        "top_positive_correlations": "上位の正の相関",
        "top_negative_correlations": "上位の負の相関",
        "significant_p005": "有意な指標 (p<=0.05)",
        "non_significant": "有意でない指標 (参考)",
        "insight_early_sink_win": "あなたは「開幕で沈まない」ことによって、開幕で沈んだ際は {percentage:.1f}% 負けているところを回避できています。",
        "insight_early_sink_loss": "あなたは「開幕で沈む」ことによって、{percentage:.1f}% 負けています。",
        "insight_early_sink_override": "これは味方の平均勝率が {threshold:.1f}% 以上かつ {condition} の場合のみ覆ります。",
        "metric_own_damage": "与ダメージ",
        "metric_own_kills": "撃沈数",
        "metric_own_kd": "K/D比",
        "metric_own_survived": "生存",
        "metric_own_dmg_share": "ダメージ貢献率",
        "metric_ally_avg_winrate": "味方平均勝率",
        "metric_ally_winrate_top": "味方最高勝率",
        "metric_ally_winrate_worst": "味方最低勝率",
        "metric_enemy_avg_winrate": "敵平均勝率",
        "metric_enemy_winrate_worst": "敵最低勝率",
        "metric_winrate_delta": "勝率差 (味方-敵)",
        "metric_damage_delta": "ダメージ差 (味方-敵)",
        "metric_kill_delta": "撃沈数差 (味方-敵)",
        "metric_sink_delta_t5": "沈没ペース差 @5分",
        "metric_sink_delta_t10": "沈没ペース差 @10分",
        "metric_sink_delta_t15": "沈没ペース差 @15分",
        "metric_own_tier_disadvantage": "格差マッチング度",
        "positive_contribution": "〜することで {delta:+.1f}% の勝率寄与があります",
        "negative_contribution": "〜することは {abs_delta:.1f}% の勝率低下と関連しています",
        "low_sample_ref": "（データ不足のため参考値）",
        "low_predictive_power": "\n※このメトリクスは現在のサンプルでは勝敗への予測力が低いです。",
        "already_met_target": "すでに勝利水準を達成",
        "map_data_missing": "マップ分類データ未設定",
        "T-101": (
            "カテゴリ 1 — 自艦生存\n"
            "T-101: 開幕生存\n"
            "あなたは {survived_early_label} ことによって、\n"
            "開幕生存した場合の勝率は {wr_survived_early:.1f}%、\n"
            "沈んだ場合は {wr_died_early:.1f}% であり、\n"
            "{delta_label}{sample_suffix}\n\n"
            "この傾向は味方平均勝率が {clan_threshold:.1f}% 以上の場合に限り逆転することがあります\n"
            "（その条件下での勝率差: {delta_survival_early_conditional:+.1f}%）。"
        ),
        "T-102": (
            "T-102: 試合終了時生存\n"
            "あなたが {survived_match_label} 試合の勝率は\n"
            "それぞれ {wr_survived_match:.1f}% / {wr_died_match:.1f}% です。\n"
            "生存に {delta_survival_match:+.1f}% の勝率差があります。{sample_suffix}\n\n"
            "ただし自艦の与ダメが {own_damage:.0f} を超えている場合、\n"
            "撃沈されていても勝率への影響は {delta_survival_damage_adj:+.1f}% に縮小します。"
        ),
        "T-103": (
            "T-103: 生存時間\n"
            "あなたの平均生存時間は {avg_survived_time:.0f} 秒です。\n"
            "生存時間が {time_threshold:.0f} 秒を超えた試合の勝率は {wr_long_lived:.1f}%、\n"
            "それ未満は {wr_short_lived:.1f}% です（差: {delta_time:+.1f}%）。{sample_suffix}{predictive_suffix}"
        ),
        "T-201": (
            "\nカテゴリ 2 — 自艦ダメージ\n"
            "T-201: 与ダメ絶対値\n"
            "あなたの平均与ダメは {avg_damage:.0f} です。\n"
            "与ダメが {damage_threshold:.0f} を超えた試合の勝率は {wr_high_dmg:.1f}%、\n"
            "それ未満は {wr_low_dmg:.1f}% です（差: {delta_damage:+.1f}%）。{sample_suffix}\n\n"
            "この効果は自艦ティア {own_tier} のシップタイプ {own_ship_type} における\n"
            "パーセンタイルで上位 {damage_percentile:.0f}% に相当します。"
        ),
        "T-202": (
            "T-202: チーム内与ダメ貢献率\n"
            "あなたはチーム全体の与ダメのうち {own_dmg_share:.1f}% を担っています。\n"
            "この比率が {share_threshold:.1f}% を超えた試合の勝率は {wr_high_share:.1f}%、\n"
            "それ未満は {wr_low_share:.1f}% です（差: {delta_share:+.1f}%）。{sample_suffix}"
        ),
        "T-203": (
            "T-203: ダメージ効率（ダメージ/分）\n"
            "あなたの平均ダメージ効率は {avg_dpm:.0f} DPM です。\n"
            "DPM が {dpm_threshold:.0f} を超えた試合の勝率は {wr_high_dpm:.1f}%、\n"
            "それ未満は {wr_low_dpm:.1f}% です（差: {delta_dpm:+.1f}%）。{sample_suffix}"
        ),
        "T-301": (
            "\nカテゴリ 3 — キル / K/D\n"
            "T-301: キル数\n"
            "あなたの平均キル数は {avg_kills:.2f} です。\n"
            "{kill_threshold} 体以上キルした試合の勝率は {wr_multi_kill:.1f}%、\n"
            "それ未満は {wr_low_kill:.1f}% です（差: {delta_kill:+.1f}%）。{sample_suffix}"
        ),
        "T-302": (
            "T-302: ファーストキル\n"
            "あなたが試合で最初のキルを取った場合の勝率は {wr_first_blood:.1f}%、\n"
            "取らなかった場合は {wr_no_first_blood:.1f}% です。\n"
            "{delta_label}{sample_suffix}"
        ),
        "T-303": (
            "T-303: K/D 比\n"
            "あなたの平均 K/D は {avg_kd:.2f} です。\n"
            "K/D が {kd_threshold:.1f} を超えた試合の勝率は {wr_high_kd:.1f}%、\n"
            "それ未満は {wr_low_kd:.1f}% です（差: {delta_kd:+.1f}%）。{sample_suffix}"
        ),
        "T-401": (
            "\nカテゴリ 4 — 駆逐艦専用\n"
            "T-401: 魚雷命中\n"
            "あなたの平均魚雷命中数は {avg_torp_hits:.1f} 本です。\n"
            "{torp_threshold} 本以上命中させた試合の勝率は {wr_torp_hit:.1f}%、\n"
            "それ未満は {wr_torp_miss:.1f}% です（差: {delta_torp:+.1f}%）。{sample_suffix}"
        ),
        "T-402": (
            "T-402: スポッティングダメージ\n"
            "あなたの平均スポッティングダメージは {avg_spot_dmg:.0f} です。\n"
            "{spot_threshold:.0f} を超えた試合の勝率は {wr_high_spot:.1f}%、\n"
            "それ未満は {wr_low_spot:.1f}% です（差: {delta_spot:+.1f}%）。{sample_suffix}\n\n"
            "スポッティングダメージは与ダメ（相関 r={r_dmg_won:.2f}）よりも\n"
            "勝率への相関が {r_spot_won:.2f} {spot_relation} です。"
        ),
        "T-403": (
            "T-403: スモーク展開\n"
            "あなたが {smoke_threshold} 回以上スモークを展開した試合の勝率は {wr_smoke:.1f}%、\n"
            "それ未満は {wr_no_smoke:.1f}% です（差: {delta_smoke:+.1f}%）。{sample_suffix}"
        ),
        "T-404": (
            "T-404: キャップ占有\n"
            "あなたがキャップゾーンを {cap_threshold:.0f} 秒以上占有した試合の勝率は {wr_cap:.1f}%、\n"
            "それ未満は {wr_no_cap:.1f}% です（差: {delta_cap:+.1f}%）。{sample_suffix}"
        ),
        "T-501": (
            "\nカテゴリ 5 — 味方の質\n"
            "T-501: 味方平均勝率\n"
            "あなたの味方平均勝率が {ally_wr_threshold:.1f}% 以上だった試合の勝率は {wr_good_ally:.1f}%、\n"
            "未満は {wr_bad_ally:.1f}% です（差: {delta_ally_wr:+.1f}%）。{sample_suffix}\n\n"
            "統計的には味方平均勝率と勝敗の相関は r={r_ally_wr_won:.2f} です。"
        ),
        "T-502": (
            "T-502: 味方ワースト勝率プレイヤー\n"
            "味方の最低勝率プレイヤーが {ally_worst_threshold:.1f}% 未満だった試合の勝率は {wr_has_potato:.1f}%、\n"
            "それ以上だった試合は {wr_no_potato:.1f}% です（差: {delta_potato:+.1f}%）。{sample_suffix}\n\n"
            "チーム全体の平均勝率よりも、最低勝率 1 人の影響が\n"
            "{potato_relation}\n"
            "傾向があります（r={r_ally_worst_won:.2f} vs {r_ally_avg_won:.2f}）。"
        ),
        "T-503": (
            "T-503: 味方トップ勝率プレイヤー\n"
            "味方の最高勝率プレイヤーが {ally_top_threshold:.1f}% 以上いた試合の勝率は {wr_has_ace:.1f}%、\n"
            "いなかった試合は {wr_no_ace:.1f}% です（差: {delta_ace:+.1f}%）。{sample_suffix}"
        ),
        "T-504": (
            "T-504: 味方勝率分散（チームのバラつき）\n"
            "味方勝率の標準偏差が {ally_std_threshold:.1f}% 以上（バラつき大）の試合の勝率は {wr_high_std:.1f}%、\n"
            "均質なチーム（標準偏差未満）は {wr_low_std:.1f}% です（差: {delta_std:+.1f}%）。{sample_suffix}"
        ),
        "T-505": (
            "T-505: 敵平均勝率との差分\n"
            "味方平均勝率が敵を {winrate_delta_threshold:+.1f}% 以上上回っていた試合の勝率は {wr_positive_delta:.1f}%、\n"
            "下回っていた試合は {wr_negative_delta:.1f}% です（差: {delta_wr_delta:+.1f}%）。{sample_suffix}\n\n"
            "勝率差が ±{deadzone:.1f}% 以内のほぼ同等マッチでの勝率は {wr_even_match:.1f}% であり、\n"
            "あなたが個人スキルで勝敗に影響を与えられる可能性が最も高い状況です。"
        ),
        "T-601": (
            "\nカテゴリ 6 — 敵の質\n"
            "T-601: 敵平均勝率\n"
            "敵平均勝率が {enemy_wr_threshold:.1f}% 以上だった試合の勝率は {wr_strong_enemy:.1f}%、\n"
            "未満は {wr_weak_enemy:.1f}% です（差: {delta_enemy_wr:+.1f}%）。{sample_suffix}"
        ),
        "T-602": (
            "T-602: 敵ワースト勝率（弱点敵の影響）\n"
            "敵の最低勝率プレイヤーが {enemy_worst_threshold:.1f}% 未満だった試合の勝率は {wr_enemy_has_potato:.1f}%、\n"
            "そうでない試合は {wr_enemy_no_potato:.1f}% です（差: {delta_enemy_potato:+.1f}%）。{sample_suffix}\n\n"
            "つまり敵に \"弱点\" が 1 人いることで {delta_enemy_potato:+.1f}% の勝率上昇が見られます。"
        ),
        "T-701": (
            "\nカテゴリ 7 — 沈没ペース\n"
            "T-701: 開幕 5 分間の沈没ペース優位\n"
            "試合開始 5 分時点で味方チームが敵より多く撃沈していた（sink_delta_t5 > 0）試合の勝率は {wr_sink_lead_t5:.1f}%、\n"
            "劣勢（< 0）だった試合は {wr_sink_trail_t5:.1f}% です（差: {delta_sink_t5:+.1f}%）。{sample_suffix}\n\n"
            "5 分時点での優位が最終勝敗と一致した割合は {sink_t5_accuracy:.1f}% です。{predictive_suffix}"
        ),
        "T-702": (
            "T-702: 10 分・15 分時点\n"
            "10 分時点の優位一致率: {sink_t10_accuracy:.1f}%\n"
            "15 分時点の優位一致率: {sink_t15_accuracy:.1f}%\n\n"
            "沈没ペースの予測力は試合が進むにつれて {sink_accuracy_trend} 傾向があります。"
        ),
        "T-703": (
            "T-703: 逆転試合の特徴\n"
            "5 分時点で劣勢（sink_delta_t5 < 0）にもかかわらず勝利した試合は\n"
            "全試合中 {comeback_rate:.1f}% です。\n"
            "その逆転試合での共通特徴:\n"
            "- 味方平均勝率: {comeback_ally_wr:.1f}%（通常敗北時: {normal_loss_ally_wr:.1f}%）\n"
            "- 自艦与ダメ:   {comeback_own_dmg:.0f}（通常敗北時: {normal_loss_own_dmg:.0f}）"
        ),
        "T-801": (
            "\nカテゴリ 8 — マップ\n"
            "T-801: マップ別勝率\n"
            "マップ \"{map_name}\" でのあなたの勝率は {wr_on_map:.1f}%（n={n_on_map}）です。\n"
            "全マップ平均（{overall_wr:.1f}%）と比較して {delta_map:+.1f}% の差があります。\n\n"
            "このマップでの相関上位指標:\n"
            "1. {map_corr_metric_1} (r={map_corr_r_1:.2f})\n"
            "2. {map_corr_metric_2} (r={map_corr_r_2:.2f})"
        ),
        "T-802": (
            "T-802: マップ種別（開け具合）\n"
            "オープンマップ（{open_maps}）での勝率: {wr_open_map_str}\n"
            "クローズドマップ（{closed_maps}）での勝率: {wr_closed_map_str}\n"
            "差: {delta_map_type_str}\n\n"
            "あなたは {strong_map_type} マップで強い傾向があります。"
        ),
        "T-901": (
            "\nカテゴリ 9 — ティア帯 / マッチング位置\n"
            "T-901: トップティア / ボトムティア\n"
            "自艦がマッチの最高ティアだった（tier_disadvantage = 0）試合の勝率: {wr_top_tier:.1f}%\n"
            "ティア差 1（tier_disadvantage = 1）:                                 {wr_mid_tier:.1f}%\n"
            "ティア差 2（ボトムティア、tier_disadvantage = 2）:                   {wr_bot_tier:.1f}%\n\n"
            "トップ→ボトムで {delta_tier_pos:+.1f}% の勝率変化があります。{sample_suffix}"
        ),
        "T-902": (
            "T-902: ボトムティアでの個人貢献\n"
            "ボトムティア試合（tier_disadvantage = 2）での平均与ダメは {avg_dmg_bot:.0f} です。\n"
            "同条件の他プレイヤーと比較して {dmg_percentile_bot_label} {dmg_percentile_bot:.0f}% に相当します。\n\n"
            "ボトムティアで与ダメ {bot_dmg_threshold:.0f} 以上を達成した場合の勝率は {wr_bot_high_dmg:.1f}%、\n"
            "それ未満は {wr_bot_low_dmg:.1f}% です（差: {delta_bot_dmg:+.1f}%）。{sample_suffix}"
        ),
        "T-903": (
            "T-903: ティア帯別傾向\n"
            "T{tier_band_start}–T{tier_band_end} 帯での勝率: {wr_tier_band:.1f}%（n={n_tier_band}）\n"
            "同ティア帯での相関上位指標:\n"
            "1. {tier_corr_metric_1} (r={tier_corr_r_1:.2f})\n"
            "2. {tier_corr_metric_2} (r={tier_corr_r_2:.2f})"
        ),
        "T-1001": (
            "\nカテゴリ 10 — 艦種\n"
            "T-1001: 艦種別勝率\n"
            "{own_ship_type}（{own_ship_type_abbr}）での勝率: {wr_by_type:.1f}%（n={n_by_type}）\n"
            "全艦種平均（{overall_wr:.1f}%）比: {delta_type:+.1f}%"
        ),
        "T-1002": (
            "T-1002: 艦種内での役割達成\n"
            "{own_ship_type} として期待されるロール指標（{role_metric}）が\n"
            "{role_threshold:.0f} を超えた試合の勝率: {wr_role_met:.1f}%\n"
            "それ未満: {wr_role_unmet:.1f}%（差: {delta_role:+.1f}%）\n\n"
            "ロール指標の定義:\n"
            "  DD  → スポッティングダメージ + キャップ時間\n"
            "  CA  → 与ダメ + 対空ribbons\n"
            "  BB  → 与ダメ + 被スポット低減（生存時間）\n"
            "  CV  → スポッティングダメージ + 与ダメ\n"
            "  SS  → 魚雷命中 + 生存時間"
        ),
        "T-1101": (
            "\nカテゴリ 11 — 艦艇個別\n"
            "T-1101: 艦艇勝率と全艦平均比較\n"
            "\"{vessel_name}\" での勝率: {wr_vessel:.1f}%（n={n_vessel}）\n"
            "全艦平均（{overall_wr:.1f}%）比: {delta_vessel:+.1f}%\n"
            "同艦種・同ティア内での位置: 上位 {vessel_percentile:.0f}%"
        ),
        "T-1102": (
            "T-1102: 艦艇固有の勝率決定因子\n"
            "\"{vessel_name}\" において勝敗との相関が最も高い指標:\n"
            "1. {vessel_corr_metric_1}  r={vessel_corr_r_1:.2f}  (全艦平均: r={global_corr_r_1:.2f})\n"
            "2. {vessel_corr_metric_2}  r={vessel_corr_r_2:.2f}  (全艦平均: r={global_corr_r_2:.2f})\n"
            "3. {vessel_corr_metric_3}  r={vessel_corr_r_3:.2f}  (全艦平均: r={global_corr_r_3:.2f})\n\n"
            "この艦は他艦と比べて {vessel_unique_metric} が勝率に与える影響が\n"
            "{vessel_unique_relation} です。"
        ),
        "T-1201": (
            "\nカテゴリ 12 — 複合条件（交差分析）\n"
            "T-1201: 自艦活躍 × 味方の質\n"
            "あなたの与ダメが高く（>{own_dmg_threshold:.0f}）かつ味方平均勝率も高い（>{ally_wr_threshold:.1f}%）試合:\n"
            "  勝率 {wr_both_good:.1f}%（n={n_both_good}）\n\n"
            "あなたの与ダメが高いが味方が弱い（<{ally_wr_threshold:.1f}%）試合:\n"
            "  勝率 {wr_own_good_ally_bad:.1f}%（n={n_own_good_ally_bad}）\n\n"
            "あなたが低ダメで味方が強い試合:\n"
            "  勝率 {wr_own_bad_ally_good:.1f}%（n={n_own_bad_ally_good}）\n\n"
            "あなたの個人パフォーマンスが勝率に与える純粋な寄与（味方質を固定した場合）:\n"
            "  {individual_contribution_delta:+.1f}%"
        ),
        "T-1202": (
            "T-1202: 沈没ペース × 個人生存\n"
            "開幕 5 分で有利（sink_delta_t5 > 0）かつあなたが生存:   勝率 {wr_lead_alive:.1f}%\n"
            "開幕 5 分で有利だがあなたが沈んでいた:                   勝率 {wr_lead_dead:.1f}%\n"
            "開幕 5 分で不利かつあなたが生存:                         勝率 {wr_trail_alive:.1f}%\n"
            "開幕 5 分で不利かつあなたも沈んでいた:                   勝率 {wr_trail_dead:.1f}%"
        ),
        "T-1203": (
            "T-1203: マップ × ティア位置\n"
            "マップ \"{map_name}\" でトップティアだった試合の勝率: {wr_map_top:.1f}%\n"
            "マップ \"{map_name}\" でボトムティアだった試合の勝率: {wr_map_bot:.1f}%\n"
            "差: {delta_map_tier:+.1f}%"
        ),
        "T-1301": (
            "\nカテゴリ 13 — 総合スコアリング（サマリー用）\n"
            "T-1301: 個人影響度スコア\n"
            "あなたの個人行動が勝敗に与える影響度スコア: {individual_impact_score:.1f} / 100\n\n"
            "内訳:\n"
            "  与ダメ寄与      {dmg_impact:.1f} pt  (相関 r={r_dmg:.2f})\n"
            "  生存寄与        {surv_impact:.1f} pt  (相関 r={r_surv:.2f})\n"
            "  キル寄与        {kill_impact:.1f} pt  (相関 r={r_kill:.2f})\n"
            "  ロール達成寄与  {role_impact:.1f} pt  (相関 r={r_role:.2f})\n\n"
            "チーム依存度スコア: {team_dependency_score:.1f} / 100\n"
            "（高いほど個人力より味方の質が勝敗を左右している）"
        ),
        "T-1302": (
            "T-1302: 改善優先度提示\n"
            "統計に基づく改善優先度（勝率への実効影響が大きい順）:\n\n"
            "1. {improve_item_1}\n"
            "   現状: {improve_current_1}  →  目標: {improve_target_1}\n"
            "   達成時の推定勝率変化: {improve_delta_1:+.1f}%\n\n"
            "2. {improve_item_2}\n"
            "   現状: {improve_current_2}  →  目標: {improve_target_2}\n"
            "   達成時の推定勝率変化: {improve_delta_2:+.1f}%\n\n"
            "3. {improve_item_3}\n"
            "   現状: {improve_current_3}  →  目標: {improve_target_3}\n"
            "   達成時の推定勝率変化: {improve_delta_3:+.1f}%"
        ),
    },
}


class I18n:
    def __init__(self, lang: str = "ja") -> None:
        self.lang = lang if lang in TRANSLATIONS else "en"
        self.strings = TRANSLATIONS[self.lang]

    def t(self, key: str, **kwargs: Any) -> str:
        text = self.strings.get(key, TRANSLATIONS["en"].get(key, key))
        if kwargs:
            try:
                # Replace None/NaN with 0 for safety in formatting
                safe_kwargs = {
                    k: (0.0 if v is None or (isinstance(v, float) and math.isnan(v)) else v)
                    for k, v in kwargs.items()
                }
                return text.format(**safe_kwargs)
            except Exception as e:
                # Return the raw text or the key if formatting fails completely
                return f"{text} (Format Error: {e})"
        return text


def get_i18n(lang: str = "ja") -> I18n:
    return I18n(lang)
