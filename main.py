#!/usr/bin/env python3
"""Navidrome Gaps Finder - Find missing albums in your Navidrome music library."""

import argparse
import ast
import csv
import json
import sqlite3
import subprocess
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


def get_artists_without_mbid(db_path: str) -> list[tuple]:
    """Return [(navidrome_id, name)] for artists without a MusicBrainz ID."""
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, name FROM artist "
            "WHERE mbz_artist_id = '' OR mbz_artist_id IS NULL "
            "ORDER BY sort_artist_name"
        )
        return cur.fetchall()
    finally:
        conn.close()


def set_artist_mbid(db_path: str, artist_id: str, mbz_artist_id: str) -> None:
    """Update the MusicBrainz artist ID for a given artist."""
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE artist SET mbz_artist_id = ? WHERE id = ?",
            (mbz_artist_id, artist_id),
        )
        conn.commit()
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


def get_local_tracks(db_path: str, album_artist_id: str, album_name: str) -> list[tuple]:
    """Return [(disc_number, track_number, title, duration, artist, suffix, bit_rate, sample_rate)] for an album."""
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT mf.disc_number, mf.track_number, mf.title, mf.duration, "
            "mf.artist, mf.suffix, mf.bit_rate, mf.sample_rate "
            "FROM media_file mf "
            "JOIN album a ON mf.album_id = a.id "
            "WHERE a.album_artist_id = ? AND a.name = ? "
            "ORDER BY mf.disc_number, mf.track_number",
            (album_artist_id, album_name),
        )
        return cur.fetchall()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Nicotine+ config helpers
# ---------------------------------------------------------------------------

def read_nicotine_autosearch(config_dir: str) -> list[str]:
    """Read the autosearch wishlist from a Nicotine+ config file."""
    config_file = Path(config_dir) / "config"
    if not config_file.exists():
        return []
    text = config_file.read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("autosearch"):
            _, _, value = stripped.partition("=")
            value = value.strip()
            try:
                result = ast.literal_eval(value)
                if isinstance(result, list):
                    return [str(item) for item in result]
            except (ValueError, SyntaxError):
                pass
            return []
    return []


def write_nicotine_autosearch(config_dir: str, items: list[str]) -> None:
    """Write the autosearch wishlist to a Nicotine+ config file."""
    config_file = Path(config_dir) / "config"
    text = config_file.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    new_value = repr(items)
    found = False
    for i, line in enumerate(lines):
        if line.strip().startswith("autosearch"):
            ending = "\n"
            if line.endswith("\r\n"):
                ending = "\r\n"
            elif not line.endswith("\n"):
                ending = ""
            lines[i] = f"autosearch = {new_value}{ending}"
            found = True
            break
    if not found:
        for i, line in enumerate(lines):
            if line.strip() == "[server]":
                ending = "\n"
                if line.endswith("\r\n"):
                    ending = "\r\n"
                lines.insert(i + 1, f"autosearch = {new_value}{ending}")
                break
    config_file.write_text("".join(lines), encoding="utf-8")


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


