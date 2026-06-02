from __future__ import annotations

from datetime import datetime, timezone

from wows_analyzer.api.wg_client import WGClient
from wows_analyzer.db.repository import Repository


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


async def refresh_ships(repo: Repository, client: WGClient) -> int:
    page_no = 1
    total = 0

    while True:
        data = await client.get_json(
            "wows/encyclopedia/ships/",
            {
                "fields": "name,tier,type,nation,is_premium",
                "language": "en",
                "page_no": str(page_no),
            },
        )

        ships = data.get("data", {})
        for ship_id, row in ships.items():
            repo.upsert_ship(
                {
                    "ship_id": int(ship_id),
                    "name": row.get("name", "Unknown"),
                    "name_ja": row.get("name"),
                    "tier": int(row.get("tier", 1)),
                    "type": row.get("type", "Unknown"),
                    "nation": row.get("nation"),
                    "is_premium": 1 if row.get("is_premium") else 0,
                    "fetched_at": _utc_now_iso(),
                }
            )
            total += 1

        meta = data.get("meta", {})
        page_total = int(meta.get("page_total", 1))
        if page_no >= page_total:
            break
        page_no += 1

    repo.commit()
    return total
