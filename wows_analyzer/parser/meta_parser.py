from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path
from typing import Any


def parse_meta_blocks(replay_path: Path) -> dict[str, Any]:
    raw = replay_path.read_bytes()
    offset = 0

    if len(raw) < 4:
        raise ValueError("Replay file too small to parse meta block.")

    meta1_size = struct.unpack_from("<I", raw, offset)[0]
    offset += 4
    meta1_blob = raw[offset : offset + meta1_size]
    offset += meta1_size
    try:
        meta1 = json.loads(meta1_blob.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        # Replay header format may differ across game builds. Let downstream
        # packet dump metadata drive parsing when this quick header parse fails.
        return {}

    meta2 = {}
    if offset + 4 <= len(raw):
        _extra_count = struct.unpack_from("<I", raw, offset)[0]
        offset += 4
        if offset + 4 <= len(raw):
            meta2_size = struct.unpack_from("<I", raw, offset)[0]
            offset += 4
            if meta2_size > 0 and offset + meta2_size <= len(raw):
                meta2_blob = raw[offset : offset + meta2_size]
                try:
                    meta2 = json.loads(meta2_blob.decode("utf-8", errors="replace"))
                except json.JSONDecodeError:
                    meta2 = {}

    merged: dict[str, Any] = {}
    merged.update(meta1 if isinstance(meta1, dict) else {})
    if isinstance(meta2, dict):
        merged.update(meta2)
    return merged


def make_replay_hash(meta: dict[str, Any], replay_path: Path | None = None) -> str:
    date_time = meta.get("dateTime", "")
    map_name = meta.get("mapName", "")
    player_name = meta.get("playerName", "")
    key = f"{date_time}|{map_name}|{player_name}"
    if date_time or map_name or player_name:
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    # Fallback for replay formats where local metadata extraction is unavailable.
    if replay_path is None:
        raise ValueError("replay_path is required when metadata fields are empty")
    return hashlib.sha256(replay_path.read_bytes()).hexdigest()
