from __future__ import annotations

from typing import Any

from wows_analyzer.api.wg_client import WGClient


async def account_search_exact(client: WGClient, player_name: str) -> int | None:
    data = await client.get_json(
        "wows/account/search/",
        {
            "search": player_name,
            "type": "exact",
            "fields": "account_id,nickname",
        },
    )
    rows = data.get("data", [])
    if not rows:
        return None
    for row in rows:
        if row.get("nickname", "").lower() == player_name.lower():
            return int(row["account_id"])
    return int(rows[0]["account_id"])


async def account_info_batch(client: WGClient, account_ids: list[int]) -> dict[int, dict[str, Any]]:
    if not account_ids:
        return {}
    chunks = [account_ids[i : i + 100] for i in range(0, len(account_ids), 100)]
    out: dict[int, dict[str, Any]] = {}

    for chunk in chunks:
        ids = ",".join(str(v) for v in chunk)
        data = await client.get_json(
            "wows/account/info/",
            {
                "account_id": ids,
                "fields": "account_id,nickname,hidden_profile,statistics.pvp.wins,statistics.pvp.battles",
            },
        )
        data_map = data.get("data", {})
        for key, row in data_map.items():
            if row is None:
                continue
            out[int(key)] = row
    return out
