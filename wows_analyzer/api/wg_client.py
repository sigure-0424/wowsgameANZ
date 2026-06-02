from __future__ import annotations

import asyncio
from dataclasses import dataclass
import httpx


REGION_BASE_URLS = {
    "ASIA": "https://api.worldofwarships.asia/",
    "EU": "https://api.worldofwarships.eu/",
    "NA": "https://api.worldofwarships.com/",
}


@dataclass
class WGClient:
    app_id: str
    region: str
    delay_ms: int = 100

    def __post_init__(self) -> None:
        if self.region not in REGION_BASE_URLS:
            raise ValueError(f"Unsupported region: {self.region}")
        self.base_url = REGION_BASE_URLS[self.region]

    async def get_json(self, endpoint: str, params: dict) -> dict:
        url = self.base_url.rstrip("/") + "/" + endpoint.lstrip("/")
        full_params = {"application_id": self.app_id, **params}

        retry_waits = [2, 4, 8]
        last_exc: Exception | None = None

        async with httpx.AsyncClient(timeout=30.0) as client:
            for attempt in range(0, 1 + len(retry_waits)):
                try:
                    resp = await client.get(url, params=full_params)
                    if resp.status_code in (429, 500, 502, 503, 504):
                        if attempt < len(retry_waits):
                            await asyncio.sleep(retry_waits[attempt])
                            continue
                    resp.raise_for_status()
                    data = resp.json()
                    if data.get("status") == "error":
                        code = data.get("error", {}).get("code")
                        if code == 407 and attempt < len(retry_waits):
                            await asyncio.sleep(retry_waits[attempt])
                            continue
                    await asyncio.sleep(self.delay_ms / 1000)
                    return data
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    if attempt < len(retry_waits):
                        await asyncio.sleep(retry_waits[attempt])
                        continue
                    break

        raise RuntimeError(f"WG API request failed for {endpoint}: {last_exc}")
