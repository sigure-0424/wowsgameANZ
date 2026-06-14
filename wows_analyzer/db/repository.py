from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable

from wows_analyzer.db.schema import init_db


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


@dataclass
class Repository:
    db_path: Path = Path("analyzer.db")

    def __post_init__(self) -> None:
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        init_db(self.conn)

    def close(self) -> None:
        self.conn.close()

    def replay_exists(self, replay_hash: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM battles WHERE replay_hash = ?",
            (replay_hash,),
        ).fetchone()
        return row is not None

    def upsert_battle(self, row: dict[str, Any]) -> None:
        self.conn.execute(
            """
            INSERT INTO battles (
                replay_hash, file_path, date, map_name, game_mode, duration_s,
                winner_team, own_team, is_incomplete, imported_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(replay_hash) DO UPDATE SET
                file_path = excluded.file_path,
                date = excluded.date,
                map_name = excluded.map_name,
                game_mode = excluded.game_mode,
                duration_s = excluded.duration_s,
                winner_team = excluded.winner_team,
                own_team = excluded.own_team,
                is_incomplete = excluded.is_incomplete,
                imported_at = excluded.imported_at
            """,
            (
                row["replay_hash"],
                row["file_path"],
                row["date"],
                row.get("map_name"),
                row.get("game_mode"),
                row.get("duration_s"),
                row.get("winner_team"),
                row.get("own_team"),
                row.get("is_incomplete", 0),
                row.get("imported_at", _utc_now_iso()),
            ),
        )

    def upsert_players(self, rows: Iterable[dict[str, Any]]) -> None:
        self.conn.executemany(
            """
            INSERT INTO players (
                replay_hash, entity_id, name, ship_id, team, relation,
                wg_account_id, win_rate, win_rate_source, battles_total, clan_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(replay_hash, entity_id) DO UPDATE SET
                name = excluded.name,
                ship_id = excluded.ship_id,
                team = excluded.team,
                relation = excluded.relation,
                wg_account_id = excluded.wg_account_id,
                win_rate = excluded.win_rate,
                win_rate_source = excluded.win_rate_source,
                battles_total = excluded.battles_total,
                clan_id = excluded.clan_id
            """,
            [
                (
                    r["replay_hash"],
                    r["entity_id"],
                    r["name"],
                    r.get("ship_id"),
                    r.get("team"),
                    r.get("relation"),
                    r.get("wg_account_id"),
                    r.get("win_rate"),
                    r.get("win_rate_source", "excluded"),
                    r.get("battles_total"),
                    r.get("clan_id"),
                )
                for r in rows
            ],
        )

    def insert_damage_events(self, replay_hash: str, rows: Iterable[dict[str, Any]]) -> None:
        self.conn.executemany(
            """
            INSERT INTO damage_events (replay_hash, clock, aggressor, victim, damage)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (replay_hash, r["clock"], r["aggressor"], r["victim"], r["damage"])
                for r in rows
            ],
        )

    def insert_sink_events(self, replay_hash: str, rows: Iterable[dict[str, Any]]) -> None:
        self.conn.executemany(
            """
            INSERT INTO sink_events (replay_hash, clock, entity_id, team)
            VALUES (?, ?, ?, ?)
            """,
            [(replay_hash, r["clock"], r["entity_id"], r["team"]) for r in rows],
        )

    def upsert_ship(self, row: dict[str, Any]) -> None:
        self.conn.execute(
            """
            INSERT INTO ships (
                ship_id, name, name_ja, tier, type, nation, is_premium, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ship_id) DO UPDATE SET
                name = excluded.name,
                name_ja = excluded.name_ja,
                tier = excluded.tier,
                type = excluded.type,
                nation = excluded.nation,
                is_premium = excluded.is_premium,
                fetched_at = excluded.fetched_at
            """,
            (
                row["ship_id"],
                row["name"],
                row.get("name_ja"),
                row["tier"],
                row["type"],
                row.get("nation"),
                row.get("is_premium", 0),
                row.get("fetched_at", _utc_now_iso()),
            ),
        )

    def upsert_battle_stats(self, row: dict[str, Any]) -> None:
        keys = list(row.keys())
        placeholders = ",".join(["?"] * len(keys))
        updates = ",".join([f"{k}=excluded.{k}" for k in keys if k != "replay_hash"])
        sql = (
            f"INSERT INTO battle_stats ({','.join(keys)}) VALUES ({placeholders}) "
            f"ON CONFLICT(replay_hash) DO UPDATE SET {updates}"
        )
        self.conn.execute(sql, [row[k] for k in keys])

    def get_api_cache(self, key: str, ttl_hours: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT value, fetched_at FROM api_cache WHERE key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None

        fetched_at = datetime.fromisoformat(row["fetched_at"])
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)
        if datetime.now(tz=timezone.utc) - fetched_at > timedelta(hours=ttl_hours):
            return None
        return json.loads(row["value"])

    def set_api_cache(self, key: str, value: dict[str, Any]) -> None:
        self.conn.execute(
            """
            INSERT INTO api_cache (key, value, fetched_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                fetched_at = excluded.fetched_at
            """,
            (key, json.dumps(value), _utc_now_iso()),
        )

    def fetch_players_missing_account(self) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT replay_hash, entity_id, name
                FROM players
                WHERE wg_account_id IS NULL
                GROUP BY replay_hash, entity_id, name
                """
            ).fetchall()
        )

    def fetch_players_by_replay(self, replay_hash: str) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                "SELECT * FROM players WHERE replay_hash = ?",
                (replay_hash,),
            ).fetchall()
        )

    def fetch_all_replay_hashes(self) -> list[str]:
        return [
            row["replay_hash"]
            for row in self.conn.execute("SELECT replay_hash FROM battles").fetchall()
        ]

    def fetch_battle(self, replay_hash: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM battles WHERE replay_hash = ?",
            (replay_hash,),
        ).fetchone()

    def fetch_ships_lookup(self) -> dict[int, sqlite3.Row]:
        rows = self.conn.execute("SELECT * FROM ships").fetchall()
        return {int(r["ship_id"]): r for r in rows}

    def fetch_damage_events(self, replay_hash: str) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                "SELECT * FROM damage_events WHERE replay_hash = ? ORDER BY clock",
                (replay_hash,),
            ).fetchall()
        )

    def fetch_sink_events(self, replay_hash: str) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                "SELECT * FROM sink_events WHERE replay_hash = ? ORDER BY clock",
                (replay_hash,),
            ).fetchall()
        )

    def fetch_all_battle_stats(self) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM battle_stats").fetchall())

    def get_total_battle_count(self) -> int:
        row = self.conn.execute("SELECT COUNT(1) AS n FROM battles").fetchone()
        return int(row["n"]) if row else 0

    def commit(self) -> None:
        self.conn.commit()
