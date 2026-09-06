"""Move healer output from the root of F:\sorted back into its mood folder.

One-off. The mapping is read from the healer session JSON:
fallback_result.file_path = the new file at the root, file_path = where it came
from.
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
        print(f"SKIP  no replacement file: {track['filename']}")
        skipped += 1
        continue
    src = os.path.normpath(src)
    dest_dir = os.path.dirname(os.path.normpath(track["file_path"]))
    dest = os.path.join(dest_dir, os.path.basename(src))

    if not os.path.exists(src):
        print(f"SKIP  source is gone: {src}")
        skipped += 1
        continue
    if os.path.exists(dest):
        print(f"SKIP  destination already taken: {dest}")
        skipped += 1
        continue
    if not os.path.isdir(dest_dir):
        print(f"SKIP  destination folder does not exist: {dest_dir}")
        skipped += 1
        continue

    print(f"{'DRY ' if DRY else ''}MOVE {src}\n    -> {dest}")
    if not DRY:
        shutil.move(src, dest)
    moved += 1

print(f"\n{moved} moved, {skipped} skipped" + (" (dry-run)" if DRY else ""))
