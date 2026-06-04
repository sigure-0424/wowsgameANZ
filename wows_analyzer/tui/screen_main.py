from __future__ import annotations

from dataclasses import dataclass


from wows_analyzer.i18n import get_i18n


@dataclass
class MainScreenState:
    replay_count: int = 0
    parsed_ok: int = 0
    parse_errors: int = 0
    hidden_profiles: int = 0
    lang: str = "ja"


def render_main(state: MainScreenState) -> str:
    i18n = get_i18n(state.lang)
    green = "\033[32m"
    red = "\033[31m"
    yellow = "\033[33m"
    cyan = "\033[36m"
    reset = "\033[0m"

    return (
        f"{cyan}{i18n.t('app_title')}{reset}\n"
        f"{i18n.t('replays')}: {state.replay_count}\n"
        f"{i18n.t('parsed')}: {green}{state.parsed_ok}{reset}  "
        f"{i18n.t('errors')}: {red}{state.parse_errors}{reset}\n"
        f"{i18n.t('hidden_profiles')}: {yellow}{state.hidden_profiles}{reset}\n"
    )
