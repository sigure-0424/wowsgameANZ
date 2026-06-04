from __future__ import annotations

from typing import Any

from wows_analyzer.config import AppConfig
from wows_analyzer.i18n import get_i18n


def render_settings(cfg: AppConfig) -> str:
    i18n = get_i18n(cfg.language)
    cyan = "\033[36m"
    reset = "\033[0m"

    def _v(val: Any) -> str:
        if val is None or val == "":
            return i18n.t("empty")
        return str(val)

    return (
        f"{cyan}{i18n.t('settings')}{reset}\n"
        f"- {i18n.t('app_id')}: {i18n.t('set') if cfg.app_id else i18n.t('empty')}\n"
        f"- {i18n.t('server_region')}: {cfg.server_region}\n"
        f"- {i18n.t('game_root')}: {_v(cfg.game_root)}\n"
        f"- {i18n.t('replay_folder')}: {_v(cfg.replay_folder)}\n"
        f"- {i18n.t('min_battles_for_stats')}: {cfg.min_battles_for_stats}\n"
        f"- {i18n.t('api_delay_ms')}: {cfg.api_delay_ms}\n"
        f"- {i18n.t('cache_ttl_hours')}: {cfg.cache_ttl_hours}\n"
        f"- {i18n.t('language')}: {cfg.language}\n"
    )
