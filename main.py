from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Container, VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Static, LoadingIndicator

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
        if args.app_id is not None: updates["app_id"] = args.app_id
        if args.region is not None: updates["server_region"] = args.region
        if args.game_root is not None: updates["game_root"] = args.game_root
        if args.replay_folder is not None: updates["replay_folder"] = args.replay_folder
        if args.min_battles is not None: updates["min_battles_for_stats"] = args.min_battles
        if args.api_delay_ms is not None: updates["api_delay_ms"] = args.api_delay_ms
        if args.cache_ttl_hours is not None: updates["cache_ttl_hours"] = args.cache_ttl_hours
        if args.output_path is not None: updates["output_path"] = args.output_path
        if args.language is not None: updates["language"] = args.language
        p.config.update(**updates); p.save_config(); print("Settings updated.")
    finally: p.close()


def cmd_scan() -> None:
    p = AnalyzerPipeline(Path(".")); _print_json(p.scan()); p.close()

def cmd_parse() -> None:
    p = AnalyzerPipeline(Path(".")); _print_json(p.parse()); p.close()

def cmd_enrich() -> None:
    p = AnalyzerPipeline(Path(".")); _print_json(asyncio.run(p.enrich())); p.close()

def cmd_analyze() -> None:
    p = AnalyzerPipeline(Path(".")); result = p.analyze(); _print_json({"metadata": result.get("metadata", {}), "overall_top_correlations": result.get("overall", {}).get("correlations", [])[:10]}); print(); print(p.dump_report_text()); p.close()

def cmd_export() -> None:
    p = AnalyzerPipeline(Path(".")); p.analyze(); _print_json(p.export()); p.close()

def cmd_run() -> None:
    p = AnalyzerPipeline(Path(".")); _print_json(p.run()); print(); print(p.dump_report_text()); p.close()


class TextViewScreen(Screen[None]):
    def __init__(self, title: str, text: str) -> None:
        super().__init__(); self.title = title; self.text = text
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True); yield VerticalScroll(Static(Text.from_ansi(self.text), id="body"), id="screen-body"); yield Footer()
    BINDINGS = [("escape", "app.pop_screen", "Back"), ("q", "app.pop_screen", "Back")]


class LoadingScreen(Screen[None]):
    def compose(self) -> ComposeResult:
        yield Container(LoadingIndicator(), id="loading-container")
    CSS = """
    #loading-container {
        width: 100%;
        height: 100%;
        align: center middle;
        background: rgba(0, 0, 0, 0.5);
    }
    """


