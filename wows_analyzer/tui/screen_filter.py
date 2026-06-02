from __future__ import annotations


def render_filter(active_modes: list[str]) -> str:
    modes = ", ".join(active_modes) if active_modes else "<none>"
    return f"Filters\n- Game mode: {modes}\n"
