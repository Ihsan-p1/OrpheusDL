"""Small tests for orpheus_healer: title parsing and rejecting lossy files."""

import os
import shutil
import subprocess
import tempfile

from orpheus_healer import _is_lossless, _parse_track


def _lavfi(path, *extra):
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", "anullsrc=r=44100:cl=mono", "-t", "0.5", *extra, path],
        check=True,
    )


def test_tags_win_over_filename():
    """Tags are used when present, a contradicting filename is ignored."""
    if not shutil.which("ffmpeg"):
        print("skipped: no ffmpeg")
        return
    from mutagen.flac import FLAC

    tmp = tempfile.mkdtemp()
    try:
        path = os.path.join(tmp, "Geek_Music_Peace_Sign_High [CORRUPTED].flac")
        _lavfi(path)
        f = FLAC(path)
        f["title"] = "Peace Sign"
        f["artist"] = "Geek Music"
        f.save()

        title, artists = _parse_track(path)
        assert title == "Peace Sign", title
        assert artists == ["Geek Music"], artists
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_aac_is_not_accepted_as_lossless():
    """AAC inside an .m4a is rejected even though the extension names no codec."""
    if not shutil.which("ffmpeg"):
        print("skipped: no ffmpeg")
        return
    tmp = tempfile.mkdtemp()
    try:
        flac = os.path.join(tmp, "a.flac")
        aac = os.path.join(tmp, "a.m4a")
        _lavfi(flac)
        _lavfi(aac, "-c:a", "aac", "-b:a", "256k")
        assert _is_lossless(flac) is True
        assert _is_lossless(aac) is False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_unreadable_file_is_not_lossless():
    assert _is_lossless("Z:/does-not-exist/x.flac") is False


def test_filename_fallback_strips_corrupted_marker():
    """Unreadable file: falls back to the filename, the dupe marker is dropped."""
    title, artists = _parse_track("Z:/does-not-exist/Adele - Hello [CORRUPTED].flac")
    assert title == "Hello", title
    assert artists == ["Adele"], artists


def test_filename_fallback_plain():
    title, artists = _parse_track("Z:/does-not-exist/Adele - Hello.flac")
    assert title == "Hello", title
    assert artists == ["Adele"], artists


if __name__ == "__main__":
    test_tags_win_over_filename()
    test_aac_is_not_accepted_as_lossless()
    test_unreadable_file_is_not_lossless()
    test_filename_fallback_strips_corrupted_marker()
    test_filename_fallback_plain()
    print("ok")
