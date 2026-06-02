from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from wows_analyzer.pipeline import AnalyzerPipeline
from wows_analyzer.tui.screen_export import render_export
from wows_analyzer.tui.screen_filter import render_filter
from wows_analyzer.tui.screen_main import MainScreenState, render_main
from wows_analyzer.tui.screen_report import render_report
from wows_analyzer.tui.screen_settings import render_settings


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, indent=2))


def cmd_settings(args: argparse.Namespace) -> None:
    p = AnalyzerPipeline(Path("."))
    try:
        updates = {}
        if args.app_id is not None:
            updates["app_id"] = args.app_id
        if args.region is not None:
            updates["server_region"] = args.region
        if args.game_root is not None:
            updates["game_root"] = args.game_root
        if args.replay_folder is not None:
            updates["replay_folder"] = args.replay_folder
        if args.min_battles is not None:
            updates["min_battles_for_stats"] = args.min_battles
        if args.api_delay_ms is not None:
            updates["api_delay_ms"] = args.api_delay_ms
        if args.cache_ttl_hours is not None:
            updates["cache_ttl_hours"] = args.cache_ttl_hours
        if args.output_path is not None:
            updates["output_path"] = args.output_path

        p.config.update(**updates)
        p.save_config()
        print("Settings updated.")
    finally:
        p.close()


def cmd_scan() -> None:
    p = AnalyzerPipeline(Path("."))
    try:
        _print_json(p.scan())
    finally:
        p.close()


def cmd_parse() -> None:
    p = AnalyzerPipeline(Path("."))
    try:
        _print_json(p.parse())
    finally:
        p.close()


def cmd_enrich() -> None:
    p = AnalyzerPipeline(Path("."))
    try:
        _print_json(asyncio.run(p.enrich()))
    finally:
        p.close()


def cmd_analyze() -> None:
    p = AnalyzerPipeline(Path("."))
    try:
        result = p.analyze()
        _print_json(
            {
                "metadata": result.get("metadata", {}),
                "overall_top_correlations": result.get("overall", {}).get("correlations", [])[:10],
            }
        )
        print()
        print(p.dump_report_text())
    finally:
        p.close()


def cmd_export() -> None:
    p = AnalyzerPipeline(Path("."))
    try:
        p.analyze()
        _print_json(p.export())
    finally:
        p.close()


def cmd_run() -> None:
    p = AnalyzerPipeline(Path("."))
    try:
        _print_json(p.run())
        print()
        print(p.dump_report_text())
    finally:
        p.close()


class TextViewScreen(Screen[None]):
    def __init__(self, title: str, text: str) -> None:
        super().__init__()
        self.title = title
        self.text = text

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Container(Static(self.text, id="body"), id="screen-body")
        yield Footer()

    BINDINGS = [
        ("escape", "app.pop_screen", "Back"),
        ("q", "app.pop_screen", "Back"),
    ]


