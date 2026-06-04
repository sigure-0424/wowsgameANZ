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
        # Fetch both EN and JA names (JA requires separate request or fetching in JA)
        # To keep it simple, we fetch in JA and use it for name_ja. 
        # Actually WG API allows language parameter.
        
        async def fetch_page(lang: str):
            return await client.get_json(
                "wows/encyclopedia/ships/",
                {
                    "fields": "name,tier,type,nation,is_premium",
                    "language": lang,
                    "page_no": str(page_no),
                },
            )

        data_en = await fetch_page("en")
        data_ja = await fetch_page("ja")

        ships_en = data_en.get("data", {})
        ships_ja = data_ja.get("data", {})
        
        for ship_id, row_en in ships_en.items():
            row_ja = ships_ja.get(ship_id, {})
            repo.upsert_ship(
                {
                    "ship_id": int(ship_id),
                    "name": row_en.get("name", "Unknown"),
                    "name_ja": row_ja.get("name") or row_en.get("name"),
                    "tier": int(row_en.get("tier", 1)),
                    "type": row_en.get("type", "Unknown"),
                    "nation": row_en.get("nation"),
                    "is_premium": 1 if row_en.get("is_premium") else 0,
                    "fetched_at": _utc_now_iso(),
                }
            )
            total += 1

        meta = data_en.get("meta", {})
        page_total = int(meta.get("page_total", 1))
        if page_no >= page_total:
            break
        page_no += 1

    repo.commit()
    return total
