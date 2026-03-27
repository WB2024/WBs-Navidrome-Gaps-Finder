#!/usr/bin/env python3
"""Navidrome Gaps Finder - Find missing albums in your Navidrome music library."""

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

import requests
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Input, LoadingIndicator, Static
from textual.containers import Horizontal, Vertical

CONFIG_PATH = Path(__file__).parent / "config.json"
MB_BASE = "https://musicbrainz.org/ws/2"
MB_USER_AGENT = "NavidromeGapsFinder/1.0 (navidrome-gaps-finder)"


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def load_config() -> dict:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text())
    return {}


def save_config(config: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(config, indent=2))


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_artists(db_path: str) -> list[tuple]:
    """Return [(navidrome_id, name, mbz_artist_id)] for artists with a MusicBrainz ID."""
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, name, mbz_artist_id FROM artist "
            "WHERE mbz_artist_id != '' ORDER BY sort_artist_name"
        )
        return cur.fetchall()
    finally:
        conn.close()


def get_local_albums(db_path: str, artist_id: str) -> list[tuple]:
    """Return [(name, type, year, mbz_release_group_id)] for an artist's albums."""
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT name, mbz_album_type, min_year, mbz_release_group_id "
            "FROM album WHERE album_artist_id = ? ORDER BY min_year, name",
            (artist_id,),
        )
        return cur.fetchall()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# MusicBrainz API
# ---------------------------------------------------------------------------

