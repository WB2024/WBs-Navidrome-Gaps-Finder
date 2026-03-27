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

| Key       | Action                        |
|-----------|-------------------------------|
| `↑` / `↓` | Navigate the artist/album list |
| `Enter`   | Select an artist              |
| `Escape`  | Go back                       |
| `s`       | Change database path          |
| `q`       | Quit                          |

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

## Notes

- The MusicBrainz API is rate-limited to **1 request per second**. Fetching large discographies may take a moment.
- Matching is done at the **release group** level (i.e. the album concept, not individual pressings/editions).
- Only artists with a `mbz_artist_id` in your Navidrome database are shown. Ensure your music files are properly tagged with MusicBrainz IDs for best results.

## License

This project is licensed under the [MIT License](LICENSE).

---

<a href="https://buymeacoffee.com/succinctrecords"><img src="https://img.shields.io/badge/Buy%20Me%20A%20Coffee-Support-yellow?logo=buy-me-a-coffee"></a>
