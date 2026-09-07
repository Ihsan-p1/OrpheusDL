# OrpheusDL, customised fork

A fork of [OrfiTeam/OrpheusDL](https://github.com/OrfiTeam/OrpheusDL), a modular music
archival tool in Python. This copy adds async downloads, an Apple Music module, and a set
of tools for auditing and repairing a local library.

Upstream documentation still applies for the module system, settings, and the built-in
sources. What follows is what this fork adds.

## Orpheus Healer (`orpheus_healer.py`)

Finds files in a local library that are not what their extension claims and replaces them.

- Reads the CSV reports exported by Soniq Tools.
- Picks out files flagged as upsampled, transcoded, or lossy transcode, the ones sold as
  lossless without being lossless.
- Tries to fetch a real lossless version from whichever sources are configured, Tidal and
  Apple Music included.
- Carries the original file's tags across to the new file: lyrics, ratings, replaygain,
  track IDs.
- Configured in `healer_config.toml`.

## Apple Music module (`modules/applemusic`)

- Downloads and decrypts Apple Music audio through the `gamdl` library and your own
  Widevine device file (`.wvd`).
- Authenticates with browser cookies from `config/cookies.txt`.
- Doubles as a fallback source for the healer when a fuzzy match is needed.

## Core changes

- Downloads run asynchronously on `aiohttp` and `aiofiles`, with connection pooling and
  exponential backoff, replacing the synchronous path.
- Windows path lengths are checked before writing, and filenames are shortened to stay
  inside the limit with 220 characters of headroom, rather than failing at the OS.
- Artist parsing splits collaborations without splitting names: `Simon & Garfunkel` stays
  one artist, while features and collaborations are separated and tagged.
- Provenance (`orpheus/provenance.py`) records the module, tier, codec, and download time
  in the file's own tags rather than a side database, because files get moved and renamed
  and any index keyed by path breaks the moment they do.

## Library tools

| Script | What it does |
|---|---|
| `quality_probe.py` | Repeatable audio measurements. Reports numbers, hands down no verdict, and stays quiet about anything it cannot prove. |
| `scan_library.py` | Walks a folder, probes every file, writes one CSV row each plus a FLAC / ALAC / lossy summary |
| `check_duplicates.py` | Duplicate detection by filename |
| `tools_dupes_by_tag.py` | Duplicate detection by artist and title tags, which catches what filename matching misses. Keeps the best copy by provenance, then bit depth, sample rate, and size. |
| `tools_backfill_genre.py` | Fills empty genre tags from the iTunes Search API, then Deezer. The Tidal module never writes a genre. |
| `tools_build_playlists.py` | Flattens the sorted tree into the library folder and writes m3u8 playlists |
| `tools_export_playlists.py` | Exports those playlists as txt and csv an Apple Music importer can read, reading artist, title, and album from tags rather than filenames |
| `tools_relocate_healed.py` | One-off: moves healer output back into its mood folder using the healer session JSON |
| `analyze_csv.py` | Counts verdicts and formats in a Soniq Tools CSV |

The `tools_*` scripts were written against specific drive layouts and still contain those
paths. Read the docstring at the top of one before running it.

## Getting started

Requirements: Python 3.9 or newer, and ffmpeg on the PATH.

```shell
pip install -r requirements.txt
python orpheus.py settings refresh
```

The second command writes the initial settings. Then fill in logins and preferences in
`config/settings.json`.

## Usage

Download by link:

```shell
python orpheus.py https://music.apple.com/us/album/...
```

Search and download:

```shell
python orpheus.py search tidal track "song name" "artist"
```

Repair a library, after setting the music directory and the Soniq Tools CSV path in
`healer_config.toml`:

```shell
python orpheus_healer.py
```

Take a quality census:

```shell
python scan_library.py --target-dir "D:\Music\sorted" --csv report.csv --workers 4
```

## Tests

Assert-based scripts, run directly:

```shell
python test_quality_probe.py
python test_healer.py
python test_provenance.py
python test_scan_library.py
python test_dupes_by_tag.py
python test_backfill_genre.py
python test_export_playlists.py
python test_rename_to_original.py
```

`docs/superpowers/` holds the design notes behind the quality verification work.

## Licence and secrets

Licensing follows the upstream project. Cookie files (`config/cookies.txt`,
`config/loginstorage.bin`), download output, and session databases are gitignored, and
they should stay that way.
