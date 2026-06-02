from __future__ import annotations

from statistics import mean

from wows_analyzer.api.account import account_info_batch
from wows_analyzer.api.wg_client import WGClient


async def get_player_clan_id(client: WGClient, account_id: int) -> int | None:
    data = await client.get_json(
        "wows/clans/accountinfo/",
        {
            "account_id": str(account_id),
            "extra": "clan",
            "fields": "clan_id,clan.tag,clan.name",
        },
    )
    row = data.get("data", {}).get(str(account_id))
    if not row:
        return None
    clan_id = row.get("clan_id")
    return int(clan_id) if clan_id else None


async def get_clan_member_ids(client: WGClient, clan_id: int) -> list[int]:
    data = await client.get_json(
        "wows/clans/info/",
        {
            "clan_id": str(clan_id),
            "extra": "members",
            "fields": "members.account_id",
        },
    )
    row = data.get("data", {}).get(str(clan_id))
    if not row:
        return []
    members = row.get("members", [])
    ids: list[int] = []
    for m in members:
        aid = m.get("account_id")
        if aid:
            ids.append(int(aid))
    return ids


async def get_clan_avg_winrate(client: WGClient, clan_id: int, exclude_account_id: int | None = None) -> float | None:
    member_ids = await get_clan_member_ids(client, clan_id)
    if exclude_account_id is not None:
        member_ids = [m for m in member_ids if m != exclude_account_id]
    if not member_ids:
        return None

    info = await account_info_batch(client, member_ids)
    rates: list[float] = []
    for row in info.values():
        if row.get("hidden_profile"):
            continue
        pvp = ((row.get("statistics") or {}).get("pvp") or {})
        battles = pvp.get("battles") or 0
        wins = pvp.get("wins") or 0
        if battles > 0:
            rates.append((wins / battles) * 100.0)

    if not rates:
        return None
    return float(mean(rates))
