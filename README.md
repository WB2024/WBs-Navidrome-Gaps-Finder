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

On first launch, the app will prompt you for the path to your Navidrome database file. This is saved to `config.json` for future runs.

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

```
┌──────────────────────────────────────────────────────────┐
│  Navidrome Gaps Finder                                   │
├──────────────────────────────────────────────────────────┤
│  Type to filter artists…                                 │
│                                                          │
│  Artist                        │ MusicBrainz ID          │
│  ─────────────────────────────────────────────────────── │
│  2Pac                          │ 382f1005-e9ab-...       │
│  Dr. Dre                       │ a1c7a95b-3615-...       │
│  Nas                           │ 2f3f8fb1-e5dc-...       │
│  Snoop Dogg                    │ f90e8b26-9e52-...       │
│  ...                                                     │
└──────────────────────────────────────────────────────────┘
```

After selecting an artist:

```
┌──────────────────────────────────────────────────────────┐
│  2Pac                                                    │
│  7 in library · 12 missing                               │
│                                                          │
│  ✓ In Your Library       │  ✗ Missing from Library       │
│  ──────────────────────  │  ─────────────────────────    │
│  2Pacalypse Now          │  Thug Life: Volume 1          │
│  All Eyez on Me          │  Until the End of Time        │
│  Better Dayz             │  Loyal to the Game            │
│  Me Against the World    │  Pac's Life                   │
│  ...                     │  ...                          │
└──────────────────────────────────────────────────────────┘
```

## Notes

- The MusicBrainz API is rate-limited to **1 request per second**. Fetching large discographies may take a moment.
- Matching is done at the **release group** level (i.e. the album concept, not individual pressings/editions).
- Only artists with a `mbz_artist_id` in your Navidrome database are shown. Ensure your music files are properly tagged with MusicBrainz IDs for best results.

## License

This project is licensed under the [MIT License](LICENSE).

---

<a href="https://buymeacoffee.com/succinctrecords"><img src="https://img.shields.io/badge/Buy%20Me%20A%20Coffee-Support-yellow?logo=buy-me-a-coffee"></a>
