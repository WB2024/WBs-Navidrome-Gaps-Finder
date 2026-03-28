# 🎵 Navidrome Gaps Finder

A terminal UI application that helps you discover missing albums in your [Navidrome](https://www.navidrome.org/) music library by cross-referencing it with the [MusicBrainz](https://musicbrainz.org/) database.

<a href="https://buymeacoffee.com/succinctrecords"><img src="https://img.shields.io/badge/Buy%20Me%20A%20Coffee-Support-yellow?logo=buy-me-a-coffee"></a>

---

## How It Works

1. **Connects** to your Navidrome SQLite database
2. **Lists** all artists that have a MusicBrainz artist ID
3. **Fetches** the complete discography for a selected artist from the MusicBrainz API
4. **Compares** MusicBrainz release groups against your local library using `mbz_release_group_id`
5. **Displays** a side-by-side view of albums you own vs. albums you're missing
6. **Inspect tracks** for any album — view your local tracklist with full audio details, or browse MusicBrainz releases and their tracks
7. **Optionally integrates** with [Nicotine+](https://nicotine-plus.org/) — add missing albums directly to your Soulseek wishlist

## Requirements

- Python 3.10+
- Access to your Navidrome `navidrome.db` database file

## Installation

```bash
git clone https://github.com/WB2024/WBs-Navidrome-Gaps-Finder.git
cd WBs-Navidrome-Gaps-Finder
python3 -m venv venv
source venv/bin/activate        # Linux / macOS
# venv\Scripts\activate         # Windows
pip install -r requirements.txt
```

> **Note:** On modern Debian/Ubuntu systems, installing packages globally with `pip` is blocked ([PEP 668](https://peps.python.org/pep-0668/)). Using a virtual environment as shown above is the recommended approach.

## Usage

```bash
# Make sure the venv is activated first
source venv/bin/activate        # Linux / macOS
# venv\Scripts\activate         # Windows

python main.py
```

You can also pass the database path directly via the command line to skip the interactive prompt:

```bash
python main.py --db /path/to/navidrome.db
```

On first launch (without `--db`), the app will prompt you for the path to your Navidrome database file. This is saved to `config.json` for future runs.

> **Tip:** If you can't paste into the TUI input field, use `Shift+Insert` or right-click instead of `Ctrl+V`. Alternatively, use the `--db` flag shown above.

### Key Bindings

| Key       | Action                                          |
|-----------|--------------------------------------------------|
| `↑` / `↓` | Navigate the artist/album list                   |
| `Enter`   | Select an artist / inspect album tracks          |
| `Space`   | Toggle album selection (wishlist screen)          |
| `Escape`  | Go back                                          |
| `e`       | Export missing albums to CSV (comparison screen)  |
| `w`       | Add missing albums to Nicotine+ wishlist          |
| `a`       | Select / deselect all (wishlist screen)           |
| `n`       | Configure Nicotine+ config path                  |
| `s`       | Change database path                             |
| `q`       | Quit                                             |

Type in the filter box at the top to search for artists by name.

## Screenshots

### All Artists

The main screen lists every artist in your Navidrome library that has a MusicBrainz ID, along with their corresponding MBID.

![All Artists](Screenshots/All%20Artists.png)

### Filtering Artists

Type in the filter box to narrow down the list in real time. Select an artist with the arrow keys and press Enter.

![Artist Filter](Screenshots/Artist%20Filter.png)

### Comparison View — Morrissey

After selecting an artist, the app fetches their full discography from MusicBrainz and compares it against your library. The left panel shows what you already have; the right panel shows what's missing.

![Artist Results — Morrissey](Screenshots/Artist%20Results%201.png)

### Comparison View — Afroman

Another example — here only 1 album is in the library, with 54 missing release groups listed on the right along with their type and first release date.

![Artist Results — Afroman](Screenshots/Artist%20Results%202.png)

### Track Inspection — Local Album

Press `Enter` on an album in the **In Your Library** panel to view its full tracklist pulled from your Navidrome database. Each track shows disc/track number, title, duration, artist, file format, bitrate, and sample rate.

![Local Tracklist](Screenshots/LocalTracklist.webp)

### Track Inspection — MusicBrainz Release Selection

Press `Enter` on an album in the **Missing from Library** panel to browse its available releases on MusicBrainz. Releases are listed with their status, country, date, format, and track count. Select a release to view its tracks.

![MusicBrainz Release Select](Screenshots/Musicbrainz%20Release%20Select.webp)

### Track Inspection — MusicBrainz Tracklist

After selecting a release, the full tracklist is fetched from MusicBrainz showing disc/track number, title, and duration.

![MusicBrainz Tracklist](Screenshots/Musicbrainz%20TrackList.webp)

## Export Missing Albums to CSV

While viewing the comparison screen for an artist, press `e` to export all missing albums to a CSV file. The file is saved to your current working directory as `<Artist Name> - Missing Albums.csv` and contains:

| Column             | Description                                  |
|--------------------|----------------------------------------------|
| Artist             | Artist name                                  |
| Album              | Album / release group title                  |
| Type               | Release group type (e.g. Album, Single, EP)  |
| First Release Date | Earliest known release date from MusicBrainz |
| MusicBrainz URL    | Direct link to the release group page        |

## Nicotine+ Integration (Optional)

If you use [Nicotine+](https://nicotine-plus.org/) (a Soulseek client), you can add missing albums directly to your Nicotine+ wishlist (auto-search list).

### Setup

Press `n` at any time to configure the path to your Nicotine+ config folder — the directory that contains the `config` file (no extension). This is typically:

- **Linux:** `~/.config/nicotine/` or your Docker/container config mount
- **Windows:** `%APPDATA%\nicotine\`

You can also optionally provide a **Docker container name**. If set, the app will automatically restart the container after updating the wishlist so Nicotine+ picks up the changes immediately. If left blank, you'll need to restart Nicotine+ manually.

This setting is optional and saved to `config.json`. The rest of the app works without it.

### Adding to Wishlist

1. View the comparison screen for any artist
2. Press `w` to open the wishlist selection screen (if Nicotine+ isn't configured yet, you'll be prompted)
3. Use `Space` to toggle individual albums, or `a` to select/deselect all
4. Press `Enter` to confirm — selected albums are added to the `autosearch` list in your Nicotine+ config as `"Artist - Album"` search terms
5. Duplicates are automatically skipped

![Wishlist Selection](Screenshots/NicotineWishlistadd.png)

After confirming, the selected albums appear in the Nicotine+ wishlist and are auto-searched on Soulseek at regular intervals.

![Nicotine+ Wishlist](Screenshots/NicotineUIWishlist.webp)

> **Note:** Nicotine+ loads its config into memory at startup. If you provided a Docker container name during setup, the container is restarted automatically after updating the wishlist. Otherwise, restart Nicotine+ manually for changes to take effect.

## Notes

- The MusicBrainz API is rate-limited to **1 request per second**. Fetching large discographies may take a moment.
- Matching is done at the **release group** level (i.e. the album concept, not individual pressings/editions).
- Only artists with a `mbz_artist_id` in your Navidrome database are shown. Ensure your music files are properly tagged with MusicBrainz IDs for best results.

## License

This project is licensed under the [MIT License](LICENSE).

---

<a href="https://buymeacoffee.com/succinctrecords"><img src="https://img.shields.io/badge/Buy%20Me%20A%20Coffee-Support-yellow?logo=buy-me-a-coffee"></a>
