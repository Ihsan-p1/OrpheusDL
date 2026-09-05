"""Uji kecil untuk orpheus_healer: parsing judul dan penolakan file lossy."""

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
    """Tag dipakai kalau ada, nama file yang bertentangan diabaikan."""
    if not shutil.which("ffmpeg"):
        print("lewat: ffmpeg tidak ada")
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
    """AAC dalam .m4a ditolak walau ekstensinya tidak menyebut codec."""
    if not shutil.which("ffmpeg"):
        print("lewat: ffmpeg tidak ada")
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
    assert _is_lossless("Z:/tidak-ada/x.flac") is False


def test_filename_fallback_strips_corrupted_marker():
    """File tak terbaca: jatuh ke nama file, marker duplikat dibuang."""
    title, artists = _parse_track("Z:/tidak-ada/Adele - Hello [CORRUPTED].flac")
    assert title == "Hello", title
    assert artists == ["Adele"], artists


def test_filename_fallback_plain():
    title, artists = _parse_track("Z:/tidak-ada/Adele - Hello.flac")
    assert title == "Hello", title
    assert artists == ["Adele"], artists


if __name__ == "__main__":
    test_tags_win_over_filename()
    test_aac_is_not_accepted_as_lossless()
    test_unreadable_file_is_not_lossless()
    test_filename_fallback_strips_corrupted_marker()
    test_filename_fallback_plain()
    print("ok")
