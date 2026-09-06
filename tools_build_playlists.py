"""Flatten G:\Music\sorted into G:\Music\Library and write the m3u8 playlists.

Mood membership comes from the current folder names, language from
peta_bahasa_mood.json, which was harvested from D:\Music\sorted. The output/
folder is skipped: it holds duplicates nobody has decided about yet.
"""
import collections
import json
import os
import shutil
import sys
from datetime import datetime

from orpheus.provenance import read_provenance

SORTED = r"G:\Music\sorted"
LIBRARY = r"G:\Music\Library"
PLAYLISTS = r"G:\Music\Playlists"
BACKUP = r"G:\Music\_FAKE_BACKUP"
AUDIO = (".flac", ".m4a", ".mp3")

# Keys are folder names on disk, values are playlist names on disk. Both sides
# stay as they are written there.
MOOD = {"Mood_Berenergi": "Semangat", "Mood_Melankolis": "Sedih", "Mood_Tenang": "Calm"}
LANGUAGE = {"Lagu_Indonesia": "Indonesia", "Lagu_Inggris_dan_Lainnya": "Inggris",
            "Lagu_Jepang": "Jepang"}


apply = "--apply" in sys.argv
language_map = json.load(open("peta_bahasa_mood.json", encoding="utf-8"))

rename = {}
for name in ("healer_session_20260905_122051.json", "healer_session_20260905_134736.json"):
    for track in json.load(open(name, encoding="utf-8"))["tracks"]:
        src = (track.get("fallback_result") or {}).get("file_path")
        if src:
            rename[os.path.basename(os.path.normpath(src))] = os.path.basename(
                os.path.normpath(track["file_path"]))

# Collect the files by name. A name appearing in two mood folders is one song
# that belongs to two playlists, not two songs.
candidates = collections.defaultdict(list)
for folder in MOOD:
    d = os.path.join(SORTED, folder)
    for n in sorted(os.listdir(d)):
        p = os.path.join(d, n)
        if os.path.isfile(p) and n.lower().endswith(AUDIO):
            candidates[n].append((folder, p))

playlist = collections.defaultdict(list)
moved = parked = 0
stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

for n, entries in sorted(candidates.items()):
    # When one name has several files, the one with provenance is kept.
    if len(entries) > 1:
        entries.sort(key=lambda e: (read_provenance(e[1]) is None, -os.path.getsize(e[1])))
    keeper_folder, keeper = entries[0]

    for folder, _ in entries:
        playlist[MOOD[folder]].append(n)
    entry = language_map.get(n) or language_map.get(rename.get(n, ""))
    if entry:
        playlist[LANGUAGE[entry["bahasa"]]].append(n)

    if apply:
        shutil.move(keeper, os.path.join(LIBRARY, n))
        lyrics = os.path.splitext(keeper)[0] + ".lrc"
        if os.path.exists(lyrics):
            shutil.move(lyrics, os.path.join(LIBRARY, os.path.basename(lyrics)))
    moved += 1

    for folder, p in entries[1:]:
        if apply:
            base, ext = os.path.splitext(n)
            shutil.move(p, os.path.join(BACKUP, f"{base}_{folder}_{stamp}{ext}"))
        parked += 1
        print(f"PARK second copy from {folder}: {n}")

if apply:
    for name, files in playlist.items():
        path = os.path.join(PLAYLISTS, f"{name}.m3u8")
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("#EXTM3U\n")
            for n in sorted(files):
                fh.write(f"../Library/{n}\n")

print(f"\n{moved} files into Library, {parked} second copies parked"
      + ("" if apply else " — DRY RUN"))
for name in sorted(playlist):
    print(f"  {len(playlist[name]):5}  {name}.m3u8")
