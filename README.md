# WoWS Replay Analyzer

Replay ingestion and causal analysis pipeline for World of Warships `.wowsreplay` files.

## Quick Start

1. Install Python 3.11+.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Configure app:

```bash
python main.py settings --app-id <WG_APP_ID> --region ASIA --game-root "C:\\Games\\World_of_Warships"
```

4. Run pipeline:

```bash
python main.py run
```

5. View outputs under `./wows_analysis/`.

## Commands

- `python main.py run` : scan -> parse -> enrich -> analyze -> export
- `python main.py scan` : discover replay folder and show file count
- `python main.py parse` : parse and store replay event data
- `python main.py enrich` : resolve accounts and win rates via WG API
- `python main.py analyze` : compute battle stats and analysis outputs
- `python main.py export` : write CSV/JSON/HTML report
- `python main.py settings ...` : update config values

## Notes

- Place `replayshark.exe` at `bin/replayshark.exe`, or run `python main.py run` to auto-download.
- The analyzer stores data in `analyzer.db`.
- Win-rate scale is 0-100 percentage points.
