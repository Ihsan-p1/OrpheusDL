"""Ratakan G:\Music\sorted jadi G:\Music\Library dan tulis playlist m3u8.

Keanggotaan mood diambil dari nama folder yang sekarang, bahasa dari
peta_bahasa_mood.json yang dipanen dari D:\Music\sorted. Folder output/
dilewati: isinya duplikat yang keputusannya belum diambil.
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

MOOD = {"Mood_Berenergi": "Semangat", "Mood_Melankolis": "Sedih", "Mood_Tenang": "Calm"}
BAHASA = {"Lagu_Indonesia": "Indonesia", "Lagu_Inggris_dan_Lainnya": "Inggris",
          "Lagu_Jepang": "Jepang"}


apply = "--apply" in sys.argv
peta = json.load(open("peta_bahasa_mood.json", encoding="utf-8"))

rename = {}
for name in ("healer_session_20260905_122051.json", "healer_session_20260905_134736.json"):
    for track in json.load(open(name, encoding="utf-8"))["tracks"]:
        src = (track.get("fallback_result") or {}).get("file_path")
        if src:
            rename[os.path.basename(os.path.normpath(src))] = os.path.basename(
                os.path.normpath(track["file_path"]))

# Kumpulkan file per nama. Nama yang muncul di dua folder mood adalah satu lagu
# yang masuk dua playlist, bukan dua lagu.
kandidat = collections.defaultdict(list)
for folder in MOOD:
    d = os.path.join(SORTED, folder)
    for n in sorted(os.listdir(d)):
        p = os.path.join(d, n)
        if os.path.isfile(p) and n.lower().endswith(AUDIO):
            kandidat[n].append((folder, p))

playlist = collections.defaultdict(list)
dipindah = diparkir = 0
stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

for n, entries in sorted(kandidat.items()):
    # Kalau satu nama punya beberapa file, yang berprovenance yang disimpan.
    if len(entries) > 1:
        entries.sort(key=lambda e: (read_provenance(e[1]) is None, -os.path.getsize(e[1])))
    simpan_folder, simpan = entries[0]

    for folder, _ in entries:
        playlist[MOOD[folder]].append(n)
    entry = peta.get(n) or peta.get(rename.get(n, ""))
    if entry:
        playlist[BAHASA[entry["bahasa"]]].append(n)

    if apply:
        shutil.move(simpan, os.path.join(LIBRARY, n))
        lirik = os.path.splitext(simpan)[0] + ".lrc"
        if os.path.exists(lirik):
            shutil.move(lirik, os.path.join(LIBRARY, os.path.basename(lirik)))
    dipindah += 1

    for folder, p in entries[1:]:
        if apply:
            base, ext = os.path.splitext(n)
            shutil.move(p, os.path.join(BACKUP, f"{base}_{folder}_{stamp}{ext}"))
        diparkir += 1
        print(f"PARKIR versi kedua dari {folder}: {n}")

if apply:
    for name, files in playlist.items():
        path = os.path.join(PLAYLISTS, f"{name}.m3u8")
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("#EXTM3U\n")
            for n in sorted(files):
                fh.write(f"../Library/{n}\n")

print(f"\n{dipindah} file ke Library, {diparkir} versi kedua diparkir"
      + ("" if apply else " — DRY RUN"))
for name in sorted(playlist):
    print(f"  {len(playlist[name]):5}  {name}.m3u8")
