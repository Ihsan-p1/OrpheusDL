#!/usr/bin/env python3
"""Test scan_library.py. Run: python test_scan_library.py"""

import io
import sys
import tempfile
from pathlib import Path

from scan_library import codec_of, read_exclusions, rows_from_csv, scan_one, summarize

GROUND_TRUTH = Path(__file__).parent / "ground_truth"


def test_codec_from_container_not_class_name():
    """FLAC's info class is called StreamInfo, so the class name names no codec.
    This bug made every FLAC read as 'streaminfo' and the ratio come out zero."""
    codec, bitrate = codec_of(GROUND_TRUTH / "orig_1.flac")
    assert codec == "flac", codec
    assert bitrate and bitrate > 0, bitrate


def test_flac_counts_as_lossless():
    row = scan_one(str(GROUND_TRUTH / "orig_1.flac"))
    assert row["lossless"] is True, row
    assert row["ext"] == ".flac", row
    assert row["status"] in ("verified", "unknown"), row


def test_known_fake_is_suspect():
    row = scan_one(str(GROUND_TRUTH / "fake_1_aac128.flac"))
    assert row["status"] == "suspect", row
    assert row["cutoff_hz"] and row["cutoff_hz"] < 20500, row


def test_exclusions_ignore_comments_and_paths():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "no_lossless_source.txt"
        p.write_text(
            "# files with no lossless source\n"
            "\n"
            r"F:\sorted\Mood_Tenang\Sepi.flac  # YouTube rip" "\n"
            "Just A Name.m4a\n",
            encoding="utf-8",
        )
        names = read_exclusions(str(p))
    assert names == {"sepi.flac", "just a name.m4a"}, names


def test_missing_exclusion_file_is_empty_not_an_error():
    assert read_exclusions("file-that-does-not-exist.txt") == set()


def test_excluded_files_leave_the_ratio():
    rows = [
        {"path": r"X\a.flac", "codec": "flac", "lossless": True, "status": "unknown",
         "cutoff_hz": None, "reasons": "", "error": None},
        {"path": r"X\b.m4a", "codec": "aac", "lossless": False, "status": "unknown",
         "cutoff_hz": None, "reasons": "", "error": None},
    ]
    out = io.StringIO()
    stdout, sys.stdout = sys.stdout, out
    try:
        summarize(list(rows), {"b.m4a"})
    finally:
        sys.stdout = stdout
    text = out.getvalue()
    assert "1 files excluded" in text, text
    assert "SUMMARY OF 1 FILES" in text, text
    assert "FLAC         1  100.0%" in text, text


def test_csv_roundtrip_restores_types():
    with tempfile.TemporaryDirectory() as d:
        csv_path = Path(d) / "r.csv"
        csv_path.write_text(
            "path,ext,codec,lossless,status,bitrate_kbps,sample_rate,"
            "declared_bit_depth,effective_bit_depth,cutoff_hz,top_band_std_db,"
            "provenance_module,provenance_codec,reasons,error\n"
            "a.flac,.flac,flac,True,suspect,900,44100,16,16,16300.0,5.1,,,cliff,\n"
            "b.m4a,.m4a,aac,False,unknown,256,44100,,,,,,,,\n",
            encoding="utf-8",
        )
        rows = rows_from_csv(str(csv_path))
    assert rows[0]["lossless"] is True and rows[1]["lossless"] is False, rows
    assert rows[0]["cutoff_hz"] == 16300.0, rows[0]
    assert rows[1]["cutoff_hz"] is None, rows[1]


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except AssertionError as e:
                failed += 1
                print(f"FAIL {name}: {e}")
    sys.exit(1 if failed else 0)
