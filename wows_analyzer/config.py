from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any


CONFIG_PATH = Path("config.json")


@dataclass
class AppConfig:
    app_id: str = ""
    server_region: str = "ASIA"
    game_root: str = ""
    replay_folder: str = ""
    last_build_number: int = 0
    min_battles_for_stats: int = 30
    api_delay_ms: int = 100
    cache_ttl_hours: int = 24
    default_game_mode_filter: list[str] = field(default_factory=lambda: ["RandomBattle"])
    output_path: str = "./wows_analysis/"
    replayshark_version: str = ""

    @classmethod
    def load(cls, path: Path | None = None) -> "AppConfig":
        file_path = path or CONFIG_PATH
        if not file_path.exists():
            cfg = cls()
            cfg.save(file_path)
            return cfg

        raw = json.loads(file_path.read_text(encoding="utf-8"))
        defaults = cls()
        merged = asdict(defaults)
        merged.update(raw)
        return cls(**merged)

    def save(self, path: Path | None = None) -> None:
        file_path = path or CONFIG_PATH
        file_path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    def update(self, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            if not hasattr(self, key):
                raise ValueError(f"Unknown config field: {key}")
            setattr(self, key, value)
