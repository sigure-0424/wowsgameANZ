#!/usr/bin/env python3
import subprocess
from pathlib import Path

replay = Path('E:/SteamLibrary/steamapps/common/World of Warships/replays/20260531_153405_PGSD719-ZH-1_45_Zigzag.wowsreplay')
game_dir = Path('E:/SteamLibrary/steamapps/common/World of Warships')
out_path = Path('test_py.jl')

cmd = [str(Path('./bin/replayshark.exe')), '-g', str(game_dir), 'dump', str(replay), '--output', str(out_path)]
print('Command:', ' '.join(cmd))

result = subprocess.run(cmd, capture_output=True, timeout=120)
print('Return code:', result.returncode)
print('Stdout:', result.stdout[:200] if result.stdout else 'EMPTY')
print('Stderr:', result.stderr[:200] if result.stderr else 'EMPTY')
print('Output file exists:', out_path.exists())
if out_path.exists():
    print('File size:', out_path.stat().st_size)