class AnalyzerTUI(App[None]):
    TITLE = "WoWS Replay Analyzer"
    BINDINGS = [("ctrl+x", "quit", "Exit"), ("ctrl+s", "show_settings", "Settings"), ("ctrl+f", "show_filter", "Filter"), ("ctrl+r", "show_report", "Report"), ("r", "run_all", "Run"), ("ctrl+e", "run_export", "Export"), ("ctrl+p", "run_parse", "Parse"), ("ctrl+a", "run_analyze", "Analyze"), ("ctrl+u", "run_enrich", "API Sync"), ("u", "run_enrich", "API Sync"), ("f5", "run_all", "Run"), ("ctrl+g", "run_all", "Run")]
    CSS = """
    #main-body { height: 1fr; padding: 1 2; }
    #main-text { width: 100%; height: 100%; }
    #screen-body { height: 1fr; padding: 1 2; }
    #body { width: 100%; height: auto; }
    """

    def __init__(self) -> None:
        super().__init__(); self.pipeline = AnalyzerPipeline(Path(".")); self.last_run: dict[str, Any] = {}

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True); yield Container(Static("", id="main-text"), id="main-body"); yield Footer()

    def on_mount(self) -> None:
        self.refresh_main_view("Ready")

    def on_unmount(self) -> None:
        self.pipeline.close()

    def refresh_main_view(self, status: str = "") -> None:
        # Fast scan (cached)
        scan = self.pipeline.scan()
        total_parsed = self.pipeline.repo.get_total_battle_count()
        parse_errors = int((self.last_run.get("parse") or {}).get("parse_errors", 0))
        hidden_profiles = 0
        try:
            row = self.pipeline.repo.conn.execute("SELECT COUNT(1) AS n FROM players WHERE win_rate_source = 'excluded'").fetchone()
            hidden_profiles = int(row["n"]) if row else 0
        except Exception: pass

        state = MainScreenState(replay_count=int(scan.get("count", 0)), parsed_ok=total_parsed, parse_errors=parse_errors, hidden_profiles=hidden_profiles, lang=self.pipeline.config.language)
        body = render_main(state)
        if status: body += f"\nStatus: {status}\n"
        self.query_one("#main-text", Static).update(Text.from_ansi(body))

    def action_show_settings(self) -> None: self.push_screen(TextViewScreen("Settings", render_settings(self.pipeline.config)))
    def action_show_filter(self) -> None: self.push_screen(TextViewScreen("Filter", render_filter(self.pipeline.config.default_game_mode_filter)))

    def action_show_report(self) -> None: self.run_worker_show_report()

    @work(exclusive=True)
    async def run_worker_show_report(self) -> None:
        self.push_screen(LoadingScreen()); self.refresh_main_view("Generating Report...")
        try:
            report = await asyncio.to_thread(self.pipeline.dump_report_text)
            self.pop_screen(); self.push_screen(TextViewScreen("Report", render_report(report)))
        except Exception as exc:
            self.pop_screen(); self.refresh_main_view(f"Report error: {exc}")
        finally: self.refresh_main_view("Ready")

    def action_run_all(self) -> None: self.run_worker_all()

    @work(exclusive=True)
    async def run_worker_all(self) -> None:
        self.push_screen(LoadingScreen()); self.pipeline.clear_cache()
        try:
            self.refresh_main_view("Step 1/5: Scanning..."); scan = await asyncio.to_thread(self.pipeline.scan, force=True)
            self.refresh_main_view(f"Step 2/5: Parsing {scan.get('count', 0)} files..."); parse = await asyncio.to_thread(self.pipeline.parse)
            self.refresh_main_view("Step 3/5: API Sync..."); enrich = await self.pipeline.enrich() if self.pipeline.config.app_id else {}
            self.refresh_main_view("Step 4/5: Analyzing..."); analyze = await asyncio.to_thread(self.pipeline.analyze)
            self.refresh_main_view("Step 5/5: Exporting..."); export = await asyncio.to_thread(self.pipeline.export)
            self.last_run = {"scan": scan, "parse": parse, "enrich": enrich, "analyze": analyze.get("metadata", {}), "export": export}
            self.pop_screen(); self.refresh_main_view(f"Run complete! Parsed: {parse.get('parsed', 0)}")
        except Exception as exc:
            self.pop_screen(); self.refresh_main_view(f"Run failed: {exc}")

    def action_run_parse(self) -> None:
        self.refresh_main_view("Parsing..."); res = self.pipeline.parse(); self.last_run["parse"] = res; self.refresh_main_view(f"Parse complete: {res.get('parsed', 0)}")
    
    async def action_run_enrich(self) -> None:
        if not self.pipeline.config.app_id: self.refresh_main_view("Missing app_id"); return
        self.refresh_main_view("Syncing..."); res = await self.pipeline.enrich(); self.last_run["enrich"] = res; self.refresh_main_view(f"Sync complete: {res.get('updated', 0)}")

    def action_run_analyze(self) -> None:
        self.refresh_main_view("Analyzing..."); res = self.pipeline.analyze(); self.last_run["analyze"] = res.get("metadata", {}); self.refresh_main_view(f"Analyze complete: {res.get('metadata', {}).get('n_battles', 0)}")

    def action_run_export(self) -> None:
        self.pipeline.analyze(); res = self.pipeline.export(); self.last_run["export"] = res; self.push_screen(TextViewScreen("Export", render_export(res.get("output_path", "")))); self.refresh_main_view("Export complete")


def cmd_tui() -> None: AnalyzerTUI().run()

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="WoWS Replay Analyzer")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("scan"); sub.add_parser("parse"); sub.add_parser("enrich"); sub.add_parser("analyze"); sub.add_parser("export"); sub.add_parser("run"); sub.add_parser("tui")
    s = sub.add_parser("settings"); s.add_argument("--app-id"); s.add_argument("--region", choices=["ASIA", "EU", "NA"]); s.add_argument("--game-root"); s.add_argument("--replay-folder"); s.add_argument("--min-battles", type=int); s.add_argument("--api-delay-ms", type=int); s.add_argument("--cache-ttl-hours", type=int); s.add_argument("--output-path"); s.add_argument("--language", choices=["en", "ja"])
    return parser

def main() -> None:
    parser = build_parser(); args = parser.parse_args()
    if args.command == "settings": cmd_settings(args)
    elif args.command == "scan": cmd_scan()
    elif args.command == "parse": cmd_parse()
    elif args.command == "enrich": cmd_enrich()
    elif args.command == "analyze": cmd_analyze()
    elif args.command == "export": cmd_export()
    elif args.command == "run": cmd_run()
    elif args.command == "tui": cmd_tui()
    else: parser.error(f"Unsupported command: {args.command}")

if __name__ == "__main__": main()