def fetch_releases_for_group(release_group_id: str) -> list[dict]:
    """Fetch all releases belonging to a release group."""
    headers = {"User-Agent": MB_USER_AGENT, "Accept": "application/json"}
    all_releases: list[dict] = []
    offset = 0
    limit = 100

    while True:
        resp = requests.get(
            f"{MB_BASE}/release",
            params={
                "release-group": release_group_id,
                "fmt": "json",
                "limit": limit,
                "offset": offset,
            },
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        all_releases.extend(data.get("releases", []))

        total = data.get("release-count", 0)
        offset += limit
        if offset >= total:
            break
        time.sleep(1.1)

    return all_releases


def fetch_release_tracks(release_id: str) -> list[dict]:
    """Fetch the full track list for a specific release (inc=recordings)."""
    headers = {"User-Agent": MB_USER_AGENT, "Accept": "application/json"}
    resp = requests.get(
        f"{MB_BASE}/release/{release_id}",
        params={"inc": "recordings", "fmt": "json"},
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    tracks: list[dict] = []
    for medium in data.get("media", []):
        disc = medium.get("position", 1)
        for track in medium.get("tracks", []):
            rec = track.get("recording", {})
            tracks.append({
                "disc": disc,
                "number": track.get("number", ""),
                "title": track.get("title", "") or rec.get("title", ""),
                "length": track.get("length") or rec.get("length"),
            })
    return tracks


def search_musicbrainz_artists(query: str) -> list[dict]:
    """Search the MusicBrainz API for artists matching the query."""
    headers = {"User-Agent": MB_USER_AGENT, "Accept": "application/json"}
    resp = requests.get(
        f"{MB_BASE}/artist",
        params={"query": query, "fmt": "json", "limit": 25},
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("artists", [])


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


class NicotineSetupScreen(Screen):
    """Prompt the user for the Nicotine+ config directory path (optional)."""

    BINDINGS = [Binding("escape", "cancel", "Cancel / Skip")]

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="nic-setup-box"):
            yield Static(
                "[bold]Nicotine+ Integration[/] [dim](optional)[/]\n\n"
                "Enter the path to your Nicotine+ config folder\n"
                "(the directory containing the [bold]config[/] file):\n"
                "[dim](Press Escape to skip)[/]",
                id="nic-setup-prompt",
            )
            yield Input(placeholder="/path/to/nicotine/config/folder", id="nic-input")
            yield Static(
                "\n[bold]Docker container name[/] [dim](optional — leave blank if not using Docker)[/]\n"
                "If provided, the container will be restarted automatically\n"
                "after updating the wishlist so Nicotine+ picks up the changes.",
                id="nic-docker-prompt",
            )
            yield Input(placeholder="e.g. nicotine-plus", id="nic-docker-input")
            yield Static("", id="nic-setup-error")
        yield Footer()

    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(Input.Submitted, "#nic-input")
    def on_path_submitted(self, event: Input.Submitted) -> None:
        self.query_one("#nic-docker-input", Input).focus()

    @on(Input.Submitted, "#nic-docker-input")
    def on_docker_submitted(self, event: Input.Submitted) -> None:
        self._save()

    def _save(self) -> None:
        path = self.query_one("#nic-input", Input).value.strip().strip('"').strip("'")
        err = self.query_one("#nic-setup-error", Static)

        if not path:
            err.update("[red]Please enter a path or press Escape to skip.[/]")
            return

        p = Path(path)
        if not p.exists():
            err.update(f"[red]Directory not found: {path}[/]")
            return
        if not p.is_dir():
            err.update(f"[red]Not a directory: {path}[/]")
            return

        config_file = p / "config"
        if not config_file.exists():
            err.update(f"[red]No 'config' file found in {path}[/]")
            return

        container = self.query_one("#nic-docker-input", Input).value.strip()

        config = load_config()
        config["nicotine_config_path"] = str(p.resolve())
        if container:
            config["nicotine_container"] = container
        else:
            config.pop("nicotine_container", None)
        save_config(config)
        self.dismiss(True)


class ComparisonScreen(Screen):
    """Show albums in the library vs. missing from MusicBrainz."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("e", "export_csv", "Export CSV"),
        Binding("w", "add_to_wishlist", "Wishlist"),
    ]

    def __init__(self, artist_name: str, artist_id: str, mbz_artist_id: str):
        super().__init__()
        self.artist_name = artist_name
        self.artist_id = artist_id
        self.mbz_artist_id = mbz_artist_id
        self._missing_data: list[tuple[str, str, str, str]] = []

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
            # Row keys are stored as "idx:rg_id" to guarantee uniqueness
            raw = str(event.row_key.value)
            rg_id = raw.split(":", 1)[1] if ":" in raw else raw
            detail = self.query_one("#comp-detail", Static)
            detail.display = True
            if rg_id:
                detail.update(
                    f"[dim]Release Group ID:[/] [bold]{rg_id}[/]  "
                    f"[dim](https://musicbrainz.org/release-group/{rg_id})[/]"
                )
            else:
                detail.update("[dim]No MusicBrainz Release Group ID[/]")

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
        self._owned_count = len(owned)
        self.query_one("#comp-status").update(
            f"[green]{len(owned)}[/] in library · [red]{len(missing)}[/] missing"
        )
        self.query_one("#comp-tables").display = True

        self._missing_data = sorted(missing, key=lambda r: r[2] or "9999")

        ot = self.query_one("#owned-table", DataTable)
        ot.cursor_type = "row"
        ot.add_columns("Album", "Type", "Year")
        for i, (name, atype, year, rg_id) in enumerate(owned):
            ot.add_row(name, atype, year, key=f"{i}:{rg_id}")

        mt = self.query_one("#missing-table", DataTable)
        mt.cursor_type = "row"
        mt.add_columns("Album", "Type", "Date")
        for i, (name, ftype, date, rg_id) in enumerate(self._missing_data):
            mt.add_row(name, ftype, date, key=f"m{i}:{rg_id}")

    def action_export_csv(self) -> None:
        """Export missing albums to a CSV file."""
        if not self._missing_data:
            self.query_one("#comp-status").update("[yellow]No missing albums to export.[/]")
            return

        safe_name = "".join(c if c.isalnum() or c in " _-" else "_" for c in self.artist_name).strip()
        filename = f"{safe_name} - Missing Albums.csv"
        filepath = Path.cwd() / filename

        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Artist", "Album", "Type", "First Release Date", "MusicBrainz URL"])
            for name, ftype, date, rg_id in self._missing_data:
                mb_url = f"https://musicbrainz.org/release-group/{rg_id}" if rg_id else ""
                writer.writerow([self.artist_name, name, ftype, date, mb_url])

        self.query_one("#comp-status").update(
            f"[green]{self._owned_count}[/] in library · "
            f"[red]{len(self._missing_data)}[/] missing · "
            f"[bold cyan]Exported to {filename}[/]"
        )

    @on(DataTable.RowSelected, "#owned-table")
    def on_owned_selected(self, event: DataTable.RowSelected) -> None:
        table = self.query_one("#owned-table", DataTable)
        row = table.get_row(event.row_key)
        album_name = row[0]
        self.app.push_screen(
            LocalTracksScreen(album_name, self.artist_name, self.artist_id)
        )

    @on(DataTable.RowSelected, "#missing-table")
    def on_missing_selected(self, event: DataTable.RowSelected) -> None:
        raw = str(event.row_key.value)
        rg_id = raw.split(":", 1)[1] if ":" in raw else raw
        if not rg_id:
            return
        table = self.query_one("#missing-table", DataTable)
        row = table.get_row(event.row_key)
        album_name = row[0]
        self.app.push_screen(MBReleasesScreen(album_name, rg_id))

    def action_add_to_wishlist(self) -> None:
        """Open the wishlist selection screen for missing albums."""
        if not self._missing_data:
            return
        config = load_config()
        nic_path = config.get("nicotine_config_path", "")
        if not nic_path:
            self.app.push_screen(NicotineSetupScreen(), callback=self._on_nicotine_setup)
        else:
            self.app.push_screen(
                WishlistScreen(self.artist_name, self._missing_data),
                callback=self._on_wishlist_done,
            )

    def _on_nicotine_setup(self, result) -> None:
        if result:
            self.app.push_screen(
                WishlistScreen(self.artist_name, self._missing_data),
                callback=self._on_wishlist_done,
            )

    def _on_wishlist_done(self, added) -> None:
        if added is not None and added > 0:
            self.query_one("#comp-status").update(
                f"[green]{self._owned_count}[/] in library · "
                f"[red]{len(self._missing_data)}[/] missing · "
                f"[bold cyan]Added {added} album(s) to Nicotine+ wishlist[/]"
            )


class LocalTracksScreen(Screen):
    """Show tracks for a local album from the Navidrome database."""

    BINDINGS = [Binding("escape", "app.pop_screen", "Back")]

    def __init__(self, album_name: str, artist_name: str, artist_id: str):
        super().__init__()
        self.album_name = album_name
        self.artist_name = artist_name
        self.artist_id = artist_id

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="tracks-root"):
            yield Static(
                f"[bold]{self.artist_name}[/] — [italic]{self.album_name}[/]  [dim](Local)[/]",
                id="tracks-title",
            )
            yield DataTable(id="tracks-table")
        yield Footer()

    def on_mount(self) -> None:
        config = load_config()
        tracks = get_local_tracks(config["db_path"], self.artist_id, self.album_name)

        table = self.query_one("#tracks-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("Disc", "#", "Title", "Duration", "Artist", "Format", "Bitrate", "Sample Rate")
        for disc, num, title, duration, artist, suffix, bitrate, sample_rate in tracks:
            mins, secs = divmod(int(duration), 60)
            dur_str = f"{mins}:{secs:02d}"
            br_str = f"{bitrate} kbps" if bitrate else ""
            sr_str = f"{sample_rate} Hz" if sample_rate else ""
            table.add_row(
                str(disc), str(num), title, dur_str, artist,
                suffix.upper() if suffix else "", br_str, sr_str,
            )


class MBReleasesScreen(Screen):
    """Show releases within a MusicBrainz release group and let the user pick one to see tracks."""

    BINDINGS = [Binding("escape", "app.pop_screen", "Back")]

    def __init__(self, album_name: str, release_group_id: str):
        super().__init__()
        self.album_name = album_name
        self.release_group_id = release_group_id

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="releases-root"):
            yield Static(
                f"[bold]{self.album_name}[/]  [dim](Select a release to view tracks)[/]",
                id="releases-title",
            )
            yield LoadingIndicator(id="releases-loading")
            yield DataTable(id="releases-table")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#releases-table").display = False
        self.fetch_releases()

    @work(thread=True)
    def fetch_releases(self) -> None:
        try:
            releases = fetch_releases_for_group(self.release_group_id)
        except Exception as exc:
            self.app.call_from_thread(self._show_error, str(exc))
            return
        self.app.call_from_thread(self._show_releases, releases)

    def _show_error(self, msg: str) -> None:
        self.query_one("#releases-loading").display = False
        self.query_one("#releases-title", Static).update(f"[red]Error: {msg}[/]")

    def _show_releases(self, releases: list[dict]) -> None:
        self.query_one("#releases-loading").display = False
        table = self.query_one("#releases-table", DataTable)
        table.display = True
        table.cursor_type = "row"
        table.add_columns("Title", "Status", "Country", "Date", "Format", "Tracks")
        for rel in sorted(releases, key=lambda r: r.get("date", "") or "9999"):
            title = rel.get("title", "")
            status = rel.get("status", "")
            country = rel.get("country", "")
            date = rel.get("date", "")
            media = rel.get("media", [])
            formats = ", ".join({m.get("format", "?") for m in media if m.get("format")})
            track_count = sum(m.get("track-count", 0) for m in media)
            table.add_row(
                title, status, country, date, formats, str(track_count),
                key=rel.get("id", ""),
            )

    @on(DataTable.RowSelected, "#releases-table")
    def on_release_selected(self, event: DataTable.RowSelected) -> None:
        release_id = str(event.row_key.value)
        if not release_id:
            return
        table = self.query_one("#releases-table", DataTable)
        row = table.get_row(event.row_key)
        release_title = row[0]
        self.app.push_screen(MBTracksScreen(release_title, release_id))


class MBTracksScreen(Screen):
    """Show tracks for a specific MusicBrainz release."""

    BINDINGS = [Binding("escape", "app.pop_screen", "Back")]

    def __init__(self, release_title: str, release_id: str):
        super().__init__()
        self.release_title = release_title
        self.release_id = release_id

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="mb-tracks-root"):
            yield Static(
                f"[bold]{self.release_title}[/]  [dim](MusicBrainz)[/]",
                id="mb-tracks-title",
            )
            yield LoadingIndicator(id="mb-tracks-loading")
            yield DataTable(id="mb-tracks-table")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#mb-tracks-table").display = False
        self.fetch_tracks()

    @work(thread=True)
    def fetch_tracks(self) -> None:
        try:
            tracks = fetch_release_tracks(self.release_id)
        except Exception as exc:
            self.app.call_from_thread(self._show_error, str(exc))
            return
        self.app.call_from_thread(self._show_tracks, tracks)

    def _show_error(self, msg: str) -> None:
        self.query_one("#mb-tracks-loading").display = False
        self.query_one("#mb-tracks-title", Static).update(f"[red]Error: {msg}[/]")

    def _show_tracks(self, tracks: list[dict]) -> None:
        self.query_one("#mb-tracks-loading").display = False
        table = self.query_one("#mb-tracks-table", DataTable)
        table.display = True
        table.cursor_type = "row"
        table.add_columns("Disc", "#", "Title", "Duration")
        for t in tracks:
            length = t.get("length")
            if length:
                total_secs = int(length) // 1000
                mins, secs = divmod(total_secs, 60)
                dur_str = f"{mins}:{secs:02d}"
            else:
                dur_str = "?"
            table.add_row(
                str(t.get("disc", "")),
                str(t.get("number", "")),
                t.get("title", ""),
                dur_str,
            )


class WishlistScreen(Screen):
    """Select missing albums to add to Nicotine+ wishlist."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("space", "toggle_selection", "Toggle"),
        Binding("a", "select_all", "Select All"),
    ]

    def __init__(self, artist_name: str, missing_albums: list[tuple[str, str, str, str]]):
        super().__init__()
        self.artist_name = artist_name
        self.missing_albums = missing_albums
        self.selected: set[int] = set()

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="wishlist-root"):
            yield Static(
                f"[bold]{self.artist_name}[/] — [italic]Add to Nicotine+ Wishlist[/]",
                id="wishlist-title",
            )
            yield Static(
                "[dim]Space[/] toggle · [dim]A[/] select all · [dim]Enter[/] add to wishlist",
                id="wishlist-hint",
            )
            yield DataTable(id="wishlist-table")
            yield Static("", id="wishlist-status")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#wishlist-table", DataTable)
        table.cursor_type = "row"
        table.add_column("\u2713", key="check")
        table.add_columns("Album", "Type", "Date")
        for i, (name, ftype, date, rg_id) in enumerate(self.missing_albums):
            table.add_row("", name, ftype, date, key=str(i))
        self._update_status()

    def _update_status(self) -> None:
        self.query_one("#wishlist-status", Static).update(
            f"[cyan]{len(self.selected)}[/] of [bold]{len(self.missing_albums)}[/] selected"
        )

    def _refresh_check(self, index: int) -> None:
        table = self.query_one("#wishlist-table", DataTable)
        mark = "\u2713" if index in self.selected else ""
        table.update_cell(str(index), "check", mark)

    def action_toggle_selection(self) -> None:
        table = self.query_one("#wishlist-table", DataTable)
        cursor_row = table.cursor_row
        if cursor_row < 0 or cursor_row >= len(self.missing_albums):
            return
        if cursor_row in self.selected:
            self.selected.discard(cursor_row)
        else:
            self.selected.add(cursor_row)
        self._refresh_check(cursor_row)
        self._update_status()

    def action_select_all(self) -> None:
        if len(self.selected) == len(self.missing_albums):
            self.selected.clear()
        else:
            self.selected = set(range(len(self.missing_albums)))
        for i in range(len(self.missing_albums)):
            self._refresh_check(i)
        self._update_status()

    @on(DataTable.RowSelected, "#wishlist-table")
    def on_wishlist_confirm(self, event: DataTable.RowSelected) -> None:
        if not self.selected:
            self.query_one("#wishlist-status", Static).update(
                "[yellow]No albums selected.[/]"
            )
            return

        config = load_config()
        nic_path = config.get("nicotine_config_path", "")
        container = config.get("nicotine_container", "")

        existing = read_nicotine_autosearch(nic_path)
        existing_lower = {item.lower() for item in existing}

        added = 0
        for idx in sorted(self.selected):
            album_name = self.missing_albums[idx][0]
            search_term = f"{self.artist_name} - {album_name}"
            if search_term.lower() not in existing_lower:
                existing.append(search_term)
                existing_lower.add(search_term.lower())
                added += 1

        if added == 0:
            self.query_one("#wishlist-status", Static).update(
                "[yellow]All selected albums are already in the wishlist.[/]"
            )
            return

        write_nicotine_autosearch(nic_path, existing)

        if container:
            self.query_one("#wishlist-status", Static).update(
                f"[cyan]Added {added} album(s). Restarting Nicotine+ container…[/]"
            )
            self._restart_container(container, added)
        else:
            self.dismiss(added)

    @work(thread=True)
    def _restart_container(self, container: str, added: int) -> None:
        try:
            subprocess.run(
                ["docker", "restart", container],
                check=True,
                capture_output=True,
                timeout=30,
            )
        except FileNotFoundError:
            self.app.call_from_thread(self._show_restart_error, added, "docker command not found")
            return
        except subprocess.TimeoutExpired:
            self.app.call_from_thread(self._show_restart_error, added, "container restart timed out")
            return
        except subprocess.CalledProcessError as exc:
            msg = exc.stderr.decode(errors="replace").strip() if exc.stderr else str(exc)
            self.app.call_from_thread(self._show_restart_error, added, msg)
            return
        self.app.call_from_thread(self.dismiss, added)

    def _show_restart_error(self, added: int, msg: str) -> None:
        self.query_one("#wishlist-status", Static).update(
            f"[green]Added {added} album(s) to wishlist.[/] "
            f"[red]Container restart failed: {msg}[/]\n"
            f"[dim]Restart Nicotine+ manually for changes to take effect.[/]"
        )