def fetch_release_groups(mbz_artist_id: str) -> list[dict]:
    """Fetch all release groups for an artist from the MusicBrainz API (with pagination)."""
    headers = {"User-Agent": MB_USER_AGENT, "Accept": "application/json"}
    all_groups: list[dict] = []
    offset = 0
    limit = 100

    while True:
        resp = requests.get(
            f"{MB_BASE}/release-group",
            params={
                "artist": mbz_artist_id,
                "fmt": "json",
                "limit": limit,
                "offset": offset,
            },
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        all_groups.extend(data.get("release-groups", []))

        total = data.get("release-group-count", 0)
        offset += limit
        if offset >= total:
            break
        time.sleep(1.1)  # respect MusicBrainz rate-limit (1 req/s)

    return all_groups


# ═══════════════════════════════════════════════════════════════════════════
# Screens
# ═══════════════════════════════════════════════════════════════════════════

class SetupScreen(Screen):
    """Prompt the user for the Navidrome database path."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="setup-box"):
            yield Static(
                "Welcome to [bold]Navidrome Gaps Finder[/]!\n\n"
                "Enter the full path to your Navidrome database file:\n"
                "[dim](Tip: use Shift+Insert or right-click to paste in most terminals)[/]",
                id="setup-prompt",
            )
            yield Input(placeholder="/path/to/navidrome.db", id="db-input")
            yield Static("", id="setup-error")
        yield Footer()

    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Input.Submitted, "#db-input")
    def submit_path(self, event: Input.Submitted) -> None:
        path = event.value.strip().strip('"').strip("'")
        err = self.query_one("#setup-error", Static)

        if not path:
            err.update("[red]Please enter a path.[/]")
            return

        p = Path(path)
        if not p.exists():
            err.update(f"[red]File not found: {path}[/]")
            return
        if not p.is_file():
            err.update(f"[red]Not a file: {path}[/]")
            return

        # Verify the database contains the expected tables
        try:
            conn = sqlite3.connect(str(p))
            cur = conn.cursor()
            cur.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name IN ('artist', 'album')"
            )
            tables = {r[0] for r in cur.fetchall()}
            conn.close()
            if not {"artist", "album"}.issubset(tables):
                err.update("[red]Database is missing 'artist' or 'album' tables.[/]")
                return
        except Exception as exc:
            err.update(f"[red]Cannot open database: {exc}[/]")
            return

        config = load_config()
        config["db_path"] = str(p.resolve())
        save_config(config)
        self.dismiss(True)


class ComparisonScreen(Screen):
    """Show albums in the library vs. missing from MusicBrainz."""

    BINDINGS = [Binding("escape", "app.pop_screen", "Back")]

    def __init__(self, artist_name: str, artist_id: str, mbz_artist_id: str):
        super().__init__()
        self.artist_name = artist_name
        self.artist_id = artist_id
        self.mbz_artist_id = mbz_artist_id

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="comp-root"):
            yield Static(f"[bold]{self.artist_name}[/]", id="comp-title")
            yield Static(
                "Fetching release groups from MusicBrainz…", id="comp-status"
            )
            yield LoadingIndicator(id="comp-loading")
            with Horizontal(id="comp-tables"):
                with Vertical(id="owned-box"):
                    yield Static(
                        "[bold green]✓ In Your Library[/]", classes="table-heading"
                    )
                    yield DataTable(id="owned-table")
                with Vertical(id="missing-box"):
                    yield Static(
                        "[bold red]✗ Missing from Library[/]", classes="table-heading"
                    )
                    yield DataTable(id="missing-table")
            yield Static("", id="comp-detail")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#comp-tables").display = False
        self.query_one("#comp-detail").display = False
        self.do_comparison()

    @on(DataTable.RowHighlighted)
    def on_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key and event.row_key.value:
            rg_id = str(event.row_key.value)
            detail = self.query_one("#comp-detail", Static)
            detail.display = True
            detail.update(f"[dim]Release Group ID:[/] [bold]{rg_id}[/]")

    @work(thread=True)
    def do_comparison(self) -> None:
        config = load_config()
        db_path = config["db_path"]

        # --- local albums ---
        local = get_local_albums(db_path, self.artist_id)
        local_rg_ids = {row[3] for row in local if row[3]}

        # --- MusicBrainz release groups ---
        try:
            release_groups = fetch_release_groups(self.mbz_artist_id)
        except Exception as exc:
            self.app.call_from_thread(self._show_error, str(exc))
            return

        # Build owned list from local albums (include rg_id as row key)
        owned: list[tuple[str, str, str, str]] = []
        for name, atype, year, rg_id in local:
            year_str = str(year) if year else ""
            owned.append((name, atype or "", year_str, rg_id or ""))

        # Build missing list from MusicBrainz release groups not found locally
        missing: list[tuple[str, str, str, str]] = []
        for rg in release_groups:
            rg_id = rg.get("id", "")
            if rg_id not in local_rg_ids:
                title = rg.get("title", "")
                ptype = rg.get("primary-type", "") or ""
                stypes = rg.get("secondary-types") or []
                full_type = ptype
                if stypes:
                    full_type += " + " + ", ".join(stypes)
                date = rg.get("first-release-date", "") or ""
                missing.append((title, full_type, date, rg_id))

        self.app.call_from_thread(self._show_results, owned, missing)

    def _show_error(self, msg: str) -> None:
        self.query_one("#comp-loading").display = False
        self.query_one("#comp-status").update(f"[red]Error: {msg}[/]")

    def _show_results(self, owned: list, missing: list) -> None:
        self.query_one("#comp-loading").display = False
        self.query_one("#comp-status").update(
            f"[green]{len(owned)}[/] in library · [red]{len(missing)}[/] missing"
        )
        self.query_one("#comp-tables").display = True

        ot = self.query_one("#owned-table", DataTable)
        ot.cursor_type = "row"
        ot.add_columns("Album", "Type", "Year")
        for name, atype, year, rg_id in owned:
            ot.add_row(name, atype, year, key=rg_id or None)

        mt = self.query_one("#missing-table", DataTable)
        mt.cursor_type = "row"
        mt.add_columns("Album", "Type", "Date")
        for name, ftype, date, rg_id in sorted(missing, key=lambda r: r[2] or "9999"):
            mt.add_row(name, ftype, date, key=rg_id)


# ═══════════════════════════════════════════════════════════════════════════
# Main app
# ═══════════════════════════════════════════════════════════════════════════

class NavidromeGapsApp(App):
    """TUI to find gaps in your Navidrome music library."""

    TITLE = "Navidrome Gaps Finder"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("s", "setup", "Change DB Path"),
    ]

    def __init__(self, db_path: str | None = None):
        super().__init__()
        self.artists: list[tuple] = []
        self._cli_db_path = db_path

    CSS = """
    #setup-box {
        margin: 2 4;
        max-width: 100;
    }
    #setup-prompt {
        margin-bottom: 1;
    }
    #setup-error {
        margin-top: 1;
    }
    #filter-input {
        margin: 0 1;
    }
    #artist-table {
        height: 1fr;
        margin: 0 1;
    }
    #comp-root {
        height: 1fr;
    }
    #comp-title {
        margin: 1 1 0 1;
    }
    #comp-status {
        margin: 0 1 1 1;
    }
    #comp-tables {
        height: 1fr;
    }
    #owned-box, #missing-box {
        width: 1fr;
        height: 1fr;
        margin: 0 1;
    }
    .table-heading {
        margin-bottom: 1;
    }
    #owned-table, #missing-table {
        height: 1fr;
    }
    #comp-detail {
        margin: 0 1;
        height: auto;
        max-height: 2;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical():
            yield Input(placeholder="Type to filter artists…", id="filter-input")
            yield DataTable(id="artist-table")
        yield Footer()

    def on_mount(self) -> None:
        # If a path was supplied via CLI, save it and skip the setup screen
        if self._cli_db_path:
            p = Path(self._cli_db_path)
            if p.is_file():
                config = load_config()
                config["db_path"] = str(p.resolve())
                save_config(config)
                self._load_artists()
                return

        config = load_config()
        db_path = config.get("db_path", "")
        if not db_path or not Path(db_path).exists():
            self.push_screen(SetupScreen(), callback=self._on_setup)
        else:
            self._load_artists()

    def _on_setup(self, result) -> None:
        if result:
            self._load_artists()

    def _load_artists(self) -> None:
        config = load_config()
        self.artists = get_artists(config["db_path"])
        self._refresh_table()

    def _refresh_table(self, filter_text: str = "") -> None:
        table = self.query_one("#artist-table", DataTable)
        table.clear(columns=True)
        table.cursor_type = "row"
        table.add_columns("Artist", "MusicBrainz ID")
        ft = filter_text.lower()
        for nid, name, mbid in self.artists:
            if ft and ft not in name.lower():
                continue
            table.add_row(name, mbid, key=nid)

    @on(Input.Changed, "#filter-input")
    def on_filter(self, event: Input.Changed) -> None:
        self._refresh_table(event.value)

    @on(DataTable.RowSelected, "#artist-table")
    def on_artist_selected(self, event: DataTable.RowSelected) -> None:
        table = self.query_one("#artist-table", DataTable)
        row = table.get_row(event.row_key)
        name, mbid = row[0], row[1]
        nid = str(event.row_key.value)
        self.push_screen(ComparisonScreen(name, nid, mbid))

    def action_setup(self) -> None:
        self.push_screen(SetupScreen(), callback=self._on_setup)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Navidrome Gaps Finder")
    parser.add_argument(
        "--db",
        metavar="PATH",
        help="Path to the Navidrome database file (navidrome.db)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    NavidromeGapsApp(db_path=args.db).run()
