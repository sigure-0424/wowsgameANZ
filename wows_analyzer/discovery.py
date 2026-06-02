from __future__ import annotations

from pathlib import Path
import shutil

REPLAY_SUBDIRS = ["replays", "profile/replays"]

DEFAULT_ROOTS = [
    r"C:\Games\World_of_Warships",
    r"C:\Games\World_of_Warships_Asia",
    r"C:\Program Files (x86)\Steam\steamapps\common\World of Warships",
    r"C:\Program Files\Steam\steamapps\common\World of Warships",
]


def has_replay_files(path: Path) -> bool:
    return any(path.glob("*.wowsreplay")) if path.exists() else False


def discover_replay_folder(game_root: str | None = None) -> Path | None:
    roots: list[Path] = []
    if game_root:
        roots.append(Path(game_root))
    roots.extend(Path(p) for p in DEFAULT_ROOTS)

    for root in roots:
        if not root.exists():
            continue
        for sub in REPLAY_SUBDIRS:
            candidate = root / sub
            if has_replay_files(candidate):
                return candidate
    return None


def find_latest_build_dir(game_root: Path) -> Path | None:
    bin_dir = game_root / "bin"
    if not bin_dir.exists():
        return None

    numeric_dirs = [p for p in bin_dir.iterdir() if p.is_dir() and p.name.isdigit()]
    if not numeric_dirs:
        return None

    return max(numeric_dirs, key=lambda p: int(p.name))


def populate_versions_dir(game_root: Path, versions_root: Path, last_build_number: int) -> int:
    latest_build = find_latest_build_dir(game_root)
    if latest_build is None:
        return last_build_number

    build_number = int(latest_build.name)
    if build_number <= last_build_number:
        return last_build_number

    source_scripts = latest_build / "res" / "scripts"
    if not source_scripts.exists():
        return last_build_number

    target = versions_root / str(build_number) / "scripts"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source_scripts, target)
    return build_number
