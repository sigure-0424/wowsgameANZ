from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MainScreenState:
    replay_count: int = 0
    parsed_ok: int = 0
    parse_errors: int = 0
    hidden_profiles: int = 0


def render_main(state: MainScreenState) -> str:
    return (
        "WoWS Replay Analyzer\n"
        f"Replays: {state.replay_count}\n"
        f"Parsed: {state.parsed_ok}  Errors: {state.parse_errors}\n"
        f"Hidden profiles: {state.hidden_profiles}\n"
    )
