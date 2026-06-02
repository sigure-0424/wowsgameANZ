from __future__ import annotations

import asyncio
from collections import Counter
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

from wows_analyzer.analysis.correlation import correlation_table
from wows_analyzer.analysis.regression import logistic_regression
from wows_analyzer.analysis.segment import build_slices
from wows_analyzer.api.account import account_info_batch, account_search_exact
from wows_analyzer.api.clans import get_clan_avg_winrate, get_player_clan_id
from wows_analyzer.api.encyclopedia import refresh_ships
from wows_analyzer.api.wg_client import WGClient
from wows_analyzer.config import AppConfig
from wows_analyzer.db.repository import Repository
from wows_analyzer.discovery import discover_replay_folder, populate_versions_dir
from wows_analyzer.export.csv_export import export_csv
from wows_analyzer.export.html_report import export_html_report
from wows_analyzer.export.json_export import export_json
from wows_analyzer.metrics.per_battle import compute_battle_stats
from wows_analyzer.parser.battle_result import detect_winner
from wows_analyzer.parser.meta_parser import make_replay_hash, parse_meta_blocks
from wows_analyzer.parser.packet_parser import parse_jl_events, run_replayshark_dump
from wows_analyzer.replayshark import download_replayshark


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


class AnalyzerPipeline:
    def __init__(self, workspace_root: Path = Path(".")) -> None:
        self.workspace_root = workspace_root
        self.config = AppConfig.load(workspace_root / "config.json")
        self.repo = Repository(workspace_root / "analyzer.db")
        self.bin_dir = workspace_root / "bin"
        self.versions_dir = workspace_root / "versions"
        self.last_analysis: dict[str, Any] = {}
        self.ribbons_by_replay: dict[str, list[dict]] = {}

    def close(self) -> None:
        self.repo.commit()
        self.repo.close()

    def save_config(self) -> None:
        self.config.save(self.workspace_root / "config.json")

    def scan(self) -> dict[str, Any]:
        replay_folder = discover_replay_folder(self.config.game_root or None)
        if replay_folder is None and self.config.replay_folder:
            replay_folder = Path(self.config.replay_folder)

        if replay_folder is None:
            return {"found": False, "count": 0, "replay_folder": None}

        files = sorted(replay_folder.glob("*.wowsreplay"))
        self.config.replay_folder = str(replay_folder)
        self.save_config()
        return {"found": True, "count": len(files), "replay_folder": str(replay_folder)}

    def ensure_replayshark_and_versions(self) -> None:
        exe = self.bin_dir / "replayshark.exe"
        if not exe.exists():
            version = download_replayshark(self.bin_dir)
            self.config.replayshark_version = version

        if self.config.game_root:
            new_build = populate_versions_dir(
                Path(self.config.game_root),
                self.versions_dir,
                self.config.last_build_number,
            )
            self.config.last_build_number = new_build

        self.save_config()

    def parse(self) -> dict[str, Any]:
        if not self.config.replay_folder:
            raise RuntimeError("Replay folder not configured. Run scan/settings first.")

        replay_dir = Path(self.config.replay_folder)
        if not replay_dir.exists():
            raise RuntimeError(f"Replay folder does not exist: {replay_dir}")

        try:
            self.ensure_replayshark_and_versions()
        except Exception as exc:  # noqa: BLE001
            return {
                "parsed": 0,
                "skipped": 0,
                "parse_errors": 0,
                "status": "blocked",
                "reason": str(exc),
            }

        exe = self.bin_dir / "replayshark.exe"
        if not exe.exists():
            return {
                "parsed": 0,
                "skipped": 0,
                "parse_errors": 0,
                "status": "blocked",
                "reason": "replayshark.exe is not available in bin/",
            }

        parsed = 0
        skipped = 0
        parse_errors = 0
        errors: list[tuple[str, str]] = []

        for replay_file in sorted(replay_dir.glob("*.wowsreplay")):
            try:
                # WoWS may leave a transient temp file while recording; ignore it.
                if replay_file.name.lower() == "temp.wowsreplay":
                    skipped += 1
                    continue

                meta = parse_meta_blocks(replay_file)
                replay_hash = make_replay_hash(meta, replay_file)
                if self.repo.replay_exists(replay_hash):
                    skipped += 1
                    continue

                jl_path = replay_file.with_suffix(".jl")
                game_dir = Path(self.config.game_root) if self.config.game_root else None
                ok = run_replayshark_dump(exe, replay_file, jl_path, game_dir)
                if not ok or not jl_path.exists():
                    parse_errors += 1
                    errors.append((replay_file.name, "replayshark failed or no .jl output"))
                    continue

                parsed_payload = parse_jl_events(jl_path)
                packet_meta = parsed_payload.get("meta", {})
                if packet_meta:
                    meta.update(packet_meta)

                arena_players = parsed_payload.get("arena_players", [])
                own_entity_id = parsed_payload.get("own_entity_id")
                vehicles = meta.get("vehicles", [])
                players_rows = []
                team_population = Counter()

                for ap in arena_players:
                    entity_id = ap.get("entity_id", -1)
                    team = ap.get("team_id")
                    if team is None:
                        team = 0
                    else:
                        team = int(team)
                    if team in (0, 1):
                        team_population[team] += 1

                    players_rows.append(
                        {
                            "replay_hash": replay_hash,
                            "entity_id": int(entity_id),
                            "name": ap.get("name", "unknown"),
                            "ship_id": ap.get("ship_id"),
                            "team": team,
                            "relation": 0 if entity_id == own_entity_id else (1 if team == 0 else 2),
                            "wg_account_id": int(ap["db_id"]) if ap.get("db_id") else None,
                            "win_rate": None,
                            "win_rate_source": "excluded",
                            "battles_total": None,
                            "clan_id": None,
                        }
                    )

                # Fallback for older dumps where arena player states are unavailable.
                if not players_rows:
                    for v in vehicles:
                        relation = int(v.get("relation", 2))
                        team = 0 if relation in (0, 1) else 1
                        entity_id = int(v.get("id", -1))
                        if team in (0, 1) and entity_id >= 0:
                            team_population[team] += 1

                        players_rows.append(
                            {
                                "replay_hash": replay_hash,
                                "entity_id": entity_id,
                                "name": v.get("name", "unknown"),
                                "ship_id": v.get("shipId"),
                                "team": team,
                                "relation": relation,
                                "wg_account_id": None,
                                "win_rate": None,
                                "win_rate_source": "excluded",
                                "battles_total": None,
                                "clan_id": None,
                            }
                        )

                sink_events = parsed_payload["sink_events"]

                winner_team, is_incomplete = detect_winner(
                    parsed_payload.get("battle_result_team"),
                    sink_events,
                    dict(team_population),
                )

                own_row = next((p for p in players_rows if p.get("entity_id") == own_entity_id), None)
                own_team = int(own_row["team"]) if own_row else 0

                battle_row = {
                    "replay_hash": replay_hash,
                    "file_path": str(replay_file),
                    "date": meta.get("dateTime", _utc_now_iso()),
                    "map_name": meta.get("mapDisplayName") or meta.get("mapName"),
                    "game_mode": meta.get("gameMode"),
                    "duration_s": int(meta.get("duration") or 0),
                    "winner_team": winner_team,
                    "own_team": own_team,
                    "is_incomplete": is_incomplete,
                    "imported_at": _utc_now_iso(),
                }

                self.repo.upsert_battle(battle_row)
                self.repo.upsert_players(players_rows)
                self.repo.insert_damage_events(replay_hash, parsed_payload["damage_events"])
                self.repo.insert_sink_events(replay_hash, sink_events)
                self.ribbons_by_replay[replay_hash] = parsed_payload.get("ribbons", [])
                self.repo.commit()

                jl_path.unlink(missing_ok=True)
                parsed += 1
            except Exception as e:  # noqa: BLE001
                parse_errors += 1
                errors.append((replay_file.name, str(e)))
                continue

        return {
            "parsed": parsed,
            "skipped": skipped,
            "parse_errors": parse_errors,
            "errors": [{"file": f, "error": e} for f, e in errors],
        }

    async def enrich(self) -> dict[str, int]:
        if not self.config.app_id:
            raise RuntimeError("WG app_id is empty. Configure settings first.")

        client = WGClient(
            app_id=self.config.app_id,
            region=self.config.server_region,
            delay_ms=self.config.api_delay_ms,
        )

        # Refresh ships dictionary if empty.
        ship_count = self.repo.conn.execute("SELECT COUNT(*) AS n FROM ships").fetchone()["n"]
        if int(ship_count) == 0:
            await refresh_ships(self.repo, client)

        rows = self.repo.fetch_players_missing_account()
        resolved_accounts = 0
        for row in rows:
            name = row["name"]
            if not name:
                continue
            cache_key = f"name_to_id:{name}"
            cached = self.repo.get_api_cache(cache_key, self.config.cache_ttl_hours)
            if cached and "account_id" in cached:
                account_id = cached["account_id"]
            else:
                account_id = await account_search_exact(client, name)
                self.repo.set_api_cache(cache_key, {"account_id": account_id})

            if account_id is None:
                continue

            self.repo.conn.execute(
                "UPDATE players SET wg_account_id = ? WHERE name = ? AND wg_account_id IS NULL",
                (int(account_id), name),
            )
            resolved_accounts += 1

        account_rows = self.repo.conn.execute(
            "SELECT DISTINCT wg_account_id FROM players WHERE wg_account_id IS NOT NULL"
        ).fetchall()
        account_ids = [int(r["wg_account_id"]) for r in account_rows]

        info = await account_info_batch(client, account_ids)
        updated_rates = 0

        for account_id, payload in info.items():
            hidden = bool(payload.get("hidden_profile"))
            if not hidden:
                pvp = ((payload.get("statistics") or {}).get("pvp") or {})
                battles = int(pvp.get("battles") or 0)
                wins = int(pvp.get("wins") or 0)
                if battles > 0:
                    win_rate = (wins / battles) * 100.0
                    self.repo.conn.execute(
                        """
                        UPDATE players
                        SET win_rate = ?, win_rate_source = 'direct', battles_total = ?
                        WHERE wg_account_id = ?
                        """,
                        (float(win_rate), battles, account_id),
                    )
                    updated_rates += 1
                continue

            clan_cache_key = f"player_clan:{account_id}"
            cached_clan = self.repo.get_api_cache(clan_cache_key, self.config.cache_ttl_hours)
            clan_id = cached_clan.get("clan_id") if cached_clan else None
            if clan_id is None:
                clan_id = await get_player_clan_id(client, account_id)
                self.repo.set_api_cache(clan_cache_key, {"clan_id": clan_id})

            if clan_id is None:
                self.repo.conn.execute(
                    "UPDATE players SET win_rate = NULL, win_rate_source = 'excluded' WHERE wg_account_id = ?",
                    (account_id,),
                )
                continue

            clan_avg_key = f"clan_avg:{clan_id}"
            cached_avg = self.repo.get_api_cache(clan_avg_key, self.config.cache_ttl_hours)
            clan_avg = cached_avg.get("win_rate") if cached_avg else None
            if clan_avg is None:
                clan_avg = await get_clan_avg_winrate(client, int(clan_id), exclude_account_id=account_id)
                self.repo.set_api_cache(clan_avg_key, {"win_rate": clan_avg})

            if clan_avg is None:
                self.repo.conn.execute(
                    "UPDATE players SET win_rate = NULL, win_rate_source = 'excluded', clan_id = ? WHERE wg_account_id = ?",
                    (int(clan_id), account_id),
                )
                continue

            self.repo.conn.execute(
                """
                UPDATE players
                SET win_rate = ?, win_rate_source = 'clan_avg', clan_id = ?
                WHERE wg_account_id = ?
                """,
                (float(clan_avg), int(clan_id), account_id),
            )
            updated_rates += 1

        self.repo.commit()
        return {
            "resolved_accounts": resolved_accounts,
            "updated_win_rates": updated_rates,
            "accounts_considered": len(account_ids),
        }

    def analyze(self) -> dict[str, Any]:
        replay_hashes = self.repo.fetch_all_replay_hashes()
        computed = 0

        for replay_hash in replay_hashes:
            row = compute_battle_stats(
                self.repo,
                replay_hash,
                ribbons=self.ribbons_by_replay.get(replay_hash, []),
            )
            if row is None:
                continue
            self.repo.upsert_battle_stats(row)
            computed += 1
        self.repo.commit()

        stats_rows = [dict(r) for r in self.repo.fetch_all_battle_stats()]
        if not stats_rows:
            self.last_analysis = {
                "metadata": {"generated_at": _utc_now_iso(), "n_battles": 0},
                "overall": {"correlations": [], "regression": {"error": "no_data"}},
                "slices": {},
                "per_vessel": [],
            }
            return self.last_analysis

        df = pd.DataFrame(stats_rows)
        slices = build_slices(df)

        min_battles = self.config.min_battles_for_stats
        slice_results: dict[str, Any] = {}
        flat_correlations: list[dict[str, Any]] = []

        for name, sdf in slices.items():
            corr_rows = correlation_table(sdf, min_battles=min_battles)
            if name == "overall":
                reg = logistic_regression(sdf)
            else:
                reg = {}
            slice_results[name] = {
                "n": int(len(sdf)),
                "correlations": corr_rows,
                "regression": reg,
            }
            for row in corr_rows:
                flat_correlations.append({"slice": name, **row})

        vessel_rows = []
        by_vessel = df.groupby("own_ship_name", dropna=True)
        for vessel, vdf in by_vessel:
            n = int(len(vdf))
            if n == 0:
                continue
            vessel_rows.append(
                {
                    "vessel": vessel,
                    "n": n,
                    "win_rate": float(vdf["won"].dropna().mean() * 100) if vdf["won"].notna().any() else None,
                    "avg_damage": float(vdf["own_damage"].mean()) if "own_damage" in vdf else None,
                    "avg_kd": float(vdf["own_kd"].mean()) if "own_kd" in vdf else None,
                    "avg_torp_hits": float(vdf["own_torp_hits"].dropna().mean()) if "own_torp_hits" in vdf and vdf["own_torp_hits"].notna().any() else None,
                }
            )
        vessel_rows.sort(key=lambda x: x["n"], reverse=True)

        self.last_analysis = {
            "metadata": {
                "generated_at": _utc_now_iso(),
                "filters": {"default_game_mode_filter": self.config.default_game_mode_filter},
                "n_battles": int(len(df)),
                "computed_battle_stats": computed,
            },
            "overall": slice_results.get("overall", {"correlations": [], "regression": {}}),
            "slices": slice_results,
            "correlations_flat": flat_correlations,
            "per_vessel": vessel_rows,
        }

        return self.last_analysis

    def export(self) -> dict[str, str]:
        if not self.last_analysis:
            self.analyze()

        output_path = (self.workspace_root / self.config.output_path).resolve()
        output_path.mkdir(parents=True, exist_ok=True)

        battle_df = pd.DataFrame([dict(r) for r in self.repo.fetch_all_battle_stats()])
        corr_rows = self.last_analysis.get("correlations_flat", [])
        per_vessel_rows = self.last_analysis.get("per_vessel", [])

        export_csv(output_path, battle_df, corr_rows, per_vessel_rows)
        export_json(output_path, self.last_analysis)
        export_html_report(output_path, battle_df, corr_rows)

        return {
            "output_path": str(output_path),
            "json": str(output_path / "analysis_results.json"),
            "html": str(output_path / "report.html"),
            "csv": str(output_path / "csv"),
        }

    def run(self) -> dict[str, Any]:
        scan_result = self.scan()
        parse_result = self.parse()
        enrich_result = asyncio.run(self.enrich()) if self.config.app_id else {"skipped": "missing_app_id"}
        analysis_result = self.analyze()
        export_result = self.export()
        return {
            "scan": scan_result,
            "parse": parse_result,
            "enrich": enrich_result,
            "analyze": {
                "n_battles": analysis_result.get("metadata", {}).get("n_battles", 0),
                "generated_at": analysis_result.get("metadata", {}).get("generated_at"),
            },
            "export": export_result,
        }

    def dump_report_text(self) -> str:
        if not self.last_analysis:
            self.analyze()
        overall = self.last_analysis.get("overall", {})
        corr = [r for r in overall.get("correlations", []) if math.isfinite(float(r.get("r", float("nan"))))]

        stats_rows = [dict(r) for r in self.repo.fetch_all_battle_stats()]
        win_known = [r for r in stats_rows if r.get("won") in (0, 1)]
        wins = sum(int(r.get("won") == 1) for r in win_known)
        avg_damage = (
            sum(float(r.get("own_damage") or 0.0) for r in stats_rows) / len(stats_rows)
            if stats_rows
            else 0.0
        )
        survival_rate = (
            (sum(int(r.get("own_survived") == 1) for r in stats_rows) / len(stats_rows)) * 100.0
            if stats_rows
            else 0.0
        )

        significant = [r for r in corr if float(r.get("p", 1.0)) <= 0.05]
        nonsignificant = [r for r in corr if float(r.get("p", 1.0)) > 0.05]
        pos_top = sorted(corr, key=lambda x: float(x["r"]), reverse=True)[:5]
        neg_top = sorted(corr, key=lambda x: float(x["r"]))[:5]

        def _strength(row: dict[str, Any]) -> str:
            r = abs(float(row.get("r", 0.0)))
            p = float(row.get("p", 1.0))
            if p <= 0.05 and r >= 0.3:
                return "Strong"
            if p <= 0.1 and r >= 0.2:
                return "Weak"
            return "Ignore"

        lines = [
            "WoWS Replay Analyzer Report",
            f"Generated: {self.last_analysis.get('metadata', {}).get('generated_at', '')}",
            f"Battles: {self.last_analysis.get('metadata', {}).get('n_battles', 0)}",
            "",
            "Summary:",
            f"- Known outcome battles: {len(win_known)}",
            f"- Win rate: {(wins / len(win_known) * 100.0):.1f}%" if win_known else "- Win rate: N/A",
            f"- Avg own damage: {avg_damage:,.0f}",
            f"- Survival rate: {survival_rate:.1f}%",
            f"- Significant metrics (p<=0.05): {len(significant)}",
            "",
            "Top Positive Correlations:",
        ]
        for row in pos_top:
            lines.append(
                f"- {row['metric']}: r={row['r']:.3f}, p={row['p']:.4f}, n={row['n']}, class={_strength(row)}"
            )

        lines.append("")
        lines.append("Top Negative Correlations:")
        for row in neg_top:
            lines.append(
                f"- {row['metric']}: r={row['r']:.3f}, p={row['p']:.4f}, n={row['n']}, class={_strength(row)}"
            )

        lines.append("")
        lines.append("Significant (p<=0.05):")
        for row in significant[:10]:
            lines.append(
                f"- {row['metric']}: r={row['r']:.3f}, p={row['p']:.4f}, n={row['n']}, class={_strength(row)}"
            )

        lines.append("")
        lines.append("Non-significant (reference):")
        for row in nonsignificant[:10]:
            lines.append(
                f"- {row['metric']}: r={row['r']:.3f}, p={row['p']:.4f}, n={row['n']}, class={_strength(row)}"
            )

        return "\n".join(lines)
