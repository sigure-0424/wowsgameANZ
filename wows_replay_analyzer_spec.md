# WoWS Replay Causal Analysis System — Full Specification

**Version:** 1.0  
**Status:** Design Complete  
**Target Platform:** Windows 11, Python 3.11+  
**Target Game:** World of Warships (Wargaming.net), Asia/EU/NA server  

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Repository & Directory Structure](#2-repository--directory-structure)
3. [TUI Design (nano-like Console Interface)](#3-tui-design-nano-like-console-interface)
4. [Game Root Discovery & Replay Folder Detection](#4-game-root-discovery--replay-folder-detection)
5. [Replay Parsing Layer](#5-replay-parsing-layer)
6. [Database Schema](#6-database-schema)
7. [Wargaming API Enrichment Layer](#7-wargaming-api-enrichment-layer)
8. [Hidden Profile & Clan Win Rate Substitution](#8-hidden-profile--clan-win-rate-substitution)
9. [Ship Dictionary (Tier / Type / Vessel)](#9-ship-dictionary-tier--type--vessel)
10. [Metric Calculation Layer](#10-metric-calculation-layer)
11. [Analysis Classification Axes](#11-analysis-classification-axes)
12. [Causal Analysis Layer](#12-causal-analysis-layer)
13. [Report Screen & Export Layer](#13-report-screen--export-layer)
14. [Configuration & First-Run Flow](#14-configuration--first-run-flow)
15. [replayshark Integration & Version Management](#15-replayshark-integration--version-management)
16. [Error Handling & Edge Cases](#16-error-handling--edge-cases)
17. [Implementation Roadmap](#17-implementation-roadmap)
18. [Technology Stack](#18-technology-stack)
19. [Known Constraints & Open Issues](#19-known-constraints--open-issues)

---

## 1. System Overview

### 1.1 Purpose

This system ingests `.wowsreplay` files produced by World of Warships, extracts structured event data from each battle, enriches it with per-player win rates from the Wargaming public API, and performs statistical causal analysis to determine which numeric factors correlate most strongly with match outcome (win/loss).

### 1.2 Key Analytical Goals

- Quantify the relationship between the player's own performance (damage, K/D, survival) and win probability.
- Quantify the relationship between team-average win rates (allied and enemy) and match outcome.
- Identify which individual team members (worst, best ranked by win rate) have the highest leverage on outcome.
- Analyze sinking pace (team destruction rate over time) and its predictive power.
- Slice all of the above by **Tier band**, **ship type**, and **individual vessel**.

### 1.3 Scope Boundaries

| In Scope | Out of Scope |
|---|---|
| `.wowsreplay` files on local disk | Live game overlay |
| Random Battle mode (default) | Replays from other WG titles |
| Wargaming public API (no OAuth) | Private/authenticated API fields |
| Windows 11 local execution | Cloud deployment |
| Asia / EU / NA servers | CIS (Lesta) server |

### 1.4 Win Rate Scale Convention

- All win-rate values use a **0-100 percent scale** (not 0.0-1.0 ratio).
- `winrate_delta` is expressed in **percentage points** (`ally_avg_winrate - enemy_avg_winrate`).

---

## 2. Repository & Directory Structure

```
wows-analyzer/
├── main.py                  # TUI entry point
├── config.json              # User settings (APP_ID, game root, server region, etc.)
├── analyzer.db              # SQLite database (auto-created)
├── wows_analyzer/
│   ├── tui/
│   │   ├── screen_main.py
│   │   ├── screen_settings.py
│   │   ├── screen_filter.py
│   │   ├── screen_report.py
│   │   └── screen_export.py
│   ├── parser/
│   │   ├── meta_parser.py       # JSON meta block extraction
│   │   ├── packet_parser.py     # replayshark subprocess + event normalization
│   │   └── battle_result.py     # Win/loss detection logic
│   ├── api/
│   │   ├── wg_client.py         # Wargaming API HTTP client (httpx async)
│   │   ├── account.py           # account/search, account/info
│   │   ├── clans.py             # clans/accountinfo, clans/info
│   │   └── encyclopedia.py      # encyclopedia/ships
│   ├── db/
│   │   ├── schema.py            # CREATE TABLE statements
│   │   └── repository.py        # Insert/query helpers
│   ├── metrics/
│   │   ├── per_battle.py        # battle_stats row computation
│   │   ├── sink_pace.py         # 5-minute bucket sinking snapshots
│   │   └── dd_metrics.py        # Destroyer-specific extra metrics
│   ├── analysis/
│   │   ├── correlation.py       # Pearson r, biserial correlation
│   │   ├── regression.py        # Logistic regression (statsmodels)
│   │   └── segment.py           # Tier / type / vessel slicing
│   └── export/
│       ├── csv_export.py
│       ├── json_export.py
│       └── html_report.py       # plotly-based HTML report
├── bin/
│   └── replayshark.exe          # Pre-built binary (auto-downloaded on first run)
└── versions/                    # replayshark game script data (auto-populated)
    └── {build_number}/
        └── scripts/
```

---

## 3. TUI Design (nano-like Console Interface)

### 3.1 Layout Principles

- Built with Python **curses** (stdlib) or **Textual** library.
- Fixed header bar: application name + live replay count.
- Fixed footer bar: always-visible keybinding legend (identical pattern to GNU nano).
- Scrollable main area for status and content.
- All screens are full-terminal replacements; no sub-windows or overlapping panels.

### 3.2 Main Screen Layout

```
┌─────────────────────────────────────────────────────────────┐
│ WoWS Replay Analyzer v1.0                  [replays: 142]   │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  [SCAN]    Root directory : C:\Games\World_of_Warships      │
│            Replay folder  : ...\replays\      [142 files]   │
│                                                             │
│  [PARSE]   Parsed: 138 / 142    Parse errors: 4             │
│            Incomplete replays: 2  (win/loss unknown)        │
│                                                             │
│  [ENRICH]  Players resolved : 1,823                         │
│            Hidden profiles  : 47                            │
│              └ Clan average used : 31                       │
│              └ Excluded (no clan): 16                       │
│                                                             │
│  [ANALYZE] ▓▓▓▓▓▓▓▓░░  80%   (110 / 138 battles)           │
│                                                             │
│  [REPORT]  Last run: 2025-06-01 10:33:12                    │
│            Output  : ./wows_analysis/                       │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│ ^X Exit   ^S Settings   ^F Filter   ^R Report   ^E Export   │
│ ^P Parse  ^A Analyze    ^U API Sync ^? Help                  │
└─────────────────────────────────────────────────────────────┘
```

### 3.3 Screen Map

```
[Main Screen]
    ├── ^S ──> [Settings Screen]
    ├── ^F ──> [Filter Screen]
    ├── ^R ──> [Report Screen]
    └── ^E ──> [Export Screen]
```

### 3.4 Settings Screen

Fields (navigated with arrow keys, edited in-place):

| Field | Type | Description |
|---|---|---|
| `Game Root Directory` | Path string | Full path to WoWS installation root |
| `WG Application ID` | String | Developer Room APP_ID |
| `Server Region` | Select [ASIA / EU / NA] | Determines API base URL |
| `Default Game Mode Filter` | Multi-select | RandomBattle (default ON), RankedBattle, Cooperative, Clan |
| `Min Battles for Stats` | Integer (default: 30) | Suppress correlation output below this threshold |
| `API Request Delay (ms)` | Integer (default: 100) | Throttle between WG API calls |
| `Cache TTL (hours)` | Integer (default: 24) | Player/clan win rate cache lifetime |

Keybindings: `^S` Save & return, `^X` Cancel, `Arrow keys` / `Tab` Navigate fields.

### 3.5 Filter Screen

```
Period          : [All] / Last 30d / Last 90d / Custom
Tier            : [All] / T4 / T5 / T6 / T7 / T8 / T9 / T10 / T11
                  Tier band: Low(T1-5) / Mid(T6-8) / High(T9-11)
Ship Type       : [All] / DD / CA / BB / CV / SS
Ship Name       : (text search)
Game Mode       : [Random] / Ranked / Coop / Clan
Map             : [All] / (list from parsed replays)
Own Ship Tier   : (same as Tier above, but only own ship)
```

Active filters are displayed in a status line on the main screen.

### 3.6 Report Screen

Full-terminal scrollable text view of the last analysis output. Sections are collapsible (toggle with `Enter`). Navigation: `Arrow keys` scroll, `PgUp`/`PgDn` fast scroll, `^F` search text, `^X` return to main.

### 3.7 Export Screen

```
Export Format:  ( ) CSV   ( ) JSON   (*) HTML (recommended)
Output Path:    ./wows_analysis/
Include raw battle_stats table: [Y]
Include per-ship breakdown:     [Y]
Include correlation tables:     [Y]
Include regression summary:     [Y]

[^E Execute Export]  [^X Cancel]
```

---

## 4. Game Root Discovery & Replay Folder Detection

### 4.1 Candidate Paths

Searched in order:

```python
REPLAY_SUBDIRS = [
    "replays",
    "profile/replays",
]

DEFAULT_ROOTS = [
    r"C:\Games\World_of_Warships",
    r"C:\Games\World_of_Warships_Asia",
    r"C:\Program Files (x86)\Steam\steamapps\common\World of Warships",
    r"C:\Program Files\Steam\steamapps\common\World of Warships",
]
```

### 4.2 Detection Condition

A directory qualifies as a valid replay folder if it contains at least one file matching `*.wowsreplay`.

### 4.3 Manual Override

If automatic detection fails, the TUI prompts the user to enter the path manually on first run and saves it to `config.json`.

### 4.4 replayshark `versions/` Population

The `versions/` directory required by replayshark is populated automatically:

1. Locate `{game_root}/bin/` and find the highest-numbered subdirectory (latest build).
2. Copy `{build_dir}/res/scripts/` to `versions/{build_number}/scripts/`.
3. On each run, compare the current build number to the last-used build number stored in `config.json`. If newer, re-copy.

---

## 5. Replay Parsing Layer

### 5.1 `.wowsreplay` File Format

```
[4 bytes LE uint32]  : Size of JSON Meta Block 1
[N bytes]            : Meta Block 1 — UTF-8 JSON (player list, map, date, mode)
[4 bytes LE uint32]  : Number of additional JSON blocks (usually 0 or 1)
[4 bytes LE uint32]  : Size of JSON Meta Block 2 (may be 0)
[M bytes]            : Binary packet stream — all in-battle events
```

### 5.2 Meta Block Fields Extracted

```json
{
  "playerName":    "NEKO_KID",
  "playerVehicle": "PJSD012",
  "dateTime":      "2025-06-01 10:22:33",
  "duration":      1145,
  "mapName":       "42_Neighbors",
  "mapDisplayName":"Neighbors",
  "gameMode":      "RandomBattle",
  "vehicles": [
    {
      "shipId":       4291845072,
      "shipParamsId": 4289607376,
      "relation":     0,
      "name":         "NEKO_KID",
      "id":           576272
    }
  ]
}
```

`relation` values: `0` = own ship, `1` = ally, `2` = enemy.

`winnerTeamId` is **not** present in the meta block. It must be inferred from the packet stream (see §5.5).

### 5.3 Parsing Tool: replayshark

replayshark is invoked as a subprocess:

```bash
replayshark dump --input battle.wowsreplay --output battle.jl
```

Output is a JSON Lines (`.jl`) file. Each line is one JSON object:

```json
{"clock": 142.5, "payload": {"DamageReceived": {"victim": 576272, "aggressors": [{"aggressor": 576266, "damage": 3335.0}]}}}
{"clock": 203.1, "payload": {"EntityDestroyed": {"entity_id": 576266}}}
```

The first line of the `.jl` file is the JSON-encoded meta block.

### 5.4 Packet Types Extracted

| Packet Type | Key Fields | Usage |
|---|---|---|
| `DamageReceived` | `victim`, `aggressors[].aggressor`, `aggressors[].damage`, `clock` | Damage timeline per player |
| `EntityDestroyed` (or equivalent sink event) | `entity_id`, `clock` | Sinking event timestamp |
| `OnRibbon` / `RibbonReceived` | `ribbon_type`, `clock` | Kill / torp hit / fire / etc. |
| `HealthUpdate` | `entity_id`, `health`, `clock` | HP timeline |
| `Position` | `entity_id`, `x`, `y`, `z`, `clock` | Spatial data (for cap zone estimation) |
| `BattleResult` | `winner_team_id`, `reason` | Win/loss determination |

### 5.5 Win/Loss Detection

**Primary method:** Extract `BattleResult` packet from packet stream. Field `winner_team_id` indicates which team (0 or 1) won.

**Fallback method (if `BattleResult` not found):** At end of stream, check `EntityDestroyed` events. If all entities of team A were destroyed before all entities of team B, team B wins.

**Incomplete replay flag:** If neither method resolves win/loss (e.g., replay was cut short mid-game), set `winner_team = NULL` and `is_incomplete = 1`. Incomplete replays are excluded from win/loss analysis but included in damage/metric analysis.

### 5.6 Kill Attribution

A kill is attributed to the aggressor who delivered the final `DamageReceived` event against a victim before that victim appears in `EntityDestroyed`. Implemented as: for each sink event, look back through `damage_events` for the most recent `aggressor` targeting that `entity_id`.

### 5.7 Duplicate Replay Detection

A replay is identified by a hash computed from:

```python
hash_key = sha256(f"{meta['dateTime']}|{meta['mapName']}|{meta['playerName']}").hexdigest()
```

If this hash already exists in the `battles` table, the file is skipped on re-import.

---

## 6. Database Schema

All data is stored in a single SQLite file (`analyzer.db`).

### 6.1 `battles`

```sql
CREATE TABLE battles (
    replay_hash     TEXT PRIMARY KEY,
    file_path       TEXT NOT NULL,
    date            TEXT NOT NULL,       -- ISO 8601
    map_name        TEXT,
    game_mode       TEXT,
    duration_s      INTEGER,
    winner_team     INTEGER,             -- 0 or 1; NULL if unknown
    own_team        INTEGER,             -- which team the recording player is on
    is_incomplete   INTEGER DEFAULT 0,  -- 1 if BattleResult not found
    imported_at     TEXT                -- ISO 8601 timestamp of import
);
```

### 6.2 `players`

```sql
CREATE TABLE players (
    replay_hash     TEXT NOT NULL,
    entity_id       INTEGER NOT NULL,
    name            TEXT NOT NULL,
    ship_id         INTEGER,            -- shipParamsId from meta
    team            INTEGER,            -- 0=ally(own team), 1=enemy
    relation        INTEGER,            -- 0=own ship, 1=ally, 2=enemy
    wg_account_id   INTEGER,
    win_rate        REAL,               -- 0.0-100.0 (%); NULL if unresolvable
    win_rate_source TEXT,               -- 'direct' | 'clan_avg' | 'excluded'
    battles_total   INTEGER,
    clan_id         INTEGER,
    PRIMARY KEY (replay_hash, entity_id)
);
```

### 6.3 `damage_events`

```sql
CREATE TABLE damage_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    replay_hash TEXT NOT NULL,
    clock       REAL NOT NULL,
    aggressor   INTEGER NOT NULL,
    victim      INTEGER NOT NULL,
    damage      REAL NOT NULL
);
CREATE INDEX idx_damage_replay ON damage_events(replay_hash);
```

### 6.4 `sink_events`

```sql
CREATE TABLE sink_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    replay_hash TEXT NOT NULL,
    clock       REAL NOT NULL,
    entity_id   INTEGER NOT NULL,
    team        INTEGER NOT NULL
);
CREATE INDEX idx_sink_replay ON sink_events(replay_hash);
```

### 6.5 `ships`

Ship dictionary, populated from WG Encyclopedia API and cached.

```sql
CREATE TABLE ships (
    ship_id     INTEGER PRIMARY KEY,  -- shipParamsId
    name        TEXT NOT NULL,
    name_ja     TEXT,
    tier        INTEGER NOT NULL,
    type        TEXT NOT NULL,        -- 'Destroyer'|'Cruiser'|'Battleship'|'AirCarrier'|'Submarine'
    nation      TEXT,
    is_premium  INTEGER DEFAULT 0,
    fetched_at  TEXT                  -- ISO 8601; for cache invalidation
);
```

### 6.6 `battle_stats`

One row per battle. Computed from the raw event tables.

```sql
CREATE TABLE battle_stats (
    replay_hash             TEXT PRIMARY KEY,
    -- Outcome
    won                     INTEGER,        -- 1=win, 0=loss, NULL=unknown
    -- Own ship identity
    own_ship_id             INTEGER,
    own_ship_name           TEXT,
    own_ship_tier           INTEGER,
    own_ship_type           TEXT,
    own_tier_disadvantage   INTEGER,        -- max_tier_in_match - own_tier
    -- Own performance
    own_damage              REAL,
    own_kills               INTEGER,
    own_deaths              INTEGER,        -- 0 or 1
    own_kd                  REAL,
    own_survived            INTEGER,
    own_damage_per_min      REAL,
    own_dmg_share           REAL,           -- own_damage / (own + ally total)
    -- DD-specific (NULL if not DD)
    own_torp_hits           INTEGER,
    own_spotting_damage     REAL,
    own_cap_time_estimate   REAL,
    own_smoke_deployed      INTEGER,
    -- Allied team
    ally_count              INTEGER,
    ally_avg_winrate        REAL,
    ally_winrate_top        REAL,
    ally_winrate_worst      REAL,
    ally_winrate_std        REAL,
    ally_hidden_count       INTEGER,
    ally_total_damage       REAL,
    ally_kills              INTEGER,
    ally_survival_count     INTEGER,
    -- Enemy team
    enemy_count             INTEGER,
    enemy_avg_winrate       REAL,
    enemy_winrate_top       REAL,
    enemy_winrate_worst     REAL,
    enemy_winrate_std       REAL,
    enemy_hidden_count      INTEGER,
    enemy_total_damage      REAL,
    enemy_kills             INTEGER,
    enemy_survival_count    INTEGER,
    -- Differential metrics
    winrate_delta           REAL,   -- percentage points: ally_avg - enemy_avg
    damage_delta            REAL,
    kill_delta              INTEGER,
    -- Sinking pace snapshots (ally sinks - enemy sinks at t minutes)
    sink_delta_t5           INTEGER,
    sink_delta_t10          INTEGER,
    sink_delta_t15          INTEGER,
    sink_delta_t20          INTEGER,
    -- Map / match context
    map_name                TEXT,
    game_mode               TEXT,
    date                    TEXT
);
```

### 6.7 `api_cache`

```sql
CREATE TABLE api_cache (
    key         TEXT PRIMARY KEY,   -- e.g. 'player:3002507436' or 'clan:12345'
    value       TEXT NOT NULL,      -- JSON string
    fetched_at  TEXT NOT NULL       -- ISO 8601
);
```

---

## 7. Wargaming API Enrichment Layer

### 7.1 Server Region Configuration

| Region | Base URL |
|---|---|
| ASIA | `https://api.worldofwarships.asia/` |
| EU | `https://api.worldofwarships.eu/` |
| NA | `https://api.worldofwarships.com/` |

The region is set in `config.json` and applies to all API calls.

### 7.2 API Endpoints Used

#### Account Search (name → account_id)

```
GET {base}wows/account/search/
    ?application_id={APP_ID}
    &search={player_name}
    &type=exact
    &fields=account_id,nickname
```

#### Player Personal Data (account_id → stats + hidden flag)

Up to 100 account IDs per request (comma-separated).

```
GET {base}wows/account/info/
    ?application_id={APP_ID}
    &account_id={id1,id2,...}
    &fields=account_id,nickname,hidden_profile,statistics.pvp.wins,statistics.pvp.battles
```

Response fields of interest:

- `hidden_profile` (boolean) — if `true`, `statistics` is null.
- `statistics.pvp.wins` / `statistics.pvp.battles` — used to compute `win_rate` as `(wins / battles) * 100`.

#### Clan Membership (account_id → clan_id)

```
GET {base}wows/clans/accountinfo/
    ?application_id={APP_ID}
    &account_id={id}
    &extra=clan
    &fields=clan_id,clan.tag,clan.name
```

#### Clan Member List (clan_id → member account_ids)

```
GET {base}wows/clans/info/
    ?application_id={APP_ID}
    &clan_id={clan_id}
    &extra=members
    &fields=members.account_id
```

#### Ship Encyclopedia (all ships → tier/type/name)

```
GET {base}wows/encyclopedia/ships/
    ?application_id={APP_ID}
    &fields=name,tier,type,nation,is_premium
    &language=en
    &page_no={n}
```

Paginated; iterate until `meta.page_total` is exhausted.

### 7.3 Rate Limiting & Retry

- Default inter-request delay: 100 ms (configurable).
- Wargaming enforces ~10 requests/second for free application IDs.
- On HTTP 429 or error code `REQUEST_LIMIT_EXCEEDED`: exponential backoff (2s, 4s, 8s), max 3 retries.
- On HTTP 5xx: retry up to 2 times with 5s delay.

### 7.4 Caching Strategy

- Player stats are cached in `api_cache` with key `player:{account_id}`.
- Clan average win rates are cached with key `clan_avg:{clan_id}`.
- Default TTL: 24 hours. On cache hit within TTL, no API call is made.
- On first run or expired cache, the full enrichment pipeline runs.

---

## 8. Hidden Profile & Clan Win Rate Substitution

### 8.1 Decision Tree

```
wows/account/info → hidden_profile?
│
├── false  ─→  win_rate = (wins / battles) * 100
│              win_rate_source = 'direct'
│
└── true   ─→  wows/clans/accountinfo → clan_id?
               │
               ├── clan_id present
               │       ├── fetch clan member account_ids
               │       ├── batch-fetch all member stats (skip hidden members)
               │       ├── clan_avg = mean(non-hidden member win_rates)
               │       └── win_rate = clan_avg
               │           win_rate_source = 'clan_avg'
               │
               └── clan_id absent (no clan)
                       └── win_rate = NULL
                           win_rate_source = 'excluded'
```

### 8.2 Impact on Aggregated Metrics

When computing `ally_avg_winrate` or `enemy_avg_winrate`:

- Players with `win_rate_source = 'direct'` or `'clan_avg'` are included.
- Players with `win_rate_source = 'excluded'` are **omitted** from the average.
- `ally_hidden_count` / `enemy_hidden_count` fields in `battle_stats` record how many were excluded for transparency.

### 8.3 Clan Average Caching

Once computed for a given `clan_id`, the clan average is cached in `api_cache` with key `clan_avg:{clan_id}`. This avoids refetching all members' stats for every hidden player in the same clan.

---

## 9. Ship Dictionary (Tier / Type / Vessel)

### 9.1 Ship Types

| API `type` value | Display name | Abbreviation |
|---|---|---|
| `Destroyer` | Destroyer | DD |
| `Cruiser` | Cruiser | CA/CL |
| `Battleship` | Battleship | BB |
| `AirCarrier` | Aircraft Carrier | CV |
| `Submarine` | Submarine | SS |

### 9.2 Dictionary Population

The `ships` table is populated on first run by paginating through `wows/encyclopedia/ships/`. It is refreshed when:

- The `ships` table is empty.
- The most recent `fetched_at` value is older than 7 days.
- The user triggers a manual refresh from the Settings screen.

### 9.3 Ship Lookup from Replay

The meta block provides `shipParamsId` per vehicle. This maps directly to `ships.ship_id`. If a `shipParamsId` is not found in the dictionary (e.g., a new ship added after the last refresh), a background refresh is triggered and the replay is re-analyzed after it completes.

### 9.4 Tier Disadvantage Metric

For each battle:

```python
max_tier = max(ships[v.ship_id].tier for v in vehicles if ship known)
own_tier = ships[own_ship_id].tier
tier_disadvantage = max_tier - own_tier
```

`tier_disadvantage = 0` means the player is in a top-tier ship; `tier_disadvantage = 2` means the player is the lowest tier in a T+2 spread match.

---

## 10. Metric Calculation Layer

### 10.1 Own-Ship Metrics

| Metric | Formula / Source |
|---|---|
| `own_damage` | Sum of `damage_events.damage` where `aggressor = own_entity_id` |
| `own_kills` | Count of `sink_events` where final aggressor = `own_entity_id` |
| `own_deaths` | 1 if `own_entity_id` in `sink_events`, else 0 |
| `own_kd` | `own_kills / max(own_deaths, 1)` |
| `own_survived` | `1 - own_deaths` |
| `own_damage_per_min` | `own_damage / (duration_s / 60)` |
| `own_dmg_share` | `own_damage / (own_damage + ally_total_damage)` |

### 10.2 Destroyer-Specific Metrics

These are populated only when `own_ship_type = 'Destroyer'`. Populated from ribbon packets where available; otherwise `NULL`.

| Metric | Source |
|---|---|
| `own_torp_hits` | Count of `TorpedoHit` ribbons for own entity |
| `own_spotting_damage` | Sum of spotting damage events (if available in packet stream) |
| `own_cap_time_estimate` | Estimated from position proximity to capture zone coordinates (map-dependent) |
| `own_smoke_deployed` | Count of smoke deployment events |

### 10.3 Allied Team Metrics

Computed over all players where `team = 0 AND relation != 0` (allies, excluding own ship):

| Metric | Formula |
|---|---|
| `ally_count` | Count of allied players |
| `ally_avg_winrate` | Mean of non-excluded `win_rate` values (0-100 %) |
| `ally_winrate_top` | Max `win_rate` among allies (0-100 %) |
| `ally_winrate_worst` | Min `win_rate` among allies (0-100 %) |
| `ally_winrate_std` | Standard deviation of allied win rates |
| `ally_hidden_count` | Count where `win_rate_source = 'excluded'` |
| `ally_total_damage` | Sum of `own_damage` equivalent for each ally |
| `ally_kills` | Count of sink events attributed to any ally |
| `ally_survival_count` | Count of allies not in `sink_events` at battle end |

### 10.4 Enemy Team Metrics

Same formulas as Allied, computed over `team = 1`.

### 10.5 Differential Metrics

| Metric | Formula |
|---|---|
| `winrate_delta` | `ally_avg_winrate - enemy_avg_winrate` (percentage points) |
| `damage_delta` | `(ally_total_damage + own_damage) - enemy_total_damage` |
| `kill_delta` | `(ally_kills + own_kills) - enemy_kills` |

### 10.6 Sinking Pace Snapshots

For each battle, compute the net sink count delta at each 5-minute mark:

```python
def sink_delta_at(t_seconds, replay_hash):
    ally_sinks  = COUNT(sink_events WHERE team=0 AND clock <= t_seconds)
    enemy_sinks = COUNT(sink_events WHERE team=1 AND clock <= t_seconds)
    return ally_sinks - enemy_sinks
    # Negative = allied team is being sunk faster
    # Positive = enemy team is being sunk faster
```

Computed for t = 300, 600, 900, 1200 seconds (5, 10, 15, 20 minutes).

---

## 11. Analysis Classification Axes

All analyses in §12 are executed separately within each of the following slices:

### 11.1 Tier Band

| Band | Tiers |
|---|---|
| All | T1–T11 |
| Low | T1–T5 |
| Mid | T6–T8 |
| High | T9–T11 |
| Single tier | T4, T5, T6, T7, T8, T9, T10, T11 individually |

Slicing is on `own_ship_tier`.

### 11.2 Ship Type

Slicing on `own_ship_type`:

- All types combined
- Destroyer (DD)
- Cruiser (CA/CL)
- Battleship (BB)
- Aircraft Carrier (CV)
- Submarine (SS)

### 11.3 Individual Vessel

Slicing on `own_ship_name`. Vessels with fewer than `min_battles` (default: 30) battles display raw data only; correlation coefficients are suppressed with a "Insufficient data (n={count})" warning.

### 11.4 Map (Supplementary)

Slicing on `map_name`. Useful for identifying maps where DD performance diverges from average. Available as an optional filter rather than a primary report axis.

### 11.5 Game Mode

Default filter: `RandomBattle` only. Other modes can be enabled via the Filter screen. Win rate comparisons are not valid across different game modes and must not be mixed.

---

## 12. Causal Analysis Layer

### 12.1 Correlation Analysis

For each slice defined in §11, compute Pearson correlation coefficients between each numeric metric and `won` (binary 0/1):

```python
from scipy import stats

metrics = [
    'own_damage', 'own_kills', 'own_kd', 'own_survived', 'own_dmg_share',
    'ally_avg_winrate', 'ally_winrate_top', 'ally_winrate_worst',
    'enemy_avg_winrate', 'enemy_winrate_worst',
    'winrate_delta', 'damage_delta', 'kill_delta',
    'sink_delta_t5', 'sink_delta_t10', 'sink_delta_t15',
    'tier_disadvantage',
]

results = {}
for metric in metrics:
    r, p = stats.pearsonr(df[metric].dropna(), df['won'].loc[df[metric].notna()])
    results[metric] = {'r': r, 'p': p, 'n': len(df[metric].dropna())}
```

Output sorted by `|r|` descending. p-values reported; metrics with `p > 0.05` are flagged as "not significant at 5% level."

### 12.2 Point-Biserial Correlation

For binary metrics (`own_survived`, `is_incomplete`):

```python
from scipy.stats import pointbiserialr
r, p = pointbiserialr(df['own_survived'], df['won'])
```

### 12.3 Conditional Win Rate Tables

#### Sinking Pace Advantage

For each `sink_delta_t5` threshold value:

| `sink_delta_t5` | Win Rate | N |
|---|---|---|
| ≤ -3 | X.X% | n |
| -2 | X.X% | n |
| -1 | X.X% | n |
| 0 | X.X% | n |
| +1 | X.X% | n |
| +2 | X.X% | n |
| ≥ +3 | X.X% | n |

#### Win Rate Delta Buckets

`winrate_delta` bucketed in 2 percentage-point increments:

| Bucket | Win Rate | N |
|---|---|---|
| < -8% | X.X% | n |
| -8% to -4% | X.X% | n |
| -4% to 0% | X.X% | n |
| 0% to +4% | X.X% | n |
| +4% to +8% | X.X% | n |
| > +8% | X.X% | n |

#### Allied Worst Win Rate Leverage

Conditional win rate grouped by `ally_winrate_worst` percentile:

- Bottom 10% (≤ 40% win rate player on own team)
- 10–25%
- 25–75%
- Top 10% (≥ 65%)

### 12.4 Logistic Regression

Multivariate analysis with `won` as target:

```python
import statsmodels.formula.api as smf

formula = (
    "won ~ own_damage + own_survived + winrate_delta"
    " + ally_winrate_worst + enemy_winrate_worst"
    " + sink_delta_t5 + tier_disadvantage"
)
model = smf.logit(formula, data=df).fit()
```

Output: coefficient, odds ratio (`exp(coef)`), 95% CI, p-value for each predictor. Pseudo-R² (McFadden) reported as overall model fit.

### 12.5 Per-Vessel Summary

For each vessel with sufficient data (n ≥ `min_battles`):

```
Vessel: Shimakaze  (n=47)
  Win rate          : 54.3%
  Avg damage        : 48,320
  Avg K/D           : 1.21
  Avg torp hits     : 3.4
  Win corr top-3:
    1. own_damage          r = +0.41  p < 0.001
    2. sink_delta_t5       r = +0.38  p < 0.001
    3. ally_winrate_worst  r = +0.29  p = 0.003
  Team context (wins vs losses):
    ally_avg_winrate  WIN: 51.2%   LOSS: 49.1%
    enemy_avg_winrate WIN: 49.3%   LOSS: 51.4%
```

---

## 13. Report Screen & Export Layer

### 13.1 Report Screen Sections

Displayed in TUI Report Screen (^R), all sections collapsible:

1. **Overview** — total battles, date range, filters applied, data quality notes
2. **Win Rate Correlations** — sorted table of Pearson r × `won`
3. **Conditional Win Rate Tables** — sinking pace, winrate delta buckets
4. **Logistic Regression Summary** — odds ratios, p-values, pseudo-R²
5. **By Tier Band** — repeat correlation summary for Low/Mid/High
6. **By Ship Type** — repeat for DD/CA/BB/CV/SS
7. **By Vessel** — per-ship summaries (sorted by battle count desc)
8. **Data Quality** — hidden profile counts, incomplete replays, API error counts

### 13.2 CSV Export

Files written to `{output_path}/csv/`:

| File | Contents |
|---|---|
| `battle_stats.csv` | One row per battle, all `battle_stats` columns |
| `correlation_results.csv` | metric, r, p, n per slice |
| `sink_pace.csv` | replay_hash, t5, t10, t15, t20 deltas |
| `per_vessel.csv` | vessel summary rows |

### 13.3 JSON Export

`analysis_results.json` — full nested structure:

```json
{
  "metadata": { "generated_at": "...", "filters": {...}, "n_battles": 138 },
  "overall": { "correlations": [...], "regression": {...} },
  "by_tier": { "T10": { "correlations": [...] }, ... },
  "by_type": { "Destroyer": { "correlations": [...] }, ... },
  "by_vessel": { "Shimakaze": { "n": 47, "correlations": [...] }, ... }
}
```

### 13.4 HTML Report

`report.html` — single self-contained file with embedded Plotly charts:

- Correlation bar chart (sorted by |r|)
- Conditional win rate line charts (sinking pace vs win rate)
- Win rate delta heatmap (ally avg × enemy avg, colored by win rate)
- Per-vessel scatter plot (avg damage × win rate, bubble size = n)
- All correlation tables rendered as HTML with sortable columns

---

## 14. Configuration & First-Run Flow

### 14.1 `config.json` Structure

```json
{
  "app_id": "",
  "server_region": "ASIA",
  "game_root": "",
  "replay_folder": "",
  "last_build_number": 0,
  "min_battles_for_stats": 30,
  "api_delay_ms": 100,
  "cache_ttl_hours": 24,
  "default_game_mode_filter": ["RandomBattle"],
  "output_path": "./wows_analysis/"
}
```

### 14.2 First-Run Setup Screen

Displayed automatically if `app_id` is empty or `game_root` is empty:

```
┌──────────────────────────────────────────────────────────┐
│ First Run Setup                                          │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  Step 1: Wargaming Application ID                        │
│  Register at: https://developers.wargaming.net/          │
│  (Create application → copy Application ID)              │
│                                                          │
│  APP_ID > [                              ]               │
│                                                          │
│  Step 2: Server Region                                   │
│  Region > [ ASIA ] (Tab to change)                       │
│                                                          │
│  Step 3: WoWS Game Root Directory                        │
│  Detected: C:\Games\World_of_Warships  [OK]              │
│  Override > [                              ]             │
│                                                          │
│  Step 4: Download replayshark binary                     │
│  Source: github.com/landaire/wows-toolkit/releases       │
│  [^D Download now]   [^S Skip (use existing)]            │
│                                                          │
├──────────────────────────────────────────────────────────┤
│ ^S Save & Continue   ^X Exit                             │
└──────────────────────────────────────────────────────────┘
```

---

## 15. replayshark Integration & Version Management

### 15.1 Binary Acquisition

On first run (or if `bin/replayshark.exe` is absent), the system:

1. Fetches the latest release metadata from:  
   `https://api.github.com/repos/landaire/wows-toolkit/releases/latest`
2. Downloads the asset matching `wows-toolkit_v*_x86_64-pc-windows-gnu.zip`.
3. Extracts `replayshark.exe` to `bin/`.
4. Stores the release tag in `config.json` as `replayshark_version`.

### 15.2 Version Staleness Check

On each run, the system compares the installed game build number against `config.json` `last_build_number`. If the build has advanced:

1. Re-copy `{game_root}/bin/{new_build}/res/scripts/` to `versions/{new_build}/scripts/`.
2. Update `last_build_number` in `config.json`.

If replayshark fails to parse a replay due to an unknown packet (returns parse error), the system logs the version mismatch and marks the replay as `is_incomplete = 1` with error reason `"version_mismatch"`.

### 15.3 replayshark Invocation

```python
import subprocess, json

def run_replayshark(replay_path: str, jl_output_path: str) -> bool:
    result = subprocess.run(
        ["bin/replayshark.exe", "dump",
         "--input", replay_path,
         "--output", jl_output_path],
        capture_output=True, timeout=60
    )
    return result.returncode == 0
```

---

## 16. Error Handling & Edge Cases

### 16.1 Parse Errors

| Condition | Handling |
|---|---|
| replayshark exits non-zero | Log error, mark replay as `parse_error`, skip |
| Meta JSON malformed | Log, skip |
| `shipParamsId` not in `ships` dict | Trigger background encyclopedia refresh; re-analyze after |
| No `BattleResult` packet | Fall back to all-sunk detection; if still unresolved, `winner_team = NULL` |
| Replay truncated mid-game | Set `is_incomplete = 1`; include in metric stats, exclude from win/loss analysis |

### 16.2 API Errors

| Condition | Handling |
|---|---|
| Player name not found | `wg_account_id = NULL`, `win_rate_source = 'excluded'` |
| `REQUEST_LIMIT_EXCEEDED` | Exponential backoff; retry up to 3 times |
| `HIDDEN_PROFILE` in stats response | Proceed to clan lookup flow (§8) |
| Clan member batch returns 0 non-hidden | `win_rate_source = 'excluded'` for that player |
| Network timeout | Log, cache miss recorded; retry on next run |

### 16.3 Statistical Edge Cases

| Condition | Handling |
|---|---|
| n < `min_battles_for_stats` | Suppress correlation output; display raw counts only with warning |
| All battles won or all lost for a slice | Pearson r is undefined; report "Insufficient variance (win rate: 100% or 0%)" |
| Metric has >50% NULL values | Report null rate alongside correlation; flag as potentially unreliable |

---

## 17. Implementation Roadmap

### Priority P0 — Core Pipeline (Required for any output)

1. TUI skeleton: main screen, settings screen, curses/Textual layout
2. Game root scan: replay folder detection, `config.json` read/write
3. replayshark auto-download and invocation
4. `versions/` population from game install
5. Meta block parser → `battles` + `players` tables
6. `ships` table population from WG Encyclopedia API
7. SQLite schema initialization

### Priority P1 — Event Parsing & Enrichment

8. Packet parser: `DamageReceived`, `EntityDestroyed`, `BattleResult`
9. Kill attribution logic
10. Win/loss detection (primary + fallback)
11. WG API client: `account/search`, `account/info` (batch)
12. Hidden profile → clan lookup flow
13. Clan average win rate computation + caching

### Priority P2 — Metrics & Classification

14. `battle_stats` row computation (all metrics in §10)
15. Sinking pace snapshot computation
16. DD-specific metrics
17. Tier disadvantage computation
18. Filter screen implementation

### Priority P3 — Analysis & Output

19. Pearson correlation + p-value computation per slice
20. Conditional win rate tables
21. Logistic regression (statsmodels)
22. Per-vessel summary generation
23. Report screen (TUI scrollable view)
24. CSV / JSON / HTML export

---

## 18. Technology Stack

| Component | Library / Tool | Notes |
|---|---|---|
| TUI framework | `curses` (stdlib) or `Textual` | Textual preferred for maintainability |
| Replay parsing | `replayshark` (Rust CLI, subprocess) | Invoked via `subprocess.run` |
| HTTP client | `httpx` (async) | Async batch API calls |
| Database | `sqlite3` (stdlib) | Single-file, zero-dependency |
| Data manipulation | `pandas` | `DataFrame` for metric computation |
| Statistics | `scipy`, `statsmodels` | Pearson r, logistic regression |
| Visualization (HTML) | `plotly` | Self-contained HTML output |
| Configuration | `json` (stdlib) | `config.json` |
| Hashing | `hashlib` (stdlib) | Replay deduplication |

### Python Version

Requires Python **3.11 or later** (match-case, exception groups used internally).

### Installation

```bash
pip install httpx pandas scipy statsmodels plotly textual
```

replayshark is downloaded automatically on first run (see §15.1).

---

## 19. Known Constraints & Open Issues

### 19.1 Confirmed Constraints

| Item | Description |
|---|---|
| `winnerTeamId` not in meta | Win/loss must be parsed from packet stream; not all replays contain `BattleResult` |
| `hidden_profile` covers full stats | When hidden, no per-ship stats either; only clan average substitution available |
| replayshark version parity | Each WoWS game update may require new `scripts/` data; automatic migration implemented (§15.2) |
| WG API rate limit | ~10 req/sec; large replay collections (500+) may take several minutes on first enrichment run |
| Spotting damage availability | Not confirmed available in all replayshark versions; `own_spotting_damage` may remain NULL |
| Cap zone coordinates | Per-map constants required for `own_cap_time_estimate`; must be maintained as a separate lookup table |

### 19.2 Open Design Decisions (Require Resolution Before P2)

| ID | Question | Options |
|---|---|---|
| OD-1 | `BattleResult` packet: is field name confirmed as `winner_team_id` across all replay versions? | Verify with test replays from multiple versions |
| OD-2 | Clan average: should the average exclude the hidden player themselves (circular) or include if they are a non-hidden member? | Exclude own account from clan average computation |
| OD-3 | Multi-division players: players queuing together may skew team win rate. Flag or exclude? | Add `division_flag` heuristic: if ≥2 allies share a clan tag, set `has_division = 1` in `battle_stats` |
| OD-4 | Ranked Battle analysis: if user enables it, should a separate normalization apply (rank ≠ win rate meaning)? | Separate report section; do not mix with random battle regression |
| OD-5 | Cap zone coordinate lookup table: source of truth? | Manual extraction from wows-toolkit map assets; update required per map addition |
