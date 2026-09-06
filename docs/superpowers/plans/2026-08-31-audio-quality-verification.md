# Audio Quality Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the guessing verdict system in `orpheus_healer.py` with provenance written into the file's tags plus a signal detector that reports only measured evidence.

**Architecture:** A new module `quality_probe.py` at the repo root holds the signal measurements (the median of five FFT windows, lowpass cliff detection, upsampling, padded bit depth) and the `classify()` function. A new module `orpheus/provenance.py` writes and reads a file's origin through mutagen. `orpheus_healer.py` and `check_duplicates.py` switch to both, and every old verdict string is then thrown out.

**Tech Stack:** Python 3.12, numpy, soundfile, mutagen, ffmpeg-python. No test framework. Every test runs as `python test_<name>.py`.

**Spec:** `docs/superpowers/specs/2026-08-31-audio-quality-verification-prd.md`

## Global Constraints

- No test framework. Each test file is a plain script of `assert` statements, run with `python test_<name>.py`, exiting 0 when everything passes.
- The ground-truth set lives in `ground_truth/` at the repo root: `orig_1.flac`, `orig_2.flac`, `orig_3.flac`, and 12 `fake_*` files (aac128/256/320 for three sources, plus mp3128, mp3320, opus128 for the first source). The folder is 370 MB and must never reach git.
- Only four status strings are valid: `"verified"`, `"suspect"`, `"unknown"`, `"corrupt"`. No other verdict string exists anywhere in the code once Task 8 is done.
- The thresholds in use, all named constants in `quality_probe.py`: `CLIFF_MIN_DROP_DB = 30.0`, `CLIFF_SPAN_HZ = 1000.0`, `CLIFF_RECOVERY_DB = 5.0`, `CLIFF_SUSPECT_MAX_HZ = 19000.0`, `SMOOTH_HZ = 200.0`, `UPSAMPLE_MIN_HZ = 24000.0`, `N_WINDOWS = 5`, `N_SAMPLES = 131072`.
- A note from carrying out Task 1: the first design used `CLIFF_FLOOR_DB = -60.0` as its second condition and did not smooth the spectrum. Tested against the ground truth, `orig_1.flac` was wrongly accused (a random dip at 7.4 kHz read as a cliff) because one FFT bin here is 0.34 Hz wide and its value jumps tens of dB from bin to bin. The spectrum is now smoothed at 200 Hz first, and the second condition is that energy never climbs back after the cliff rather than an absolute floor. `orig_2.flac`, quiet up high (-88 dB at 16 kHz), passes correctly because its fall is gentle.
- Lossless codecs: `{"flac", "alac", "wav", "aiff"}`. Converting ALAC to FLAC is still lossless and is no reason to flag a file.
- Log messages, comments, function names, variables and docstrings are all written in English.
- Every commit is attributed to Ihsan-p1. Do not add a co-author trailer of any kind.

---

### Task 1: Median spectrum and lowpass cliff detection

**Files:**
- Create: `quality_probe.py`
- Create: `test_quality_probe.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: nothing.
- Produces: `median_spectrum(path: str, n_windows: int = 5, n_samples: int = 131072) -> tuple[np.ndarray, np.ndarray, int]` returning `(freqs, db, sample_rate)` with `db` normalized to a 0 dB peak. `find_lowpass_cliff(freqs: np.ndarray, db: np.ndarray, min_drop_db: float = 30.0, span_hz: float = 1000.0) -> tuple[float | None, float | None]` returning `(cutoff_hz, drop_db)`.

- [ ] **Step 1: Keep the ground-truth folder out of git**

Add one line to the end of `.gitignore`:

```
/ground_truth/
```

Then check that all 15 files are there:

```bash
ls ground_truth | wc -l
```

Expected: `15`

- [ ] **Step 2: Write the failing test**

Create `test_quality_probe.py`:

```python
"""Test the quality detector. Run: python test_quality_probe.py"""
import os
import sys

GT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ground_truth")

from quality_probe import find_lowpass_cliff, median_spectrum


def test_median_spectrum_shape():
    freqs, db, sr = median_spectrum(os.path.join(GT, "orig_1.flac"))
    assert sr == 44100, f"unexpected sample rate: {sr}"
    assert len(freqs) == len(db), "freqs and db must be the same length"
    assert abs(db.max()) < 1e-6, f"the spectrum must be normalized to 0 dB, got {db.max()}"


def test_cliff_found_on_aac128():
    freqs, db, _ = median_spectrum(os.path.join(GT, "fake_1_aac128.flac"))
    cutoff, drop = find_lowpass_cliff(freqs, db)
    assert cutoff is not None, "AAC 128k must have a lowpass cliff"
    assert cutoff < 19000.0, f"the AAC 128k cliff must sit below 19 kHz, got {cutoff}"
    assert drop >= 30.0, f"the drop must be >= 30 dB, got {drop}"


