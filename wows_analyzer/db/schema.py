from __future__ import annotations

import sqlite3


SCHEMA_SQL = [
    """
    CREATE TABLE IF NOT EXISTS battles (
        replay_hash     TEXT PRIMARY KEY,
        file_path       TEXT NOT NULL,
        date            TEXT NOT NULL,
        map_name        TEXT,
        game_mode       TEXT,
        duration_s      INTEGER,
        winner_team     INTEGER,
        own_team        INTEGER,
        is_incomplete   INTEGER DEFAULT 0,
        imported_at     TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS players (
        replay_hash     TEXT NOT NULL,
        entity_id       INTEGER NOT NULL,
        name            TEXT NOT NULL,
        ship_id         INTEGER,
        team            INTEGER,
        relation        INTEGER,
        wg_account_id   INTEGER,
        win_rate        REAL,
        win_rate_source TEXT,
        battles_total   INTEGER,
        clan_id         INTEGER,
        PRIMARY KEY (replay_hash, entity_id)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS damage_events (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        replay_hash TEXT NOT NULL,
        clock       REAL NOT NULL,
        aggressor   INTEGER NOT NULL,
        victim      INTEGER NOT NULL,
        damage      REAL NOT NULL
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_damage_replay ON damage_events(replay_hash);",
    """
    CREATE TABLE IF NOT EXISTS sink_events (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        replay_hash TEXT NOT NULL,
        clock       REAL NOT NULL,
        entity_id   INTEGER NOT NULL,
        team        INTEGER NOT NULL
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_sink_replay ON sink_events(replay_hash);",
    """
    CREATE TABLE IF NOT EXISTS ships (
        ship_id     INTEGER PRIMARY KEY,
        name        TEXT NOT NULL,
        name_ja     TEXT,
        tier        INTEGER NOT NULL,
        type        TEXT NOT NULL,
        nation      TEXT,
        is_premium  INTEGER DEFAULT 0,
        fetched_at  TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS battle_stats (
        replay_hash             TEXT PRIMARY KEY,
        won                     INTEGER,
        own_ship_id             INTEGER,
        own_ship_name           TEXT,
        own_ship_tier           INTEGER,
        own_ship_type           TEXT,
        own_tier_disadvantage   INTEGER,
        own_damage              REAL,
        own_kills               INTEGER,
        own_deaths              INTEGER,
        own_kd                  REAL,
        own_survived            INTEGER,
        own_damage_per_min      REAL,
        own_dmg_share           REAL,
        own_torp_hits           INTEGER,
        own_spotting_damage     REAL,
        own_cap_time_estimate   REAL,
        own_smoke_deployed      INTEGER,
        ally_count              INTEGER,
        ally_avg_winrate        REAL,
        ally_winrate_top        REAL,
        ally_winrate_worst      REAL,
        ally_winrate_std        REAL,
        ally_hidden_count       INTEGER,
        ally_total_damage       REAL,
        ally_kills              INTEGER,
        ally_survival_count     INTEGER,
        enemy_count             INTEGER,
        enemy_avg_winrate       REAL,
        enemy_winrate_top       REAL,
        enemy_winrate_worst     REAL,
        enemy_winrate_std       REAL,
        enemy_hidden_count      INTEGER,
        enemy_total_damage      REAL,
        enemy_kills             INTEGER,
        enemy_survival_count    INTEGER,
        winrate_delta           REAL,
        damage_delta            REAL,
        kill_delta              INTEGER,
        sink_delta_t5           INTEGER,
        sink_delta_t10          INTEGER,
        sink_delta_t15          INTEGER,
        sink_delta_t20          INTEGER,
        map_name                TEXT,
        game_mode               TEXT,
        date                    TEXT
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS api_cache (
        key         TEXT PRIMARY KEY,
        value       TEXT NOT NULL,
        fetched_at  TEXT NOT NULL
    );
    """,
]


def init_db(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    for statement in SCHEMA_SQL:
        cur.execute(statement)
    conn.commit()