class UntaggedArtistsScreen(Screen):
    """List artists without a MusicBrainz ID and allow tagging them."""

    BINDINGS = [Binding("escape", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="untagged-root"):
            yield Static(
                "[bold]Artists Missing MusicBrainz IDs[/]",
                id="untagged-title",
            )
            yield Input(placeholder="Type to filter…", id="untagged-filter")
            yield DataTable(id="untagged-table")
            yield Static("", id="untagged-status")
        yield Footer()

    def on_mount(self) -> None:
        config = load_config()
        self._db_path = config["db_path"]
        self._artists = get_artists_without_mbid(self._db_path)
        self._refresh_table()

    def _refresh_table(self, filter_text: str = "") -> None:
        table = self.query_one("#untagged-table", DataTable)
        table.clear(columns=True)
        table.cursor_type = "row"
        table.add_columns("Artist")
        ft = filter_text.lower()
        for nid, name in self._artists:
            if ft and ft not in name.lower():
                continue
            table.add_row(name, key=nid)
        self.query_one("#untagged-status", Static).update(
            f"[dim]{len(self._artists)} artist(s) without MusicBrainz IDs[/]"
        )

    @on(Input.Changed, "#untagged-filter")
    def on_filter(self, event: Input.Changed) -> None:
        self._refresh_table(event.value)

    @on(DataTable.RowSelected, "#untagged-table")
    def on_artist_selected(self, event: DataTable.RowSelected) -> None:
        table = self.query_one("#untagged-table", DataTable)
        row = table.get_row(event.row_key)
        artist_name = row[0]
        artist_id = str(event.row_key.value)
        self.app.push_screen(
            MBArtistSearchScreen(artist_name, artist_id, self._db_path),
            callback=self._on_tagged,
        )

    def _on_tagged(self, result) -> None:
        if result:
            self._artists = get_artists_without_mbid(self._db_path)
            self._refresh_table(
                self.query_one("#untagged-filter", Input).value
            )
            self.query_one("#untagged-status", Static).update(
                f"[green]MusicBrainz ID applied![/]  "
                f"[dim]{len(self._artists)} artist(s) remaining[/]"
            )


class MBArtistSearchScreen(Screen):
    """Search MusicBrainz for an artist and let the user pick the correct match."""

    BINDINGS = [Binding("escape", "app.pop_screen", "Back")]

    def __init__(self, artist_name: str, artist_id: str, db_path: str):
        super().__init__()
        self.artist_name = artist_name
        self.artist_id = artist_id
        self.db_path = db_path
        self._results: list[dict] = []

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="mb-search-root"):
            yield Static(
                f"Searching MusicBrainz for [bold]{self.artist_name}[/]…",
                id="mb-search-title",
            )
            yield LoadingIndicator(id="mb-search-loading")
            yield DataTable(id="mb-search-table")
            yield Static("", id="mb-search-detail")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#mb-search-table").display = False
        self.query_one("#mb-search-detail").display = False
        self.do_search()

    @work(thread=True)
    def do_search(self) -> None:
        try:
            results = search_musicbrainz_artists(self.artist_name)
        except Exception as exc:
            self.app.call_from_thread(self._show_error, str(exc))
            return
        self.app.call_from_thread(self._show_results, results)

    def _show_error(self, msg: str) -> None:
        self.query_one("#mb-search-loading").display = False
        self.query_one("#mb-search-title", Static).update(f"[red]Error: {msg}[/]")

    def _show_results(self, results: list[dict]) -> None:
        self.query_one("#mb-search-loading").display = False
        self._results = results

        if not results:
            self.query_one("#mb-search-title", Static).update(
                f"No MusicBrainz results for [bold]{self.artist_name}[/]"
            )
            return

        self.query_one("#mb-search-title", Static).update(
            f"[bold]{self.artist_name}[/] — [dim]Select the correct artist[/]"
        )

        table = self.query_one("#mb-search-table", DataTable)
        table.display = True
        table.cursor_type = "row"
        table.add_columns("Score", "Name", "Disambiguation", "Type", "Country", "Active")
        for i, art in enumerate(results):
            score = str(art.get("score", ""))
            name = art.get("name", "")
            disamb = art.get("disambiguation", "")
            atype = art.get("type", "")
            country = art.get("country", "")
            begin = art.get("life-span", {}).get("begin", "")
            end = art.get("life-span", {}).get("end", "")
            ended = art.get("life-span", {}).get("ended", False)
            active = ""
            if begin:
                active = f"{begin} – "
                active += end if end else ("present" if not ended else "?")
            table.add_row(score, name, disamb, atype, country, active, key=str(i))

    @on(DataTable.RowHighlighted, "#mb-search-table")
    def on_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key and event.row_key.value is not None:
            idx = int(event.row_key.value)
            if 0 <= idx < len(self._results):
                art = self._results[idx]
                mbid = art.get("id", "")
                detail = self.query_one("#mb-search-detail", Static)
                detail.display = True
                tags = ", ".join(t.get("name", "") for t in art.get("tags", [])[:5])
                parts = [f"[dim]MBID:[/] [bold]{mbid}[/]"]
                if tags:
                    parts.append(f"[dim]Tags:[/] {tags}")
                detail.update("  ".join(parts))

    @on(DataTable.RowSelected, "#mb-search-table")
    def on_result_selected(self, event: DataTable.RowSelected) -> None:
        idx = int(event.row_key.value)
        if idx < 0 or idx >= len(self._results):
            return
        art = self._results[idx]
        mbid = art.get("id", "")
        if not mbid:
            return
        set_artist_mbid(self.db_path, self.artist_id, mbid)
        self.dismiss(True)


