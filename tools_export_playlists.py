"""Export the m3u8 playlists as txt and csv files an Apple Music importer can read.

The m3u8 files in G:\Music\Playlists hold relative paths only, with no #EXTINF,
and a filename is not always "Artist - Title". Artist, title and album are
therefore read from the tags rather than from the filename.

Written to G:\Music\Playlists\export, one pair per playlist plus one pair for
the whole library:
  <name>.txt  one "Artist - Title" per line, the Soundiiz TXT import format
  <name>.csv  header title,artist,album, read by Soundiiz and TuneMyMusic
  All.txt / All.csv  every file in the library, playlist membership ignored

Entries whose artist could not be resolved, and paths that no longer exist, are
listed in export/untagged.txt so the ones needing a manual fix stay visible.
"""
import csv
import os

import mutagen

LIBRARY = r"G:\Music\Library"
PLAYLISTS = r"G:\Music\Playlists"
OUTPUT = os.path.join(PLAYLISTS, "export")
NAMES = ("Calm", "Indonesia", "Inggris", "Jepang", "Sedih", "Semangat")
AUDIO = (".flac", ".m4a", ".mp3")


def read_tags(tags, filename):
    """(artist, title, album) from the tags, falling back to the filename."""
    def first(*keys):
        for key in keys:
            value = (tags.get(key) or [""])[0].strip() if tags else ""
            if value:
                return value
        return ""

    artist, title, album = first("artist", "albumartist"), first("title"), first("album")
    stem = os.path.splitext(os.path.basename(filename))[0]
    if not artist and " - " in stem:
        # A name like "Adhitia Sofyan - Sesuatu Di Jogja.flac" still resolves;
        # "Nina.flac" does not, and that is what lands in untagged.txt.
        left, right = stem.split(" - ", 1)
        artist = left.strip()
        title = title or right.strip()
    return artist, title or stem, album


def collect(paths, name, notes):
    """Read every path into (artist, title, album) rows, logging what fails."""
    rows = []
    for path in paths:
        if not os.path.exists(path):
            notes.append(f"{name}\tmissing\t{path}")
            continue
        try:
            tags = mutagen.File(path, easy=True)
        except Exception as e:
            tags = None
            notes.append(f"{name}\tunreadable tags ({e.__class__.__name__})\t{path}")
        artist, title, album = read_tags(tags, path)
        if not artist:
            notes.append(f"{name}\tno artist\t{path}")
        rows.append((artist, title, album))
    return rows


def write(name, rows):
    with open(os.path.join(OUTPUT, name + ".txt"), "w", encoding="utf-8") as fh:
        for artist, title, _ in rows:
            fh.write(f"{artist} - {title}\n" if artist else f"{title}\n")

    with open(os.path.join(OUTPUT, name + ".csv"), "w", encoding="utf-8",
              newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["title", "artist", "album"])
        for artist, title, album in rows:
            writer.writerow([title, artist, album])

    print(f"{name}: {len(rows)} tracks")


def main():
    os.makedirs(OUTPUT, exist_ok=True)
    notes = []

    for name in NAMES:
        with open(os.path.join(PLAYLISTS, name + ".m3u8"), encoding="utf-8") as fh:
            entries = [line.strip() for line in fh
                       if line.strip() and not line.startswith("#")]
        paths = [os.path.normpath(os.path.join(PLAYLISTS, e)) for e in entries]
        write(name, collect(paths, name, notes))

    # All is taken from the library folder, not from the union of the playlists,
    # so a file that never made it into a playlist is still exported.
    everything = [os.path.join(LIBRARY, n) for n in sorted(os.listdir(LIBRARY))
                  if n.lower().endswith(AUDIO)]
    write("All", collect(everything, "All", notes))

    with open(os.path.join(OUTPUT, "untagged.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(notes) + ("\n" if notes else ""))
    print(f"\n{len(notes)} lines need checking, see {OUTPUT}\\untagged.txt")


if __name__ == "__main__":
    main()