def test_no_cliff_on_originals():
    for name in ("orig_1.flac", "orig_2.flac", "orig_3.flac"):
        freqs, db, _ = median_spectrum(os.path.join(GT, name))
        cutoff, _ = find_lowpass_cliff(freqs, db)
        assert cutoff is None or cutoff >= 19000.0, f"{name} wrongly accused: cliff at {cutoff}"


def test_spectrum_is_repeatable():
    path = os.path.join(GT, "fake_2_aac128.flac")
    first = find_lowpass_cliff(*median_spectrum(path)[:2])
    second = find_lowpass_cliff(*median_spectrum(path)[:2])
    assert first == second, f"unstable result: {first} vs {second}"


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
```

- [ ] **Step 3: Run the test and confirm it fails**

Run: `python test_quality_probe.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'quality_probe'`

- [ ] **Step 4: Write the minimal implementation**

Create `quality_probe.py`:

```python
"""Repeatable audio quality measurements.

This module hands down no verdict. It reports numbers that measure the same on
every run, and stays quiet about anything it cannot prove.
"""
from __future__ import annotations

import numpy as np
import soundfile as sf

CLIFF_MIN_DROP_DB = 30.0
CLIFF_SPAN_HZ = 1000.0
CLIFF_FLOOR_DB = -60.0
CLIFF_SUSPECT_MAX_HZ = 19000.0
UPSAMPLE_MIN_HZ = 24000.0
N_WINDOWS = 5
N_SAMPLES = 131072