# ═══════════════════════════════════════════════════════════════════════════
# Main app
# ═══════════════════════════════════════════════════════════════════════════

class NavidromeGapsApp(App):
    """TUI to find gaps in your Navidrome music library."""

    TITLE = "Navidrome Gaps Finder"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("s", "setup", "Change DB Path"),
        Binding("n", "nicotine_setup", "Nicotine+ Config"),
        Binding("u", "untagged", "Untagged Artists"),
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
    #tracks-root, #releases-root, #mb-tracks-root {
        height: 1fr;
    }
    #tracks-title, #releases-title, #mb-tracks-title {
        margin: 1 1 1 1;
    }
    #tracks-table, #releases-table, #mb-tracks-table {
        height: 1fr;
        margin: 0 1;
    }
    #nic-setup-box {
        margin: 2 4;
        max-width: 100;
    }
    #nic-setup-prompt {
        margin-bottom: 1;
    }
    #nic-docker-prompt {
        margin-top: 1;
        margin-bottom: 1;
    }
    #nic-setup-error {
        margin-top: 1;
    }
    #wishlist-root {
        height: 1fr;
    }
    #wishlist-title {
        margin: 1 1 0 1;
    }
    #wishlist-hint {
        margin: 0 1 1 1;
    }
    #wishlist-table {
        height: 1fr;
        margin: 0 1;
    }
    #wishlist-status {
        margin: 0 1;
        height: auto;
    }
    #untagged-root {
        height: 1fr;
    }
    #untagged-title {
        margin: 1 1 0 1;
    }
    #untagged-filter {
        margin: 0 1;
    }
    #untagged-table {
        height: 1fr;
        margin: 0 1;
    }
    #untagged-status {
        margin: 0 1;
        height: auto;
    }
    #mb-search-root {
        height: 1fr;
    }
    #mb-search-title {
        margin: 1 1 1 1;
    }
    #mb-search-table {
        height: 1fr;
        margin: 0 1;
    }
    #mb-search-detail {
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

    def action_nicotine_setup(self) -> None:
        self.push_screen(NicotineSetupScreen())

    def action_untagged(self) -> None:
        config = load_config()
        if not config.get("db_path"):
            return
        self.push_screen(
            UntaggedArtistsScreen(),
            callback=self._on_untagged_return,
        )

    def _on_untagged_return(self, result) -> None:
        self._load_artists()


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
