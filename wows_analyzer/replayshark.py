from __future__ import annotations

from pathlib import Path
import zipfile
from typing import Any

import httpx


REPO_LATEST_URL = "https://api.github.com/repos/landaire/wows-toolkit/releases/latest"
REPO_RELEASES_URL = "https://api.github.com/repos/landaire/wows-toolkit/releases"


def _score_windows_zip_asset(name: str) -> int:
    n = name.lower()
    if not n.endswith(".zip"):
        return -1
    score = 0
    if "windows" in n:
        score += 10
    if "wows-toolkit" in n or "wows_toolkit" in n:
        score += 10
    if "x86_64" in n:
        score += 2
    if "gnu" in n:
        score += 1
    return score


def _iter_candidate_assets(release_payload: dict[str, Any]) -> list[dict[str, Any]]:
    assets = release_payload.get("assets", [])
    scored = []
    for asset in assets:
        name = asset.get("name", "")
        score = _score_windows_zip_asset(name)
        if score >= 0:
            scored.append((score, asset))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [asset for _, asset in scored]


def _has_legacy_gnu_asset(release_payload: dict[str, Any]) -> bool:
    assets = release_payload.get("assets", [])
    for asset in assets:
        name = str(asset.get("name", "")).lower()
        if name.endswith("windows-gnu.zip"):
            return True
    return False


def _extract_replayshark_from_zip(zip_path: Path, bin_dir: Path) -> bool:
    with zipfile.ZipFile(zip_path, "r") as zf:
        member = next((n for n in zf.namelist() if n.lower().endswith("replayshark.exe")), None)
        if member is None:
            return False

        zf.extract(member, bin_dir)
        extracted = bin_dir / member
        target = bin_dir / "replayshark.exe"
        target.parent.mkdir(parents=True, exist_ok=True)
        extracted.replace(target)
        return True


def _download_asset(client: httpx.Client, asset: dict[str, Any], target_zip_path: Path) -> None:
    url = asset.get("browser_download_url", "")
    if not url:
        raise RuntimeError("Release asset missing browser_download_url.")
    with client.stream("GET", url) as resp:
        resp.raise_for_status()
        with target_zip_path.open("wb") as f:
            for chunk in resp.iter_bytes(1024 * 1024):
                f.write(chunk)


def _try_release_for_replayshark(
    client: httpx.Client,
    release_payload: dict[str, Any],
    bin_dir: Path,
) -> tuple[bool, str]:
    tag = release_payload.get("tag_name", "")
    candidates = _iter_candidate_assets(release_payload)
    for asset in candidates:
        zip_path = bin_dir / asset["name"]
        _download_asset(client, asset, zip_path)
        try:
            if _extract_replayshark_from_zip(zip_path, bin_dir):
                return True, tag
        finally:
            zip_path.unlink(missing_ok=True)
    return False, tag


def download_replayshark(bin_dir: Path) -> str:
    bin_dir.mkdir(parents=True, exist_ok=True)
    exe_path = bin_dir / "replayshark.exe"
    if exe_path.exists():
        return "already-installed"

    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        release = client.get(REPO_LATEST_URL)
        release.raise_for_status()
        latest_payload = release.json()

        ok, tag = _try_release_for_replayshark(client, latest_payload, bin_dir)
        if ok:
            return tag or "downloaded"

        releases_resp = client.get(REPO_RELEASES_URL, params={"per_page": 100})
        releases_resp.raise_for_status()
        releases = releases_resp.json()
        for rel in releases:
            rel_tag = rel.get("tag_name", "")
            if rel_tag == latest_payload.get("tag_name", ""):
                continue
            if not _has_legacy_gnu_asset(rel):
                continue
            ok, tag = _try_release_for_replayshark(client, rel, bin_dir)
            if ok:
                return tag or rel_tag or "downloaded"

    latest_tag = latest_payload.get("tag_name", "unknown")
    raise RuntimeError(
        "Unable to auto-download replayshark.exe from wows-toolkit releases. "
        f"Latest release ({latest_tag}) does not bundle replayshark.exe. "
        "Build replayshark manually from source (cargo build --release -p replayshark) "
        "and place replayshark.exe in bin/."
    )
