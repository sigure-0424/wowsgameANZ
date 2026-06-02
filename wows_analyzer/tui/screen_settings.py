from __future__ import annotations

from wows_analyzer.config import AppConfig


def render_settings(cfg: AppConfig) -> str:
    return (
        "Settings\n"
        f"- app_id: {'<set>' if cfg.app_id else '<empty>'}\n"
        f"- server_region: {cfg.server_region}\n"
        f"- game_root: {cfg.game_root or '<empty>'}\n"
        f"- replay_folder: {cfg.replay_folder or '<empty>'}\n"
        f"- min_battles_for_stats: {cfg.min_battles_for_stats}\n"
        f"- api_delay_ms: {cfg.api_delay_ms}\n"
        f"- cache_ttl_hours: {cfg.cache_ttl_hours}\n"
    )
