"""Test detektor kualitas. Jalankan: python test_quality_probe.py"""
import os
import sys

GT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ground_truth")

from quality_probe import find_lowpass_cliff, median_spectrum, probe


def test_median_spectrum_shape():
    freqs, db, sr = median_spectrum(os.path.join(GT, "orig_1.flac"))
    assert sr == 44100, f"sample rate tak terduga: {sr}"
    assert len(freqs) == len(db), "panjang freqs dan db harus sama"
    assert abs(db.max()) < 1e-6, f"spektrum harus dinormalisasi ke 0 dB, dapat {db.max()}"


def test_cliff_found_on_aac128():
    freqs, db, _ = median_spectrum(os.path.join(GT, "fake_1_aac128.flac"))
    cutoff, drop = find_lowpass_cliff(freqs, db)
    assert cutoff is not None, "AAC 128k harus punya tebing lowpass"
    assert cutoff < 17000.0, f"tebing AAC 128k harus di bawah 17 kHz, dapat {cutoff}"
    assert drop >= 30.0, f"jatuhnya harus >= 30 dB, dapat {drop}"


def test_no_cliff_on_originals():
    for name in ("orig_1.flac", "orig_2.flac", "orig_3.flac"):
        freqs, db, _ = median_spectrum(os.path.join(GT, name))
        cutoff, _ = find_lowpass_cliff(freqs, db)
        assert cutoff is None, f"{name} salah dituduh: tebing di {cutoff}"


def test_spectrum_is_repeatable():
    path = os.path.join(GT, "fake_2_aac128.flac")
    first = find_lowpass_cliff(*median_spectrum(path)[:2])
    second = find_lowpass_cliff(*median_spectrum(path)[:2])
    assert first == second, f"hasil tidak stabil: {first} vs {second}"


def test_probe_flags_low_bitrate_fakes():
    for name in ("fake_1_aac128.flac", "fake_2_aac128.flac", "fake_3_aac128.flac",
                 "fake_1_mp3128.flac", "fake_1_opus128.flac", "fake_1_mp3320.flac"):
        result = probe(os.path.join(GT, name))
        assert result.status == "suspect", f"{name} harusnya suspect, dapat {result.status}"
        assert result.reasons, f"{name} suspect tanpa alasan tercatat"


def test_probe_clears_originals():
    for name in ("orig_1.flac", "orig_2.flac", "orig_3.flac"):
        result = probe(os.path.join(GT, name))
        assert result.status != "suspect", f"{name} salah dituduh: {result.reasons}"


def test_probe_admits_it_cannot_see_high_bitrate():
    for name in ("fake_1_aac256.flac", "fake_2_aac256.flac", "fake_3_aac256.flac",
                 "fake_1_aac320.flac", "fake_2_aac320.flac", "fake_3_aac320.flac"):
        result = probe(os.path.join(GT, name))
        assert result.status == "unknown", (
            f"{name} keluar {result.status}. AAC 256 ke atas tidak menyisakan artefak "
            f"spektral, jadi jawaban yang benar adalah unknown, bukan tuduhan.")


def test_probe_rejects_m4a_instead_of_guessing():
    result = probe(os.path.join(GT, "orig_1.flac").replace(".flac", ".m4a"))
    assert result.status in ("unknown", "corrupt")


def test_probe_is_repeatable():
    path = os.path.join(GT, "fake_3_aac128.flac")
    assert probe(path).status == probe(path).status
    assert probe(path).cutoff_hz == probe(path).cutoff_hz


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
