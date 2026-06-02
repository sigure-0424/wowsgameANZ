from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def export_json(output_path: Path, payload: dict[str, Any]) -> None:
    output_path.mkdir(parents=True, exist_ok=True)
    target = output_path / "analysis_results.json"
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
