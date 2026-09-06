#!/usr/bin/env python3
"""Quality census of a whole music folder.

Walks recursively, measures every file through quality_probe.inspect(), and
writes one CSV row per file plus a summary of the FLAC / ALAC / lossy ratio.

    python scan_library.py --target-dir "D:\\Music\\sorted"
    python scan_library.py --target-dir "D:\\Music\\sorted" --csv report.csv --workers 4

The statuses are the ones quality_probe uses: verified, suspect, unknown,
corrupt. An .m4a is always unknown on the signal side because the probe refuses
to force a FLAC parser onto it, so it is mutagen's codec column that separates
ALAC (lossless) from AAC and EAC3 (lossy).
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import mutagen

from quality_probe import inspect

AUDIO_EXTENSIONS = (".flac", ".m4a", ".mp3", ".wav", ".aiff", ".aif", ".opus", ".ogg")
LOSSLESS_CODECS = ("flac", "alac", "pcm", "wav")

CSV_FIELDS = (
    "path", "ext", "codec", "lossless", "status", "bitrate_kbps",
    "sample_rate", "declared_bit_depth", "effective_bit_depth", "cutoff_hz",
    "top_band_std_db", "provenance_module", "provenance_codec", "reasons", "error",
)


CONTAINER_CODECS = {
    "flac": "flac",
    "mp3": "mp3",
    "easymp3": "mp3",
    "wave": "pcm",
    "aiff": "pcm",
    "oggopus": "opus",
    "oggvorbis": "vorbis",
}


def codec_of(path: Path) -> tuple[str, int | None]:
    """Codec and bitrate according to mutagen. The extension alone is not
    enough: any .m4a can hold lossless ALAC or lossy AAC.

    The codec comes from the container type rather than from the info class
    name. FLAC's info class is called StreamInfo, so the class name does not
    name the codec at all. Only MP4 has an info.codec attribute, and that is
    exactly where ALAC and AAC need separating.
    """
    try:
        f = mutagen.File(str(path))
    except Exception:
        return "unreadable", None
    if f is None or f.info is None:
        return "unreadable", None

    container = type(f).__name__.lower()
    bitrate = getattr(f.info, "bitrate", None)
    bitrate_kbps = bitrate // 1000 if bitrate else None

    if container in CONTAINER_CODECS:
        return CONTAINER_CODECS[container], bitrate_kbps

    codec = str(getattr(f.info, "codec", "") or "").lower()
    if codec.startswith("alac"):
        return "alac", bitrate_kbps
    if codec.startswith("mp4a"):
        return "aac", bitrate_kbps
    if codec.startswith("ec-3") or codec.startswith("ec+3"):
        return "eac3", bitrate_kbps
    if codec.startswith("ac-3"):
        return "ac3", bitrate_kbps
    return codec or container, bitrate_kbps


def scan_one(path_str: str) -> dict:
    path = Path(path_str)
    codec, bitrate = codec_of(path)
    row = {
        "path": path_str,
        "ext": path.suffix.lower(),
        "codec": codec,
        "lossless": any(c in codec for c in LOSSLESS_CODECS),
        "bitrate_kbps": bitrate,
        "status": "unknown",
        "sample_rate": None,
        "declared_bit_depth": None,
        "effective_bit_depth": None,
        "cutoff_hz": None,
        "top_band_std_db": None,
        "provenance_module": None,
        "provenance_codec": None,
        "reasons": "",
        "error": None,
    }
    try:
        status, result, prov = inspect(path_str)
    except Exception as exc:
        row["status"] = "corrupt"
        row["error"] = f"{type(exc).__name__}: {exc}"
        return row
    row["status"] = status
    row["sample_rate"] = result.sample_rate
    row["declared_bit_depth"] = result.declared_bit_depth
    row["effective_bit_depth"] = result.effective_bit_depth
    row["cutoff_hz"] = round(result.cutoff_hz, 1) if result.cutoff_hz else None
    row["top_band_std_db"] = round(result.top_band_std_db, 2) if result.top_band_std_db else None
    row["reasons"] = "; ".join(result.reasons)
    row["error"] = result.error
    if prov:
        row["provenance_module"] = prov.source_module
        row["provenance_codec"] = prov.codec_final or prov.codec_served
    return row


def rows_from_csv(path: str) -> list[dict]:
    """Read a scan back in. CSV returns everything as a string, so the columns
    the summary uses are put back into their own types."""
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        r["lossless"] = r["lossless"] == "True"
        r["cutoff_hz"] = float(r["cutoff_hz"]) if r["cutoff_hz"] else None
    return rows


DEFAULT_EXCLUSION_FILE = "no_lossless_source.txt"


def read_exclusions(path: str) -> set[str]:
    """Read the list of files that have no lossless source anywhere.

    One filename per line, # for a comment. Matching goes by filename rather
    than by full path, so the same list holds for a copy of the library on
    another drive. Membership is a human decision: the absence of a lossless
    source cannot be measured from the file itself.
    """
    if not path or not Path(path).is_file():
        return set()
    names = set()
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            names.add(Path(line).name.lower())
    return names


def summarize(rows: list[dict], exclusions: set[str] | None = None) -> None:
    exclusions = exclusions or set()
    if exclusions:
        excluded = [r for r in rows if Path(r["path"]).name.lower() in exclusions]
        rows = [r for r in rows if Path(r["path"]).name.lower() not in exclusions]
        print(f"{len(excluded)} files excluded from the ratio: no lossless source exists")

    total = len(rows)
    if not total:
        print("No audio files found.")
        return

    by_status = Counter(r["status"] for r in rows)
    by_codec = Counter(r["codec"] for r in rows)
    lossless = [r for r in rows if r["lossless"]]
    flac = [r for r in rows if r["codec"] == "flac"]
    alac = [r for r in rows if r["codec"] == "alac"]

    print(f"\n{'=' * 62}\n SUMMARY OF {total} FILES\n{'=' * 62}")

    print("\nStatus:")
    for status, n in by_status.most_common():
        print(f"  {status:<10} {n:>5}  {n / total * 100:5.1f}%")

    print("\nCodec:")
    for codec, n in by_codec.most_common():
        print(f"  {codec:<10} {n:>5}  {n / total * 100:5.1f}%")

    print("\nRatio against the target:")
    print(f"  FLAC     {len(flac):>5}  {len(flac) / total * 100:5.1f}%  (target at least 95%, fallback 85%)")
    print(f"  ALAC     {len(alac):>5}  {len(alac) / total * 100:5.1f}%  (target at most 10%, fallback 15%)")
    print(f"  lossless {len(lossless):>5}  {len(lossless) / total * 100:5.1f}%")
    print(f"  lossy    {total - len(lossless):>5}  {(total - len(lossless)) / total * 100:5.1f}%")

    suspect = [r for r in rows if r["status"] == "suspect"]
    if suspect:
        print(f"\n{len(suspect)} suspect files (lossless outside, encoder traces inside):")
        for r in sorted(suspect, key=lambda r: r["cutoff_hz"] or 0)[:20]:
            cut = f"cliff {r['cutoff_hz'] / 1000:.1f}kHz" if r["cutoff_hz"] else (r["reasons"] or "?")
            print(f"  {cut:<22} {Path(r['path']).name}")
        if len(suspect) > 20:
            print(f"  ... {len(suspect) - 20} more, see the CSV")

    corrupt = [r for r in rows if r["status"] == "corrupt"]
    if corrupt:
        print(f"\n{len(corrupt)} corrupt or unreadable files:")
        for r in corrupt[:20]:
            print(f"  {r['error'] or '?'} :: {Path(r['path']).name}")
        if len(corrupt) > 20:
            print(f"  ... {len(corrupt) - 20} more, see the CSV")


def main() -> int:
    parser = argparse.ArgumentParser(description="Quality census of a music folder")
    parser.add_argument("--target-dir", help="Folder to scan, recursively")
    parser.add_argument("--csv", default="scan_library_report.csv", help="CSV file to write")
    parser.add_argument("--from-csv", help="Skip the scan, print the summary from this CSV")
    parser.add_argument("--exclusion-list", default=DEFAULT_EXCLUSION_FILE,
                        help="List of files with no lossless source, excluded from the ratio")
    parser.add_argument("--workers", type=int, default=0,
                        help="Number of parallel processes. 0 uses the ProcessPoolExecutor default")
    parser.add_argument("--limit", type=int, default=0, help="Stop after N files, for a quick trial")
    args = parser.parse_args()

    # A filename can hold characters outside the Windows console codepage.
    # Without this the whole scan finishes and then dies printing its first row.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    exclusions = read_exclusions(args.exclusion_list)

    if args.from_csv:
        summarize(rows_from_csv(args.from_csv), exclusions)
        return 0

    if not args.target_dir:
        print("[ERROR] --target-dir is required unless --from-csv is used")
        return 1

    target = Path(args.target_dir)
    if not target.is_dir():
        print(f"[ERROR] Folder not found: {target}")
        return 1

    files = sorted(
        str(p) for p in target.rglob("*")
        if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS
    )
    if args.limit:
        files = files[:args.limit]

    print(f"Scanning {len(files)} audio files in {target}")
    if not files:
        return 0

    rows: list[dict] = []
    workers = args.workers or None
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for i, row in enumerate(pool.map(scan_one, files, chunksize=4), 1):
            rows.append(row)
            if i % 50 == 0 or i == len(files):
                print(f"  {i}/{len(files)}", flush=True)

    with open(args.csv, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    summarize(rows, exclusions)
    print(f"\nCSV: {Path(args.csv).resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
