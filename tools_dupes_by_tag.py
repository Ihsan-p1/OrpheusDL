"""Fold together songs that have more than one file in G:\\Music\\Library.

check_duplicates.py matches filenames, so one song stored as "Peace Sign.flac"
and as "Geek Music - My Hero Academia - Peace Sign - Season 2 Opening
Theme.flac" slips through. Grouping here uses the artist and title tags, which
are the same in both files.

What is kept: provenance first, then bit depth, sample rate, size. The losers
are moved to _FAKE_BACKUP, not deleted. The playlists are rewritten so their
entries point at the file that was kept.

A file is only released when its raw audio MD5 matches the keeper's. FLAC
stores that MD5 itself in the STREAMINFO block, so identical content can be
proven sample by sample instead of inferred from the name, the duration or the
size. A group whose members differ in MD5 is reported and left whole: durations
can match exactly while the content is a different master.

    python tools_dupes_by_tag.py            # report only
    python tools_dupes_by_tag.py --apply    # move files and rewrite playlists
"""
import collections
import os
import re
import shutil
import sys
import unicodedata
from datetime import datetime

import mutagen
from mutagen.flac import FLAC

from orpheus.provenance import read_provenance

LIBRARY = r"G:\Music\Library"
PLAYLISTS = r"G:\Music\Playlists"
BACKUP = r"G:\Music\_FAKE_BACKUP"
AUDIO = (".flac", ".m4a", ".mp3")

# Files released before this script was translated carry the older "_kembar_"
# marker instead. Nothing reads the marker back, it only keeps the backup
# folder readable by eye.
DUPE_MARKER = "_dupe_"

# Kana voicing marks. Stripped along with the other accents, "が" becomes "か"
# and that is a different word, so both are held back from the folding.
KANA_VOICE_MARKS = {"\u3099", "\u309a"}


def normalize(s):
    """Lowercase, fold accents, turn every separator into a space.

    \\W with the unicode flag, not [^a-z0-9]: a Japanese title is wiped out if
    non-ASCII is dropped, and every CJK title then collapses into one bogus
    group.

    Accents are folded because tags and catalogues often write the same name
    with different letters: "JAŸ-Z" for "JAY-Z", "Bouwéy" for "Bouwey".
    """
    decomposed = unicodedata.normalize("NFKD", s.lower())
    without_accents = "".join(c for c in decomposed
                              if unicodedata.category(c) != "Mn" or c in KANA_VOICE_MARKS)
    # Recomposed so a voicing mark attaches to its kana again; left apart, \\W+
    # turns it into a space and cuts one letter into two.
    recomposed = unicodedata.normalize("NFC", without_accents)
    return re.sub(r"\W+", " ", recomposed, flags=re.UNICODE).strip()


def tag_key(tags):
    """The normalized (artist, title), or None when the title is empty."""
    artist = (tags.get("artist") or tags.get("albumartist") or [""])[0]
    title = (tags.get("title") or [""])[0]
    cleaned = (normalize(artist), normalize(title))
    return cleaned if cleaned[1] else None


def audio_md5(path):
    """The raw audio MD5 from STREAMINFO, or None when the file is not FLAC."""
    try:
        return FLAC(path).info.md5_signature or None
    except Exception:
        return None


def rank(entry):
    """Sort key: the higher it sorts, the more the file deserves to be kept."""
    return (entry["provenance"] is not None, entry["bits"],
            entry["rate"], entry["size"])


def split_group(files):
    """Split one group into (keeper, released, left alone).

    Only files whose audio MD5 matches the keeper's exactly are released.
    Without an MD5, as with m4a and mp3, there is no proof the content is the
    same, so nothing is released.
    """
    files = sorted(files, key=rank, reverse=True)
    keeper = files[0]
    copies = [f for f in files[1:]
              if keeper["md5"] is not None and f["md5"] == keeper["md5"]]
    others = [f for f in files[1:] if f not in copies]
    return keeper, copies, others