class AnalyzerTUI(App[None]):
    TITLE = "WoWS Replay Analyzer"

    BINDINGS = [
        ("ctrl+x", "quit", "Exit"),
        ("ctrl+s", "show_settings", "Settings"),
        ("ctrl+f", "show_filter", "Filter"),
        ("ctrl+r", "show_report", "Report"),
        ("r", "run_all", "Run"),
        ("ctrl+e", "run_export", "Export"),
        ("ctrl+p", "run_parse", "Parse"),
        ("ctrl+a", "run_analyze", "Analyze"),
        ("ctrl+u", "run_enrich", "API Sync"),
        ("u", "run_enrich", "API Sync"),
        ("f5", "run_all", "Run"),
        ("ctrl+g", "run_all", "Run"),
    ]

    CSS = """
    #main-body {
        height: 1fr;
        padding: 1 2;
    }
    #main-text {
        width: 100%;
        height: 100%;
    }
    #screen-body {
        height: 1fr;
        padding: 1 2;
    }
    #body {
        width: 100%;
        height: 100%;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.pipeline = AnalyzerPipeline(Path("."))
        self.last_run: dict[str, Any] = {}

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Container(Static("", id="main-text"), id="main-body")
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_main_view("Ready")

    def on_unmount(self) -> None:
        self.pipeline.close()

    def refresh_main_view(self, status: str = "") -> None:
        scan = self.pipeline.scan()
        parsed_ok = int((self.last_run.get("parse") or {}).get("parsed", 0))
        parse_errors = int((self.last_run.get("parse") or {}).get("parse_errors", 0))

        hidden_profiles = 0
        try:
            row = self.pipeline.repo.conn.execute(
                "SELECT COUNT(1) AS n FROM players WHERE win_rate_source = 'excluded'"
            ).fetchone()
            hidden_profiles = int(row["n"]) if row else 0
        except Exception:
            hidden_profiles = 0

        state = MainScreenState(
            replay_count=int(scan.get("count", 0)),
            parsed_ok=parsed_ok,
            parse_errors=parse_errors,
            hidden_profiles=hidden_profiles,
        )

        body = render_main(state)
        if status:
            body += f"\nStatus: {status}\n"
        self.query_one("#main-text", Static).update(body)

    def action_show_settings(self) -> None:
        text = render_settings(self.pipeline.config)
        self.push_screen(TextViewScreen("Settings", text))

    def action_show_filter(self) -> None:
        text = render_filter(self.pipeline.config.default_game_mode_filter)
        self.push_screen(TextViewScreen("Filter", text))

    def action_show_report(self) -> None:
        try:
            report = self.pipeline.dump_report_text()
            self.push_screen(TextViewScreen("Report", render_report(report)))
        except Exception as exc:  # noqa: BLE001
            self.refresh_main_view(f"Report error: {exc}")

    def action_run_parse(self) -> None:
        try:
            result = self.pipeline.parse()
            self.last_run["parse"] = result
            self.refresh_main_view(
                f"Parse complete: parsed={result.get('parsed', 0)} errors={result.get('parse_errors', 0)}"
            )
        except Exception as exc:  # noqa: BLE001
            self.refresh_main_view(f"Parse error: {exc}")

    async def action_run_enrich(self) -> None:
        if not self.pipeline.config.app_id:
            self.refresh_main_view("API Sync skipped: app_id is empty")
            return
        try:
            result = await self.pipeline.enrich()
            self.last_run["enrich"] = result
            self.refresh_main_view(
                "API Sync complete: "
                f"resolved={result.get('resolved_accounts', 0)} updated={result.get('updated_win_rates', 0)}"
            )
        except Exception as exc:  # noqa: BLE001
            self.refresh_main_view(f"API Sync error: {exc}")

    def action_run_analyze(self) -> None:
        try:
            result = self.pipeline.analyze()
            self.last_run["analyze"] = result.get("metadata", {})
            self.refresh_main_view(f"Analyze complete: battles={result.get('metadata', {}).get('n_battles', 0)}")
        except Exception as exc:  # noqa: BLE001
            self.refresh_main_view(f"Analyze error: {exc}")

    def action_run_export(self) -> None:
        try:
            self.pipeline.analyze()
            result = self.pipeline.export()
            self.last_run["export"] = result
            self.push_screen(TextViewScreen("Export", render_export(result.get("output_path", ""))))
            self.refresh_main_view("Export complete")
        except Exception as exc:  # noqa: BLE001
            self.refresh_main_view(f"Export error: {exc}")

    async def action_run_all(self) -> None:
        try:
            scan_result = self.pipeline.scan()
            parse_result = self.pipeline.parse()
            if self.pipeline.config.app_id:
                enrich_result = await self.pipeline.enrich()
            else:
                enrich_result = {"skipped": "missing_app_id"}
            analysis_result = self.pipeline.analyze()
            export_result = self.pipeline.export()

            result = {
                "scan": scan_result,
                "parse": parse_result,
                "enrich": enrich_result,
                "analyze": {
                    "n_battles": analysis_result.get("metadata", {}).get("n_battles", 0),
                    "generated_at": analysis_result.get("metadata", {}).get("generated_at"),
                },
                "export": export_result,
            }

            self.last_run = result
            self.refresh_main_view(
                "Run complete: "
                f"parse={result.get('parse', {}).get('parsed', 0)} "
                f"errors={result.get('parse', {}).get('parse_errors', 0)} "
                f"battles={result.get('analyze', {}).get('n_battles', 0)}"
            )
        except Exception as exc:  # noqa: BLE001
            self.refresh_main_view(f"Run error: {exc}")


def cmd_tui() -> None:
    AnalyzerTUI().run()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="WoWS Replay Analyzer")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("scan", help="Discover replay folder and count files")
    sub.add_parser("parse", help="Parse replay files into analyzer.db")
    sub.add_parser("enrich", help="Enrich player win rates from WG API")
    sub.add_parser("analyze", help="Compute battle stats and correlations")
    sub.add_parser("export", help="Export CSV/JSON/HTML report")
    sub.add_parser("run", help="Run full pipeline")
    sub.add_parser("tui", help="Launch nano-like terminal UI")

    settings = sub.add_parser("settings", help="Update config values")
    settings.add_argument("--app-id")
    settings.add_argument("--region", choices=["ASIA", "EU", "NA"])
    settings.add_argument("--game-root")
    settings.add_argument("--replay-folder")
    settings.add_argument("--min-battles", type=int)
    settings.add_argument("--api-delay-ms", type=int)
    settings.add_argument("--cache-ttl-hours", type=int)
    settings.add_argument("--output-path")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "settings":
        cmd_settings(args)
    elif args.command == "scan":
        cmd_scan()
    elif args.command == "parse":
        cmd_parse()
    elif args.command == "enrich":
        cmd_enrich()
    elif args.command == "analyze":
        cmd_analyze()
    elif args.command == "export":
        cmd_export()
    elif args.command == "run":
        cmd_run()
    elif args.command == "tui":
        cmd_tui()
    else:
        parser.error(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    main()
