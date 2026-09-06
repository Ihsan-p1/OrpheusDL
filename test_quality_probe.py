"""Test the quality detector. Run: python test_quality_probe.py"""
import os
import sys

GT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ground_truth")

from quality_probe import find_lowpass_cliff, median_spectrum, probe


def test_median_spectrum_shape():
    freqs, db, sr = median_spectrum(os.path.join(GT, "orig_1.flac"))
    assert sr == 44100, f"unexpected sample rate: {sr}"
    assert len(freqs) == len(db), "freqs and db must be the same length"
    assert abs(db.max()) < 1e-6, f"the spectrum must be normalized to 0 dB, got {db.max()}"


def test_cliff_found_on_aac128():
    freqs, db, _ = median_spectrum(os.path.join(GT, "fake_1_aac128.flac"))
    cutoff, drop = find_lowpass_cliff(freqs, db)
    assert cutoff is not None, "AAC 128k must have a lowpass cliff"
    assert cutoff < 17000.0, f"the AAC 128k cliff must sit below 17 kHz, got {cutoff}"
    assert drop >= 30.0, f"the drop must be >= 30 dB, got {drop}"


def test_no_cliff_on_originals():
    for name in ("orig_1.flac", "orig_2.flac", "orig_3.flac"):
        freqs, db, _ = median_spectrum(os.path.join(GT, name))
        cutoff, _ = find_lowpass_cliff(freqs, db)
        assert cutoff is None, f"{name} wrongly accused: cliff at {cutoff}"


def test_spectrum_is_repeatable():
    path = os.path.join(GT, "fake_2_aac128.flac")
    first = find_lowpass_cliff(*median_spectrum(path)[:2])
    second = find_lowpass_cliff(*median_spectrum(path)[:2])
    assert first == second, f"unstable result: {first} vs {second}"


def test_probe_flags_low_bitrate_fakes():
    for name in ("fake_1_aac128.flac", "fake_2_aac128.flac", "fake_3_aac128.flac",
                 "fake_1_mp3128.flac", "fake_1_opus128.flac", "fake_1_mp3320.flac"):
        result = probe(os.path.join(GT, name))
        assert result.status == "suspect", f"{name} should be suspect, got {result.status}"
        assert result.reasons, f"{name} is suspect with no reason recorded"


def test_probe_clears_originals():
    for name in ("orig_1.flac", "orig_2.flac", "orig_3.flac"):
        result = probe(os.path.join(GT, name))
        assert result.status != "suspect", f"{name} wrongly accused: {result.reasons}"


def test_probe_admits_it_cannot_see_high_bitrate():
    for name in ("fake_1_aac256.flac", "fake_2_aac256.flac", "fake_3_aac256.flac",
                 "fake_1_aac320.flac", "fake_2_aac320.flac", "fake_3_aac320.flac"):
        result = probe(os.path.join(GT, name))
        assert result.status == "unknown", (
            f"{name} came out {result.status}. AAC 256 and above leaves no spectral "
            f"artefact, so the right answer is unknown, not an accusation.")


def test_probe_rejects_m4a_instead_of_guessing():
    result = probe(os.path.join(GT, "orig_1.flac").replace(".flac", ".m4a"))
    assert result.status in ("unknown", "corrupt")


def test_probe_is_repeatable():
    path = os.path.join(GT, "fake_3_aac128.flac")
    assert probe(path).status == probe(path).status
    assert probe(path).cutoff_hz == probe(path).cutoff_hz


def test_lossless_provenance_wins_without_signal_analysis():
    from orpheus.provenance import Provenance
    from quality_probe import ProbeResult, classify
    prov = Provenance("tidal", "HIFI", "flac", "flac", "2026-08-31T04:00:00+00:00", "db681fb")
    assert classify(ProbeResult(status="unknown"), prov, "x.flac") == "verified"


def test_lossy_provenance_in_lossless_container_is_suspect():
    from orpheus.provenance import Provenance
    from quality_probe import ProbeResult, classify
    prov = Provenance("applemusic", "HIFI", "aac", "flac", "2026-08-31T04:00:00+00:00", "db681fb")
    assert classify(ProbeResult(status="unknown"), prov, "x.flac") == "suspect"


def test_lossy_provenance_in_lossy_container_is_not_accused():
    from orpheus.provenance import Provenance
    from quality_probe import ProbeResult, classify
    prov = Provenance("applemusic", "HIGH", "aac", "aac", "2026-08-31T04:00:00+00:00", "db681fb")
    assert classify(ProbeResult(status="unknown"), prov, "x.m4a") == "unknown"


def test_corrupt_beats_everything():
    from orpheus.provenance import Provenance
    from quality_probe import ProbeResult, classify
    prov = Provenance("tidal", "HIFI", "flac", "flac", "2026-08-31T04:00:00+00:00", "db681fb")
    assert classify(ProbeResult(status="corrupt"), prov, "x.flac") == "corrupt"


def test_no_provenance_falls_back_to_probe():
    from quality_probe import ProbeResult, classify
    assert classify(ProbeResult(status="suspect", reasons=["cliff"]), None, "x.flac") == "suspect"
    assert classify(ProbeResult(status="unknown"), None, "x.flac") == "unknown"


def _probe_with_read_error(message):
    import quality_probe
    original = quality_probe.median_spectrum

    def raise_error(path):
        raise RuntimeError(message)

    quality_probe.median_spectrum = raise_error
    try:
        return quality_probe.probe(os.path.join(GT, "orig_1.flac"))
    finally:
        quality_probe.median_spectrum = original


def test_unsupported_format_is_unknown_not_corrupt():
    # 32-bit FLAC: libsndfile does not support it, but the file is whole. The
    # status has to be unknown so provenance decides, not corrupt.
    result = _probe_with_read_error(
        "Error opening 'Slow.flac': File contains data in an unimplemented format.")
    assert result.status == "unknown", result.status


def test_truncated_file_is_still_corrupt():
    result = _probe_with_read_error("Internal psf_fseek() failed.")
    assert result.status == "corrupt", result.status


def test_inspect_on_ground_truth():
    from quality_probe import inspect
    status, result, prov = inspect(os.path.join(GT, "fake_1_aac128.flac"))
    assert status == "suspect"
    assert prov is None
    assert result.cutoff_hz is not None


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
