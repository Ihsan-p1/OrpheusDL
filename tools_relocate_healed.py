"""Pindahkan file hasil healer dari akar F:\sorted ke folder mood asalnya.

Sekali pakai. Pemetaan dibaca dari session JSON healer:
fallback_result.file_path = file baru di akar, file_path = lokasi asli.
"""
import json
import os
import shutil
import sys

SESSION = sys.argv[1]
DRY = "--apply" not in sys.argv

with open(SESSION, encoding="utf-8") as fh:
    session = json.load(fh)

moved = skipped = 0
for track in session["tracks"]:
    fallback = track.get("fallback_result") or {}
    src = fallback.get("file_path")
    if not src:
        print(f"LEWAT  tidak ada file pengganti: {track['filename']}")
        skipped += 1
        continue
    src = os.path.normpath(src)
    dest_dir = os.path.dirname(os.path.normpath(track["file_path"]))
    dest = os.path.join(dest_dir, os.path.basename(src))

    if not os.path.exists(src):
        print(f"LEWAT  sumber hilang: {src}")
        skipped += 1
        continue
    if os.path.exists(dest):
        print(f"LEWAT  tujuan sudah terisi: {dest}")
        skipped += 1
        continue
    if not os.path.isdir(dest_dir):
        print(f"LEWAT  folder tujuan tidak ada: {dest_dir}")
        skipped += 1
        continue

    print(f"{'DRY ' if DRY else ''}PINDAH {src}\n    -> {dest}")
    if not DRY:
        shutil.move(src, dest)
    moved += 1

print(f"\n{moved} dipindah, {skipped} dilewati" + (" (dry-run)" if DRY else ""))