def collect_groups(library):
    """Group the audio files by (artist, title)."""
    groups = collections.defaultdict(list)
    for name in sorted(os.listdir(library)):
        path = os.path.join(library, name)
        if not (os.path.isfile(path) and name.lower().endswith(AUDIO)):
            continue
        try:
            tags = mutagen.File(path, easy=True)
        except Exception:
            continue
        if not tags:
            continue
        key = tag_key(tags)
        if not key:
            continue
        groups[key].append({
            "name": name, "path": path,
            "provenance": read_provenance(path),
            "bits": getattr(tags.info, "bits_per_sample", 0),
            "rate": getattr(tags.info, "sample_rate", 0),
            "size": os.path.getsize(path),
            "duration": tags.info.length,
            "md5": audio_md5(path),
        })
    return groups


def rewrite_playlist(lines, replacements):
    """Map playlist entries onto the kept file and drop the duplicate entries.

    `replacements` maps the name of a released file to the name of the file
    replacing it. Entry order is preserved; entries that become identical after
    the mapping are kept once.
    """
    out, seen = [], set()
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            out.append(line)
            continue
        parent, name = os.path.split(stripped)
        name = replacements.get(name, name)
        entry = f"{parent}/{name}" if parent else name
        if entry not in seen:
            seen.add(entry)
            out.append(entry)
    return out


def main():
    apply = "--apply" in sys.argv
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dupes = {k: v for k, v in collect_groups(LIBRARY).items() if len(v) > 1}

    replacements, released, bytes_released, skipped = {}, [], 0, []
    for (artist, title), files in sorted(dupes.items()):
        keeper, copies, others = split_group(files)
        if copies:
            print(f"\n[{artist} - {title}]")
            print(f"  KEEP    {keeper['name']}")
            for f in copies:
                print(f"  RELEASE {f['name']}  ({f['size'] / 1048576:.1f} MB)")
                replacements[f["name"]] = keeper["name"]
                released.append(f)
                bytes_released += f["size"]
        if others:
            skipped.append((artist, title, [keeper] + others if not copies else others))

    for artist, title, files in skipped:
        print(f"\n[LEFT ALONE, audio differs] {artist} - {title}")
        for f in files:
            print(f"  {f['name']}  ({f['duration']:.1f} s, {f['bits']}bit/{f['rate']}Hz)")

    print(f"\n{len(dupes)} duplicate groups, {len(skipped)} left alone because the "
          f"audio differs, {len(released)} files released, "
          f"{bytes_released / 1048576:.0f} MB.")

    if not apply:
        print("\nReport only. Run with --apply to move the files.")
        return

    os.makedirs(BACKUP, exist_ok=True)
    moved = 0
    for f in released:
        base, ext = os.path.splitext(f["name"])
        shutil.move(f["path"], os.path.join(BACKUP, f"{base}{DUPE_MARKER}{stamp}{ext}"))
        lyrics = os.path.splitext(f["path"])[0] + ".lrc"
        if os.path.exists(lyrics):
            shutil.move(lyrics, os.path.join(BACKUP, f"{base}{DUPE_MARKER}{stamp}.lrc"))
        moved += 1

    archive = os.path.join(PLAYLISTS, f"source_{stamp}")
    os.makedirs(archive, exist_ok=True)
    for name in sorted(os.listdir(PLAYLISTS)):
        path = os.path.join(PLAYLISTS, name)
        if not (os.path.isfile(path) and name.lower().endswith(".m3u8")):
            continue
        shutil.copy2(path, os.path.join(archive, name))
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        new_lines = rewrite_playlist(lines, replacements)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(new_lines) + "\n")
        print(f"  [PLAYLIST] {name}: {len(lines)} entries -> {len(new_lines)}")

    print(f"\n{moved} files moved to {BACKUP}. Old playlists copied to {archive}.")


if __name__ == "__main__":
    main()
