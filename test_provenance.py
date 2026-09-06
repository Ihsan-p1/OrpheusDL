"""Test the provenance writing. Run: python test_provenance.py"""
import os
import shutil
import sys
import tempfile

from orpheus.provenance import Provenance, read_provenance, write_provenance
from utils.models import ContainerEnum

GT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ground_truth")

SAMPLE = Provenance(
    source_module="tidal",
    quality_tier="HIFI",
    codec_served="flac",
    codec_final="flac",
    downloaded_at="2026-08-31T04:00:00+00:00",
    orpheus_version="db681fb",
    bitrate_kbps=1411,
    sample_rate=44100,
    bit_depth=16,
)


def _temp_copy():
    handle, path = tempfile.mkstemp(suffix=".flac")
    os.close(handle)
    shutil.copyfile(os.path.join(GT, "orig_1.flac"), path)
    return path


def test_roundtrip_flac():
    path = _temp_copy()
    try:
        write_provenance(path, ContainerEnum.flac, SAMPLE)
        loaded = read_provenance(path)
        assert loaded == SAMPLE, f"the provenance changed when read back: {loaded}"
    finally:
        os.remove(path)


def test_missing_provenance_returns_none():
    path = _temp_copy()
    try:
        assert read_provenance(path) is None
    finally:
        os.remove(path)


def test_existing_tags_survive():
    from mutagen.flac import FLAC
    path = _temp_copy()
    try:
        tagger = FLAC(path)
        tagger["title"] = "Original Title"
        tagger.save()
        write_provenance(path, ContainerEnum.flac, SAMPLE)
        assert FLAC(path)["title"] == ["Original Title"], "another tag was wiped out"
    finally:
        os.remove(path)


def test_numeric_fields_come_back_as_numbers():
    path = _temp_copy()
    try:
        write_provenance(path, ContainerEnum.flac, SAMPLE)
        loaded = read_provenance(path)
        assert loaded.sample_rate == 44100 and isinstance(loaded.sample_rate, int)
        assert loaded.bit_depth == 16 and isinstance(loaded.bit_depth, int)
    finally:
        os.remove(path)


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
