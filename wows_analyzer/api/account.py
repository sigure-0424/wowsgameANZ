from __future__ import annotations

import asyncio
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


async def account_search_parallel(client: WGClient, names: list[str]) -> dict[str, int | None]:
    if not names:
        return {}

    semaphore = asyncio.Semaphore(10)

    async def search_one(name: str):
        async with semaphore:
            try:
                # Add a small stagger delay to avoid overwhelming the API
                await asyncio.sleep(0.05)
                aid = await account_search_exact(client, name)
                return name, aid
            except Exception:
                return name, None

    tasks = [search_one(n) for n in names]
    results = await asyncio.gather(*tasks)
    return {name: aid for name, aid in results}


async def account_info_batch(client: WGClient, account_ids: list[int]) -> dict[int, dict[str, Any]]:
    if not account_ids:
        return {}
    # Use unique IDs only
    unique_ids = sorted(list(set(account_ids)))
    chunks = [unique_ids[i : i + 100] for i in range(0, len(unique_ids), 100)]
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
        if data_map:
            for key, row in data_map.items():
                if row is None:
                    continue
                out[int(key)] = row
    return out