def median_spectrum(path: str, n_windows: int = N_WINDOWS,
                    n_samples: int = N_SAMPLES) -> tuple[np.ndarray, np.ndarray, int]:
    """Take several FFT windows across the track and return the median spectrum.

    A single window in the middle of a track makes the result swing with
    whatever happens to be playing there. The median of several positions comes
    out the same on every run.
    """
    spectra = []
    with sf.SoundFile(path) as af:
        sr = af.samplerate
        total = len(af)
        if total < n_samples:
            raise ValueError(f"file too short: {total} frames")
        window = np.hanning(n_samples)
        for fraction in np.linspace(0.2, 0.8, n_windows):
            start = max(0, int(total * fraction) - n_samples // 2)
            if start + n_samples > total:
                start = total - n_samples
            af.seek(start)
            block = af.read(n_samples, dtype="float32")
            if block.ndim > 1:
                block = block.mean(axis=1)
            if len(block) < n_samples:
                continue
            magnitude = np.abs(np.fft.rfft(block * window))
            db = 20.0 * np.log10(np.maximum(magnitude, 1e-12))
            spectra.append(db - db.max())
    if not spectra:
        raise ValueError("no readable window")
    freqs = np.fft.rfftfreq(n_samples, d=1.0 / sr)
    return freqs, np.median(np.vstack(spectra), axis=0), sr


def find_lowpass_cliff(freqs: np.ndarray, db: np.ndarray,
                       min_drop_db: float = CLIFF_MIN_DROP_DB,
                       span_hz: float = CLIFF_SPAN_HZ) -> tuple[float | None, float | None]:
    """Find the encoder cliff: energy drops hard and never comes back.

    The second condition matters. Without it, an ordinary dip in the middle of
    the spectrum counts as a cliff too.
    """
    bin_hz = float(freqs[1] - freqs[0])
    span = max(1, int(span_hz / bin_hz))
    for i in range(len(freqs) - span):
        drop = float(db[i] - db[i + span])
        if drop < min_drop_db:
            continue
        if float(np.median(db[i + span:])) <= CLIFF_FLOOR_DB:
            return float(freqs[i]), drop
    return None, None
```

- [ ] **Step 5: Run the test and confirm it passes**

Run: `python test_quality_probe.py`
Expected: four `PASS` lines, exit code 0

- [ ] **Step 6: Commit**

```bash
git add .gitignore quality_probe.py test_quality_probe.py
git commit -m "feat: add the median spectrum measurement and lowpass cliff detection"
```

---

### Task 2: Upsampling detection, padded bit depth, and the probe function

**Files:**
- Modify: `quality_probe.py`
- Modify: `test_quality_probe.py`

**Interfaces:**
- Consumes: `median_spectrum()`, `find_lowpass_cliff()` from Task 1.
- Produces: the dataclass `ProbeResult` with the fields `status: str`, `reasons: list[str]`, `sample_rate: int | None`, `declared_bit_depth: int | None`, `effective_bit_depth: int | None`, `cutoff_hz: float | None`, `cutoff_drop_db: float | None`, `highest_energy_hz: float | None`, `error: str | None`. The function `bit_depths(path: str) -> tuple[int | None, int | None]` returning `(declared, effective)`. The function `probe(path: str) -> ProbeResult` whose `status` is one of `"suspect"`, `"unknown"`, `"corrupt"`.

- [ ] **Step 1: Write the failing test**

Add this to `test_quality_probe.py`, above the `if __name__` block:

```python
def test_probe_flags_low_bitrate_fakes():
    for name in ("fake_1_aac128.flac", "fake_2_aac128.flac", "fake_3_aac128.flac",
                 "fake_1_mp3128.flac", "fake_1_opus128.flac"):
        result = probe(os.path.join(GT, name))
        assert result.status == "suspect", f"{name} should be suspect, got {result.status}"
        assert result.reasons, f"{name} is suspect with no reason recorded"


def test_probe_clears_originals():
    for name in ("orig_1.flac", "orig_2.flac", "orig_3.flac"):
        result = probe(os.path.join(GT, name))
        assert result.status != "suspect", f"{name} wrongly accused: {result.reasons}"


def test_probe_admits_it_cannot_see_high_bitrate():
    for name in ("fake_1_aac256.flac", "fake_2_aac256.flac", "fake_3_aac256.flac",
                 "fake_1_aac320.flac", "fake_1_mp3320.flac"):
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
```

Change the import line at the top of the file to:

```python
from quality_probe import find_lowpass_cliff, median_spectrum, probe
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `python test_quality_probe.py`
Expected: FAIL with `ImportError: cannot import name 'probe'`

- [ ] **Step 3: Write the implementation**

Add this to `quality_probe.py`. The imports at the top of the file become:

```python
import os
from dataclasses import dataclass, field

import numpy as np
import soundfile as sf
```

Then below the constants:

```python
SIGNAL_EXTENSIONS = (".flac", ".wav", ".aiff", ".aif")


@dataclass
class ProbeResult:
    status: str = "unknown"
    reasons: list[str] = field(default_factory=list)
    sample_rate: int | None = None
    declared_bit_depth: int | None = None
    effective_bit_depth: int | None = None
    cutoff_hz: float | None = None
    cutoff_drop_db: float | None = None
    highest_energy_hz: float | None = None
    error: str | None = None
```

And below `find_lowpass_cliff`:

```python
def bit_depths(path: str, n_frames: int = 500_000) -> tuple[int | None, int | None]:
    """Compare the declared bit depth with the one actually in use.

    soundfile puts the samples in the top bits of an int32, so the number of
    zero bits underneath says how many bits are really filled. A 24-bit file
    holding padded 16-bit content has eight more zero bits than it should.
    """
    with sf.SoundFile(path) as af:
        subtype = af.subtype or ""
        declared = None
        for bits in (32, 24, 16, 8):
            if str(bits) in subtype:
                declared = bits
                break
        data = af.read(n_frames, dtype="int32")
    if declared is None:
        return None, None
    values = np.asarray(data).astype(np.int64).ravel()
    nonzero = values[values != 0]
    if nonzero.size == 0:
        return declared, 0
    lowest_set_bit = int(np.min(nonzero & -nonzero))
    trailing_zeros = lowest_set_bit.bit_length() - 1
    return declared, min(declared, 32 - trailing_zeros)


def probe(path: str) -> ProbeResult:
    """Measure one file and report the hard evidence it finds."""
    if not os.path.exists(path):
        return ProbeResult(status="corrupt", error="file not found")

    extension = os.path.splitext(path)[1].lower()
    if extension not in SIGNAL_EXTENSIONS:
        return ProbeResult(status="unknown",
                           error=f"signal probe does not apply to {extension}")

    result = ProbeResult()
    try:
        freqs, db, sr = median_spectrum(path)
    except ValueError as e:
        result.status = "unknown"
        result.error = str(e)
        return result
    except Exception as e:
        return ProbeResult(status="corrupt", error=str(e))

    result.sample_rate = sr
    result.cutoff_hz, result.cutoff_drop_db = find_lowpass_cliff(freqs, db)

    audible = np.where(db >= -80.0)[0]
    result.highest_energy_hz = float(freqs[audible[-1]]) if len(audible) else 0.0

    try:
        result.declared_bit_depth, result.effective_bit_depth = bit_depths(path)
    except Exception as e:
        result.error = f"bit depth unreadable: {e}"

    if result.cutoff_hz is not None and result.cutoff_hz < CLIFF_SUSPECT_MAX_HZ:
        result.reasons.append(
            f"lowpass cliff {result.cutoff_hz / 1000:.1f} kHz "
            f"dropping {result.cutoff_drop_db:.0f} dB")

    if sr >= 88200 and result.highest_energy_hz < UPSAMPLE_MIN_HZ:
        result.reasons.append(
            f"declared {sr / 1000:.1f} kHz but energy stops at "
            f"{result.highest_energy_hz / 1000:.1f} kHz")

    if (result.declared_bit_depth and result.effective_bit_depth
            and result.effective_bit_depth <= result.declared_bit_depth - 8):
        result.reasons.append(
            f"{result.declared_bit_depth}-bit but only "
            f"{result.effective_bit_depth} bits filled")

    result.status = "suspect" if result.reasons else "unknown"
    return result
```

- [ ] **Step 4: Run the test and confirm it passes**

Run: `python test_quality_probe.py`
Expected: nine `PASS` lines, exit code 0

If `test_probe_clears_originals` fails, do not loosen a threshold to chase the result. Record the measured cutoff, inspect that file in Audition, then decide whether the ground-truth file really is clean.

- [ ] **Step 5: Commit**

```bash
git add quality_probe.py test_quality_probe.py
git commit -m "feat: add upsampling detection, padded bit depth, and the probe function"
```

---

### Task 3: Provenance written to and read from the file's tags

**Files:**
- Create: `orpheus/provenance.py`
- Create: `test_provenance.py`

**Interfaces:**
- Consumes: `ContainerEnum` from `utils/models.py`.
- Produces: the dataclass `Provenance(source_module: str, quality_tier: str, codec_served: str, codec_final: str, downloaded_at: str, orpheus_version: str, bitrate_kbps: int | None = None, sample_rate: int | None = None, bit_depth: int | None = None)`. The functions `write_provenance(file_path: str, container: ContainerEnum, prov: Provenance) -> None` and `read_provenance(file_path: str) -> Provenance | None`. The constants `LOSSLESS_CODECS: set[str]` and `ORPHEUS_VERSION: str`.

- [ ] **Step 1: Write the failing test**

Create `test_provenance.py`:

```python
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
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `python test_provenance.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'orpheus.provenance'`

- [ ] **Step 3: Write the implementation**

Create `orpheus/provenance.py`:

```python
"""The download record of a file: module, tier, codec, download time.

Kept inside the file's own tags rather than in a separate database. Files in
the library get moved and renamed often, and an index keyed by path breaks the
moment that happens.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, fields

import mutagen
from mutagen.flac import FLAC
from mutagen.id3 import TXXX
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis

from utils.models import ContainerEnum

PREFIX = "orpheus_"
MP4_PREFIX = "----:com.orpheusdl:"
INT_FIELDS = {"bitrate_kbps", "sample_rate", "bit_depth"}
LOSSLESS_CODECS = {"flac", "alac", "wav", "aiff"}


def _detect_version() -> str:
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        done = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              cwd=repo_root, capture_output=True, text=True, timeout=5)
        return done.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


ORPHEUS_VERSION = _detect_version()


@dataclass
class Provenance:
    source_module: str
    quality_tier: str
    codec_served: str
    codec_final: str
    downloaded_at: str
    orpheus_version: str
    bitrate_kbps: int | None = None
    sample_rate: int | None = None
    bit_depth: int | None = None


def _pairs(prov: Provenance) -> list[tuple[str, str]]:
    out = []
    for f in fields(Provenance):
        value = getattr(prov, f.name)
        if value is not None and value != "":
            out.append((PREFIX + f.name, str(value)))
    return out


def write_provenance(file_path: str, container: ContainerEnum, prov: Provenance) -> None:
    """Write the provenance into the file's tags. Other tags are left alone."""
    if container is ContainerEnum.flac:
        tagger = FLAC(file_path)
        for key, value in _pairs(prov):
            tagger[key] = value
    elif container is ContainerEnum.ogg:
        tagger = OggVorbis(file_path)
        for key, value in _pairs(prov):
            tagger[key] = value
    elif container is ContainerEnum.opus:
        tagger = OggOpus(file_path)
        for key, value in _pairs(prov):
            tagger[key] = value
    elif container is ContainerEnum.m4a:
        tagger = MP4(file_path)
        for key, value in _pairs(prov):
            tagger[MP4_PREFIX + key] = [value.encode("utf-8")]
    elif container is ContainerEnum.mp3:
        tagger = MP3(file_path)
        if tagger.tags is None:
            tagger.add_tags()
        for key, value in _pairs(prov):
            tagger.tags.add(TXXX(encoding=3, desc=key, text=value))
    else:
        raise ValueError(f"container not supported for provenance: {container}")
    tagger.save()


def _flatten(value) -> str:
    if isinstance(value, TXXX):
        value = value.text
    if isinstance(value, list):
        value = value[0] if value else ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    return str(value)


def read_provenance(file_path: str) -> Provenance | None:
    """Read the provenance from a file. Returns None when there is none."""
    try:
        audio = mutagen.File(file_path)
    except Exception:
        return None
    if audio is None or audio.tags is None:
        return None

    found: dict[str, str] = {}
    for key, value in dict(audio.tags).items():
        name = str(key).lower()
        for marker in (MP4_PREFIX.lower(), "txxx:"):
            if name.startswith(marker):
                name = name[len(marker):]
        if name.startswith(PREFIX):
            found[name[len(PREFIX):]] = _flatten(value)

    if not found:
        return None

    kwargs = {}
    for f in fields(Provenance):
        raw = found.get(f.name)
        if raw is None or raw == "":
            kwargs[f.name] = None if f.name in INT_FIELDS else ""
        elif f.name in INT_FIELDS:
            try:
                kwargs[f.name] = int(float(raw))
            except ValueError:
                kwargs[f.name] = None
        else:
            kwargs[f.name] = raw
    return Provenance(**kwargs)
```

- [ ] **Step 4: Run the test and confirm it passes**

Run: `python test_provenance.py`
Expected: four `PASS` lines, exit code 0

- [ ] **Step 5: Commit**

```bash
git add orpheus/provenance.py test_provenance.py
git commit -m "feat: record where a file came from in its tags through a provenance module"
```

---

### Task 4: A classify function folding provenance and probe together

**Files:**
- Modify: `quality_probe.py`
- Modify: `test_quality_probe.py`

**Interfaces:**
- Consumes: `ProbeResult` and `probe()` from Task 2, `Provenance` and `LOSSLESS_CODECS` from Task 3.
- Produces: `classify(result: ProbeResult, prov: Provenance | None, file_path: str) -> str` returning `"verified"`, `"suspect"`, `"unknown"` or `"corrupt"`. The function `inspect(file_path: str) -> tuple[str, ProbeResult, Provenance | None]`, which runs `read_provenance`, then `probe`, then `classify` in one go.

- [ ] **Step 1: Write the failing test**

Add this to `test_quality_probe.py`:

```python
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


def test_inspect_on_ground_truth():
    from quality_probe import inspect
    status, result, prov = inspect(os.path.join(GT, "fake_1_aac128.flac"))
    assert status == "suspect"
    assert prov is None
    assert result.cutoff_hz is not None
```

- [ ] **Step 2: Run the test and confirm it fails**

Run: `python test_quality_probe.py`
Expected: FAIL with `ImportError: cannot import name 'classify'`

- [ ] **Step 3: Write the implementation**

Add this at the end of `quality_probe.py`:

```python
from orpheus.provenance import LOSSLESS_CODECS, Provenance, read_provenance

LOSSLESS_EXTENSIONS = (".flac", ".wav", ".aiff", ".aif", ".alac")


def classify(result: ProbeResult, prov: Provenance | None, file_path: str) -> str:
    """Fold provenance evidence and signal evidence into one status.

    Provenance beats signal analysis. Once we know which module a file came
    from and with which codec, there is nothing to gain from guessing by FFT.
    """
    if result.status == "corrupt":
        return "corrupt"

    if prov is not None and prov.codec_served:
        served = prov.codec_served.lower()
        if served in LOSSLESS_CODECS:
            return "verified"
        if os.path.splitext(file_path)[1].lower() in LOSSLESS_EXTENSIONS:
            return "suspect"
        return "unknown"

    return result.status


def inspect(file_path: str) -> tuple[str, ProbeResult, Provenance | None]:
    """Read the provenance, measure the signal, return the final status."""
    prov = read_provenance(file_path)
    result = probe(file_path)
    return classify(result, prov, file_path), result, prov
```

- [ ] **Step 4: Run the test and confirm it passes**

Run: `python test_quality_probe.py`
Expected: fifteen `PASS` lines, exit code 0

- [ ] **Step 5: Commit**

```bash
git add quality_probe.py test_quality_probe.py
git commit -m "feat: fold provenance and probe together through classify"
```

---

### Task 5: Write the provenance as a file is downloaded

**Files:**
- Modify: `orpheus/music_downloader.py:313`, `orpheus/music_downloader.py:543-620`, `orpheus/music_downloader.py:621-630`
- Test: verified by hand through one real download, described in Step 5

**Interfaces:**
- Consumes: `Provenance`, `write_provenance`, `ORPHEUS_VERSION` from Task 3.
- Produces: every file `download_track()` produces carries provenance tags. No new API for the other tasks.

- [ ] **Step 1: Add the import**

In `orpheus/music_downloader.py`, below the line `from orpheus.tagging import tag_file` (line 9):

```python
from orpheus.provenance import ORPHEUS_VERSION, Provenance, write_provenance
```

And make sure `datetime` is available at the top of the file:

```python
from datetime import datetime, timezone
```

- [ ] **Step 2: Track the final codec through the conversion**

At line 313, right after `codec = track_info.codec`, add:

```python
        final_codec = codec
```

Then in the conversion block, right after the line `track_location = new_track_location` (around line 616), add at the same indentation:

```python
                final_codec = new_codec
```

`codec` holds what the module actually served, including when `download_info.different_codec` overwrites it at line 398. `final_codec` holds the end result after `codec_conversions`. Both need recording because ALAC converted to FLAC is still lossless, while AAC wrapped into FLAC is not.

- [ ] **Step 3: Write the provenance after tagging**

In the `try` block that calls `tag_file` (lines 623 to 630), add this after both `tag_file` calls, still inside the `try`:

```python
            provenance = Provenance(
                source_module=self.service_name,
                quality_tier=quality_tier.name,
                codec_served=codec.name.lower(),
                codec_final=final_codec.name.lower(),
                downloaded_at=datetime.now(timezone.utc).isoformat(timespec='seconds'),
                orpheus_version=ORPHEUS_VERSION,
                bitrate_kbps=track_info.bitrate,
                sample_rate=int(track_info.sample_rate * 1000) if track_info.sample_rate else None,
                bit_depth=track_info.bit_depth,
            )
            try:
                write_provenance(track_location, container, provenance)
                if old_track_location:
                    write_provenance(old_track_location, old_container, provenance)
            except Exception as e:
                self.print(f'Warning: provenance not written: {e}')
```

`track_info.sample_rate` is stored in kHz as a float (see `utils/models.py`), so it is multiplied by 1000 to match the unit `quality_probe.probe()` reports.

A failed provenance write must not undo a download that already succeeded, hence the separate `try` block.

- [ ] **Step 4: Check the syntax**

Run: `python -c "import orpheus.music_downloader"`
Expected: no output, exit code 0

- [ ] **Step 5: Verify through one real download**

Download one short track from a module that is logged in:

```bash
python orpheus.py <track-url>
```

Then read the provenance of the resulting file:

```bash
python -c "from orpheus.provenance import read_provenance; print(read_provenance(r'<path-to-the-resulting-file>'))"
```

Expected: a `Provenance` whose `source_module` matches the module used, whose `codec_served` holds the codec the server sent, and whose `downloaded_at` holds today's time.

With no module ready to log in, skip this step and note in the commit message that the real-download check has not been done.

- [ ] **Step 6: Commit**

```bash
git add orpheus/music_downloader.py
git commit -m "feat: write provenance into every downloaded file"
```

---

### Task 6: The healer uses a status rather than a verdict

**Files:**
- Modify: `orpheus_healer.py:99`, `orpheus_healer.py:114-137`, `orpheus_healer.py:253-311`, `orpheus_healer.py:320-362`, `orpheus_healer.py:405-420`, `orpheus_healer.py:815-1000`, `orpheus_healer.py:1171-1260`, `orpheus_healer.py:1425-1460`, `orpheus_healer.py:1570-1585`
- Modify: `healer_config.toml`

**Interfaces:**
- Consumes: `inspect()`, `ProbeResult` from Task 4.
- Produces: `orpheus_healer.py` no longer exports `analyze_flac_quality`, `is_truly_lossless`, `_VERDICT_SCORE` or `_get_verdict_score`. It still exports `_normalize_for_dedup` and `_DUP_MARKER_RE` for `check_duplicates.py`.

- [ ] **Step 1: Delete the old verdict machinery**

Delete from `orpheus_healer.py`:

- `_THRESHOLDS` and `_compute_rolloff_slope()` (lines 815 to 840)
- `analyze_flac_quality()` in full (lines 841 to 954)
- `is_truly_lossless()` in full (lines 956 to 968)
- `_VERDICT_SCORE` (lines 320 to 330)
- `_get_verdict_score()` (lines 357 to 362)
- The `"quality_score"` block in `_DEFAULT_CONFIG` (around line 114) and the line merging it at line 137
- The `"bad_verdicts"` entry in `_DEFAULT_CONFIG` (line 99)

Add the import at the top of the file:

```python
from quality_probe import inspect
```

- [ ] **Step 2: Replace how flagged tracks are picked out of the CSV**

`parse_soniq_csv()` currently takes `bad_verdicts` and filters CSV rows by matching a verdict string. Soniq has evidence we do not, so its output is still used as-is for the candidate list, but the parameter is renamed to make clear it is Soniq's data rather than our verdict.

Change the signature at line 253:

```python
def parse_soniq_csv(csv_path: str, soniq_flags: list[str]) -> list[dict]:
```

Replace the uses of `bad_verdicts` inside the function (lines 277 and 311) with `soniq_flags`. At lines 1433 to 1435, replace:

```python
    soniq_flags = list(CONFIG["settings"]["soniq_flags"])
```

and delete the line `bad_verdicts.append("Possibly Upsampled")` along with its condition. At line 1458, the call becomes `parse_soniq_csv(args.csv, soniq_flags)`.

- [ ] **Step 3: Replace the verdict-based duplicate ranking**

Replace `_sort_key` inside `_pick_best_in_group()` (lines 411 to 419) with:

```python
    def _sort_key(entry):
        bd = _parse_bd(entry.get("bit_depth"))
        bw = _parse_bw(entry.get("bandwidth"))
        sr = _parse_sr(entry.get("sample_rate"))
        # A small bonus for 44.1 kHz so upsampled hi-res does not win automatically
        sr_bonus = 0.5 if abs(sr - 44.1) < 0.5 else 0.0
        return (bd, bw, sr_bonus)
```

This sorts Soniq CSV entries, not files on disk. The bit depth and bandwidth columns hold measurements while the verdict column holds Soniq's conclusion, which cannot be audited, so only the measurements are used. Update the function's docstring to `Priority: bit depth -> bandwidth -> sample rate` as well.

Replace `_colorize_verdict()` (lines 424 to 434) with a version that colours a status, and update every caller:

```python
def _colorize_status(status: str) -> str:
    if status in ("suspect", "corrupt"):
        return f"{C.RED}{status}{C.RESET}"
    if status == "verified":
        return f"{C.GREEN}{status}{C.RESET}"
    return f"{C.YELLOW}{status}{C.RESET}"
```

- [ ] **Step 4: Replace the decision made after a redownload**

At lines 1227 to 1256, replace the analysis block with:

```python
        status, measurement, prov = inspect(new_file)
        attempt["status"] = status
        attempt["reasons"] = measurement.reasons

        sr_str = f"{measurement.sample_rate / 1000:.1f}kHz" if measurement.sample_rate else "?"
        co_str = (f"{measurement.cutoff_hz / 1000:.1f}kHz"
                  if measurement.cutoff_hz is not None else "no cliff")
        src_str = f"{prov.source_module}/{prov.codec_served}" if prov else "no provenance"

        if status in ("verified", "unknown"):
            log.info(f"  {C.GREEN}[ACCEPT] {label} → {status} ({src_str}){C.RESET}")
            log.info(f"           {sr_str} | {co_str}")
            if preserved_tags:
                apply_custom_tags(new_file, preserved_tags)
            attempts.append(attempt)
            return {"status": status, "source": module, "label": label,
                    "file_path": new_file, "measurement": measurement, "attempts": attempts}

        log.warning(f"  {C.YELLOW}[REJECT] {label} → {status}: "
                    f"{'; '.join(measurement.reasons) or measurement.error}{C.RESET}")
        candidates.append({"source": module, "label": label, "file": new_file,
                           "measurement": measurement, "status": status})
        attempts.append(attempt)
```

A status of `unknown` is accepted. This system does not reject a file merely because nothing can be proven about it.

Drop the `quality_score` parameter from the signature at line 1171 and from its caller at line 1579. To pick the best candidate when everything is rejected, sort `candidates` by: a file with no `suspect` reason wins, then higher effective bit depth, then larger file size.

- [ ] **Step 5: Update the config**

In `healer_config.toml`, delete the `[quality_score]` block entirely. Replace `bad_verdicts` in `[settings]` with:

```toml
# The Soniq verdicts used to pick candidates out of the CSV.
# This is Soniq's data, not a judgement of our own.
soniq_flags = [
    "Upsampled / Transcoded",
    "Lossy Transcode",
    "Low-Bitrate Lossy",
    "Possibly Upsampled",
    "Error",
]

# The measured statuses that trigger a redownload.
# Valid values: "suspect", "corrupt", "unknown".
# "unknown" is a bad idea: most of the old library lands in that category.
redownload_status = ["suspect", "corrupt"]
```

Add `"redownload_status": ["suspect", "corrupt"]` and `"soniq_flags": [...]` to `_DEFAULT_CONFIG["settings"]` in `orpheus_healer.py` so an older config still runs.

- [ ] **Step 6: Check the syntax and dry-run it**

Run: `python -c "import orpheus_healer"`
Expected: no output, exit code 0

Run: `python -c "import orpheus_healer as h; print(hasattr(h, 'analyze_flac_quality'), hasattr(h, 'is_truly_lossless'), hasattr(h, '_VERDICT_SCORE'))"`
Expected: `False False False`

- [ ] **Step 7: Commit**

```bash
git add orpheus_healer.py healer_config.toml
git commit -m "refactor: the healer uses a measured status rather than a guessed verdict"
```

---

### Task 7: Duplicate ranking uses provenance

**Files:**
- Modify: `check_duplicates.py:25-35`, `check_duplicates.py:86-120`, `check_duplicates.py:200-210`

**Interfaces:**
- Consumes: `inspect()` from Task 4, `_normalize_for_dedup` and `_DUP_MARKER_RE` from `orpheus_healer.py`.
- Produces: `get_file_quality_score(file_path: Path) -> tuple` ordered as `(status_rank, provenance_rank, bit_depth, sample_rate_bonus, has_no_marker, file_size, -filename_len, display)`. The last element is a dict for display, as it is now, so callers using `score_tuple[-1]` do not break.

- [ ] **Step 1: Fix the imports**

At lines 25 to 35, drop `analyze_flac_quality` and `_VERDICT_SCORE` from the `orpheus_healer` import block. Keep `_normalize_for_dedup` and `_DUP_MARKER_RE`. Add:

```python
from quality_probe import inspect
```

- [ ] **Step 2: Rewrite the scoring**

Replace the body of `get_file_quality_score()` (lines 86 to 120):

```python
_STATUS_RANK = {"verified": 3, "unknown": 2, "suspect": 1, "corrupt": 0}


def get_file_quality_score(file_path: Path) -> tuple:
    """Sort key for duplicates. The higher it sorts, the more it is preferred.

    Provenance wins first, then bit depth, then file size. Size decides last
    because two lossless files with the same content should be about the same
    size, and the larger one is usually the one that is not truncated.
    """
    try:
        size_bytes = file_path.stat().st_size
    except OSError:
        size_bytes = 0

    status, measurement, prov = inspect(str(file_path))

    status_rank = _STATUS_RANK.get(status, 0)
    provenance_rank = 1 if prov is not None else 0
    bit_depth = measurement.effective_bit_depth or 0
    sample_rate = measurement.sample_rate or 0
    sr_bonus = 0.5 if abs(sample_rate / 1000.0 - 44.1) < 0.5 else 0.0
    has_marker = 1 if (_DUP_MARKER_RE.search(file_path.name)
                       or _TIMESTAMP_RE.search(file_path.name)) else 0

    display = {
        "status": status,
        "reasons": measurement.reasons,
        "cutoff_hz": measurement.cutoff_hz,
        "sample_rate": sample_rate,
        "bit_depth": bit_depth,
        "provenance": f"{prov.source_module}/{prov.codec_served}" if prov else None,
    }

    return (status_rank, provenance_rank, bit_depth, sr_bonus,
            1 - has_marker, size_bytes, -len(file_path.name), display)
```

- [ ] **Step 3: Adjust how the tuple is used**

At lines 205 to 212, change the sort key so the `display` element is not compared:

```python
        group_entries.sort(key=lambda x: x["score_tuple"][:-1])
```

Change `"analysis": score_tuple[-1]` to `"display": score_tuple[-1]` as well, then update every place reading `entry["analysis"]` to read `entry["display"]` with the new keys (`status`, `reasons`, `cutoff_hz`, `sample_rate`, `bit_depth`, `provenance`). The old keys `verdict` and `bandwidth_pct` are gone.

Replace `colorize_verdict()` (around line 124) with the same status version used in `orpheus_healer.py`:

```python
def colorize_status(status: str) -> str:
    if status in ("suspect", "corrupt"):
        return f"{Colors.RED}{status}{Colors.RESET}"
    if status == "verified":
        return f"{Colors.GREEN}{status}{Colors.RESET}"
    return f"{Colors.YELLOW}{status}{Colors.RESET}"
```

Run: `grep -n "verdict\|bandwidth_pct" check_duplicates.py`
Expected: no results. If any remain, keep replacing until there are none.

- [ ] **Step 4: Dry-run it against the ground-truth folder**

Run: `python check_duplicates.py --target-dir ground_truth --dry-run`
Expected: it runs without an exception. The `orig_*` and `fake_*` files have different names, so no duplicate group is found. What is being tested here is that the scoring runs without error across 15 real files.

- [ ] **Step 5: Commit**

```bash
git add check_duplicates.py
git commit -m "refactor: rank duplicates by provenance and effective bit depth"
```

---

### Task 8: Fix the config and clear out the leftovers

**Files:**
- Modify: `config/settings.json`
- Modify: `config/settings.json`, the `modules.applemusic.codec` part
- Delete: `test_analyzer.py`

**Interfaces:**
- Consumes: nothing.
- Produces: no API. This task closes the paths that make the format target unreachable.

- [ ] **Step 1: Drop the alac to flac mapping**

In `config/settings.json`, inside `global.advanced.codec_conversions`, delete the line `"alac": "flac"`. Keep `"wav": "flac"`.

While that mapping is there, every ALAC download is converted on arrival, so an ALAC file can never exist in the library.

- [ ] **Step 2: Ask Apple Music for ALAC**

In `config/settings.json`, change `modules.applemusic.codec` from `"aac"` to `"alac"`.

`modules/applemusic/interface.py:218` already gates ALAC on `QualityEnum.LOSSLESS` or `HIFI`, and `global.general.download_quality` is already set to `hifi`, so nothing else needs changing.

- [ ] **Step 3: Check the config reads back**

Run: `python -c "import json; d=json.load(open('config/settings.json')); print(d['global']['advanced']['codec_conversions'], d['modules']['applemusic']['codec'])"`
Expected: `{'wav': 'flac'} alac`

- [ ] **Step 4: Delete the dead manual probe**

`test_analyzer.py` imports `analyze_flac_quality` and `is_truly_lossless`, two functions that no longer exist after Task 6.

```bash
git rm test_analyzer.py
```

- [ ] **Step 5: Run the whole test suite**

```bash
python test_quality_probe.py && python test_provenance.py
```

Expected: every line `PASS`, exit code 0

- [ ] **Step 6: Make sure no old verdict is left**

```bash
grep -rn "Natural Rolloff\|Lossy Transcode\|is_truly_lossless\|_VERDICT_SCORE\|analyze_flac_quality" --include=*.py --include=*.toml --include=*.json . | grep -v "^./OrpheusDL-master/" | grep -v "^./docs/"
```

Expected: only the matches in `orpheus_healer.py` inside the `soniq_flags` list, which is Soniq's data and stays on purpose. Delete any other match in the code.

- [ ] **Step 7: Commit**

```bash
git add config/settings.json
git commit -m "fix: clear the path for ALAC and delete the dead analyzer probe"
```

---

## Notes for whoever carries this out

The ground-truth set proves nothing about AAC 256 and above, and was never designed to. Any urge to lower a threshold so 256 kbps files get caught ends in false accusations against genuine files. The measured deviation between AAC 256 and its source is only 0.12 to 0.23 dB across every frequency band. No threshold separates the two.

If a ground-truth file goes missing, rebuild it with the `-vn` flag, which is required because embedded cover art is an h264 stream that breaks m4a muxing:

```shell
ffmpeg -vn -i orig.flac -c:a aac -b:a 256k t.m4a && ffmpeg -vn -i t.m4a -c:a flac fake.flac
```
