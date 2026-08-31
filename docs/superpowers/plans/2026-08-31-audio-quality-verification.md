# Audio Quality Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ganti sistem verdict tebakan di `orpheus_healer.py` dengan provenance yang ditulis ke tag file plus detektor sinyal yang cuma melaporkan bukti terukur.

**Architecture:** Modul baru `quality_probe.py` di root repo berisi pengukuran sinyal (median lima jendela FFT, deteksi tebing lowpass, upsampling, bit depth semu) dan fungsi `classify()`. Modul baru `orpheus/provenance.py` menulis dan membaca asal-usul file lewat mutagen. `orpheus_healer.py` dan `check_duplicates.py` beralih memakai keduanya, lalu semua string verdict lama dibuang.

**Tech Stack:** Python 3.12, numpy, soundfile, mutagen, ffmpeg-python. Tanpa framework test. Semua test dijalankan `python test_<nama>.py`.

**Spec:** `docs/superpowers/specs/2026-08-31-audio-quality-verification-prd.md`

## Global Constraints

- Tidak ada framework test. Setiap file test adalah script biasa berisi `assert`, dijalankan dengan `python test_<nama>.py`, keluar kode 0 kalau semua lulus.
- Set ground-truth ada di `ground_truth/` di root repo: `orig_1.flac`, `orig_2.flac`, `orig_3.flac`, dan 12 file `fake_*` (aac128/256/320 untuk tiga sumber, plus mp3128, mp3320, opus128 untuk sumber pertama). Folder ini 370 MB dan tidak boleh masuk git.
- Status yang sah cuma empat string: `"verified"`, `"suspect"`, `"unknown"`, `"corrupt"`. Tidak ada string verdict lain di kode mana pun setelah Task 8 selesai.
- Ambang yang dipakai, semuanya konstanta bernama di `quality_probe.py`: `CLIFF_MIN_DROP_DB = 30.0`, `CLIFF_SPAN_HZ = 1000.0`, `CLIFF_RECOVERY_DB = 5.0`, `CLIFF_SUSPECT_MAX_HZ = 19000.0`, `SMOOTH_HZ = 200.0`, `UPSAMPLE_MIN_HZ = 24000.0`, `N_WINDOWS = 5`, `N_SAMPLES = 131072`.
- Catatan dari pelaksanaan Task 1: rancangan awal memakai `CLIFF_FLOOR_DB = -60.0` sebagai syarat kedua dan tidak meratakan spektrum. Diuji pada ground-truth, `orig_1.flac` salah dituduh (lembah acak di 7,4 kHz terbaca sebagai tebing) karena satu bin FFT di sini lebarnya 0,34 Hz dan nilainya melompat puluhan dB antar bin. Sekarang spektrum diratakan 200 Hz dulu, dan syarat keduanya adalah energi tidak pernah balik naik setelah tebing, bukan ambang absolut. `orig_2.flac` yang sepi di frekuensi tinggi (-88 dB pada 16 kHz) lolos dengan benar karena turunnya landai.
- Codec lossless: `{"flac", "alac", "wav", "aiff"}`. Konversi ALAC ke FLAC tetap lossless dan bukan alasan menandai file.
- Pesan log dan komentar ditulis dalam bahasa Indonesia mengikuti gaya `orpheus_healer.py`. Nama fungsi, variabel, dan docstring API dalam bahasa Inggris.
- Setiap commit diatribusikan ke Ihsan-p1. Jangan menambahkan trailer co-author apa pun.

---

### Task 1: Spektrum median dan deteksi tebing lowpass

**Files:**
- Create: `quality_probe.py`
- Create: `test_quality_probe.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: tidak ada.
- Produces: `median_spectrum(path: str, n_windows: int = 5, n_samples: int = 131072) -> tuple[np.ndarray, np.ndarray, int]` mengembalikan `(freqs, db, sample_rate)` dengan `db` sudah dinormalisasi ke puncak 0 dB. `find_lowpass_cliff(freqs: np.ndarray, db: np.ndarray, min_drop_db: float = 30.0, span_hz: float = 1000.0) -> tuple[float | None, float | None]` mengembalikan `(cutoff_hz, drop_db)`.

- [ ] **Step 1: Kunci folder ground-truth dari git**

Tambahkan satu baris di akhir `.gitignore`:

```
/ground_truth/
```

Lalu pastikan 15 file ada:

```bash
ls ground_truth | wc -l
```

Expected: `15`

- [ ] **Step 2: Tulis test yang gagal**

Buat `test_quality_probe.py`:

```python
"""Test detektor kualitas. Jalankan: python test_quality_probe.py"""
import os
import sys

GT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ground_truth")

from quality_probe import find_lowpass_cliff, median_spectrum


def test_median_spectrum_shape():
    freqs, db, sr = median_spectrum(os.path.join(GT, "orig_1.flac"))
    assert sr == 44100, f"sample rate tak terduga: {sr}"
    assert len(freqs) == len(db), "panjang freqs dan db harus sama"
    assert abs(db.max()) < 1e-6, f"spektrum harus dinormalisasi ke 0 dB, dapat {db.max()}"


def test_cliff_found_on_aac128():
    freqs, db, _ = median_spectrum(os.path.join(GT, "fake_1_aac128.flac"))
    cutoff, drop = find_lowpass_cliff(freqs, db)
    assert cutoff is not None, "AAC 128k harus punya tebing lowpass"
    assert cutoff < 19000.0, f"tebing AAC 128k harus di bawah 19 kHz, dapat {cutoff}"
    assert drop >= 30.0, f"jatuhnya harus >= 30 dB, dapat {drop}"


def test_no_cliff_on_originals():
    for name in ("orig_1.flac", "orig_2.flac", "orig_3.flac"):
        freqs, db, _ = median_spectrum(os.path.join(GT, name))
        cutoff, _ = find_lowpass_cliff(freqs, db)
        assert cutoff is None or cutoff >= 19000.0, f"{name} salah dituduh: tebing di {cutoff}"


def test_spectrum_is_repeatable():
    path = os.path.join(GT, "fake_2_aac128.flac")
    first = find_lowpass_cliff(*median_spectrum(path)[:2])
    second = find_lowpass_cliff(*median_spectrum(path)[:2])
    assert first == second, f"hasil tidak stabil: {first} vs {second}"


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

- [ ] **Step 3: Jalankan test, pastikan gagal**

Run: `python test_quality_probe.py`
Expected: FAIL dengan `ModuleNotFoundError: No module named 'quality_probe'`

- [ ] **Step 4: Tulis implementasi minimal**

Buat `quality_probe.py`:

```python
"""Pengukuran kualitas audio yang bisa diulang.

Modul ini tidak mengeluarkan verdict. Ia melaporkan angka yang bisa diukur
ulang dengan hasil sama, dan diam untuk hal yang tidak bisa dibuktikan.
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
    """Ambil beberapa jendela FFT sepanjang track, kembalikan median spektrumnya.

    Satu jendela di tengah track membuat hasil berubah-ubah tergantung isi
    bagian itu. Median dari beberapa posisi tetap sama setiap kali dijalankan.
    """
    spectra = []
    with sf.SoundFile(path) as af:
        sr = af.samplerate
        total = len(af)
        if total < n_samples:
            raise ValueError(f"file terlalu pendek: {total} frame")
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
        raise ValueError("tidak ada jendela yang bisa dibaca")
    freqs = np.fft.rfftfreq(n_samples, d=1.0 / sr)
    return freqs, np.median(np.vstack(spectra), axis=0), sr


def find_lowpass_cliff(freqs: np.ndarray, db: np.ndarray,
                       min_drop_db: float = CLIFF_MIN_DROP_DB,
                       span_hz: float = CLIFF_SPAN_HZ) -> tuple[float | None, float | None]:
    """Cari tebing encoder: energi jatuh tajam lalu tidak pernah kembali.

    Syarat kedua penting. Tanpa itu, lembah biasa di tengah spektrum ikut
    terhitung sebagai tebing.
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

- [ ] **Step 5: Jalankan test, pastikan lulus**

Run: `python test_quality_probe.py`
Expected: empat baris `PASS`, exit code 0

- [ ] **Step 6: Commit**

```bash
git add .gitignore quality_probe.py test_quality_probe.py
git commit -m "feat: tambah pengukuran spektrum median dan deteksi tebing lowpass"
```

---

### Task 2: Detektor upsampling, bit depth semu, dan fungsi probe

**Files:**
- Modify: `quality_probe.py`
- Modify: `test_quality_probe.py`

**Interfaces:**
- Consumes: `median_spectrum()`, `find_lowpass_cliff()` dari Task 1.
- Produces: dataclass `ProbeResult` dengan field `status: str`, `reasons: list[str]`, `sample_rate: int | None`, `declared_bit_depth: int | None`, `effective_bit_depth: int | None`, `cutoff_hz: float | None`, `cutoff_drop_db: float | None`, `highest_energy_hz: float | None`, `error: str | None`. Fungsi `bit_depths(path: str) -> tuple[int | None, int | None]` mengembalikan `(declared, effective)`. Fungsi `probe(path: str) -> ProbeResult` dengan `status` salah satu dari `"suspect"`, `"unknown"`, `"corrupt"`.

- [ ] **Step 1: Tulis test yang gagal**

Tambahkan ke `test_quality_probe.py`, di atas blok `if __name__`:

```python
def test_probe_flags_low_bitrate_fakes():
    for name in ("fake_1_aac128.flac", "fake_2_aac128.flac", "fake_3_aac128.flac",
                 "fake_1_mp3128.flac", "fake_1_opus128.flac"):
        result = probe(os.path.join(GT, name))
        assert result.status == "suspect", f"{name} harusnya suspect, dapat {result.status}"
        assert result.reasons, f"{name} suspect tanpa alasan tercatat"


def test_probe_clears_originals():
    for name in ("orig_1.flac", "orig_2.flac", "orig_3.flac"):
        result = probe(os.path.join(GT, name))
        assert result.status != "suspect", f"{name} salah dituduh: {result.reasons}"


def test_probe_admits_it_cannot_see_high_bitrate():
    for name in ("fake_1_aac256.flac", "fake_2_aac256.flac", "fake_3_aac256.flac",
                 "fake_1_aac320.flac", "fake_1_mp3320.flac"):
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
```

Ubah baris import di puncak file jadi:

```python
from quality_probe import find_lowpass_cliff, median_spectrum, probe
```

- [ ] **Step 2: Jalankan test, pastikan gagal**

Run: `python test_quality_probe.py`
Expected: FAIL dengan `ImportError: cannot import name 'probe'`

- [ ] **Step 3: Tulis implementasi**

Tambahkan ke `quality_probe.py`. Import di puncak file menjadi:

```python
import os
from dataclasses import dataclass, field

import numpy as np
import soundfile as sf
```

Lalu di bawah konstanta:

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

Dan di bawah `find_lowpass_cliff`:

```python
def bit_depths(path: str, n_frames: int = 500_000) -> tuple[int | None, int | None]:
    """Bandingkan bit depth yang dideklarasikan dengan yang benar-benar dipakai.

    soundfile menaruh sampel di bit teratas int32, jadi jumlah bit nol di bawah
    memberitahu berapa bit yang sebenarnya terisi. File 24-bit yang isinya
    16-bit dipadding punya delapan bit nol lebih banyak dari seharusnya.
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
    """Ukur satu file dan laporkan bukti keras yang ditemukan."""
    if not os.path.exists(path):
        return ProbeResult(status="corrupt", error="file tidak ditemukan")

    extension = os.path.splitext(path)[1].lower()
    if extension not in SIGNAL_EXTENSIONS:
        return ProbeResult(status="unknown",
                           error=f"probe sinyal tidak berlaku untuk {extension}")

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
        result.error = f"bit depth tak terbaca: {e}"

    if result.cutoff_hz is not None and result.cutoff_hz < CLIFF_SUSPECT_MAX_HZ:
        result.reasons.append(
            f"tebing lowpass {result.cutoff_hz / 1000:.1f} kHz "
            f"turun {result.cutoff_drop_db:.0f} dB")

    if sr >= 88200 and result.highest_energy_hz < UPSAMPLE_MIN_HZ:
        result.reasons.append(
            f"dideklarasikan {sr / 1000:.1f} kHz tapi energi berhenti di "
            f"{result.highest_energy_hz / 1000:.1f} kHz")

    if (result.declared_bit_depth and result.effective_bit_depth
            and result.effective_bit_depth <= result.declared_bit_depth - 8):
        result.reasons.append(
            f"{result.declared_bit_depth}-bit tapi cuma "
            f"{result.effective_bit_depth} bit yang terisi")

    result.status = "suspect" if result.reasons else "unknown"
    return result
```

- [ ] **Step 4: Jalankan test, pastikan lulus**

Run: `python test_quality_probe.py`
Expected: sembilan baris `PASS`, exit code 0

Kalau `test_probe_clears_originals` gagal, jangan longgarkan ambang untuk mengejar hasil. Catat cutoff yang terukur, periksa file itu di Audition, lalu putuskan apakah file ground-truth itu memang bersih.

- [ ] **Step 5: Commit**

```bash
git add quality_probe.py test_quality_probe.py
git commit -m "feat: tambah deteksi upsampling, bit depth semu, dan fungsi probe"
```

---

### Task 3: Provenance ditulis dan dibaca dari tag file

**Files:**
- Create: `orpheus/provenance.py`
- Create: `test_provenance.py`

**Interfaces:**
- Consumes: `ContainerEnum` dari `utils/models.py`.
- Produces: dataclass `Provenance(source_module: str, quality_tier: str, codec_served: str, codec_final: str, downloaded_at: str, orpheus_version: str, bitrate_kbps: int | None = None, sample_rate: int | None = None, bit_depth: int | None = None)`. Fungsi `write_provenance(file_path: str, container: ContainerEnum, prov: Provenance) -> None` dan `read_provenance(file_path: str) -> Provenance | None`. Konstanta `LOSSLESS_CODECS: set[str]` dan `ORPHEUS_VERSION: str`.

- [ ] **Step 1: Tulis test yang gagal**

Buat `test_provenance.py`:

```python
"""Test penulisan provenance. Jalankan: python test_provenance.py"""
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
        assert loaded == SAMPLE, f"provenance berubah setelah dibaca ulang: {loaded}"
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
        tagger["title"] = "Judul Asli"
        tagger.save()
        write_provenance(path, ContainerEnum.flac, SAMPLE)
        assert FLAC(path)["title"] == ["Judul Asli"], "tag lain ikut terhapus"
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

- [ ] **Step 2: Jalankan test, pastikan gagal**

Run: `python test_provenance.py`
Expected: FAIL dengan `ModuleNotFoundError: No module named 'orpheus.provenance'`

- [ ] **Step 3: Tulis implementasi**

Buat `orpheus/provenance.py`:

```python
"""Catatan asal-usul file: modul, tier, codec, waktu unduh.

Disimpan di dalam tag file, bukan di database terpisah. File di library sering
dipindah dan diganti nama, dan index yang memakai path sebagai kunci akan putus
begitu itu terjadi.
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
    """Tulis provenance ke tag file. Tag lain tidak disentuh."""
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
        raise ValueError(f"container tidak didukung untuk provenance: {container}")
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
    """Baca provenance dari file. Kembalikan None kalau tidak ada."""
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

- [ ] **Step 4: Jalankan test, pastikan lulus**

Run: `python test_provenance.py`
Expected: empat baris `PASS`, exit code 0

- [ ] **Step 5: Commit**

```bash
git add orpheus/provenance.py test_provenance.py
git commit -m "feat: catat asal-usul file di tag lewat modul provenance"
```

---

### Task 4: Fungsi classify menggabungkan provenance dan probe

**Files:**
- Modify: `quality_probe.py`
- Modify: `test_quality_probe.py`

**Interfaces:**
- Consumes: `ProbeResult` dan `probe()` dari Task 2, `Provenance` dan `LOSSLESS_CODECS` dari Task 3.
- Produces: `classify(result: ProbeResult, prov: Provenance | None, file_path: str) -> str` mengembalikan `"verified"`, `"suspect"`, `"unknown"`, atau `"corrupt"`. Fungsi `inspect(file_path: str) -> tuple[str, ProbeResult, Provenance | None]` yang menjalankan `read_provenance` lalu `probe` lalu `classify` sekaligus.

- [ ] **Step 1: Tulis test yang gagal**

Tambahkan ke `test_quality_probe.py`:

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
    assert classify(ProbeResult(status="suspect", reasons=["tebing"]), None, "x.flac") == "suspect"
    assert classify(ProbeResult(status="unknown"), None, "x.flac") == "unknown"


def test_inspect_on_ground_truth():
    from quality_probe import inspect
    status, result, prov = inspect(os.path.join(GT, "fake_1_aac128.flac"))
    assert status == "suspect"
    assert prov is None
    assert result.cutoff_hz is not None
```

- [ ] **Step 2: Jalankan test, pastikan gagal**

Run: `python test_quality_probe.py`
Expected: FAIL dengan `ImportError: cannot import name 'classify'`

- [ ] **Step 3: Tulis implementasi**

Tambahkan di akhir `quality_probe.py`:

```python
from orpheus.provenance import LOSSLESS_CODECS, Provenance, read_provenance

LOSSLESS_EXTENSIONS = (".flac", ".wav", ".aiff", ".aif", ".alac")


def classify(result: ProbeResult, prov: Provenance | None, file_path: str) -> str:
    """Gabungkan bukti provenance dan bukti sinyal jadi satu status.

    Provenance menang atas analisis sinyal. Kalau kita tahu file datang dari
    modul apa dengan codec apa, tidak ada gunanya menebak lewat FFT.
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
    """Baca provenance, ukur sinyal, kembalikan status akhir."""
    prov = read_provenance(file_path)
    result = probe(file_path)
    return classify(result, prov, file_path), result, prov
```

- [ ] **Step 4: Jalankan test, pastikan lulus**

Run: `python test_quality_probe.py`
Expected: lima belas baris `PASS`, exit code 0

- [ ] **Step 5: Commit**

```bash
git add quality_probe.py test_quality_probe.py
git commit -m "feat: gabungkan provenance dan probe lewat classify"
```

---

### Task 5: Tulis provenance saat file diunduh

**Files:**
- Modify: `orpheus/music_downloader.py:313`, `orpheus/music_downloader.py:543-620`, `orpheus/music_downloader.py:621-630`
- Test: verifikasi manual lewat satu unduhan nyata, dijelaskan di Step 5

**Interfaces:**
- Consumes: `Provenance`, `write_provenance`, `ORPHEUS_VERSION` dari Task 3.
- Produces: setiap file hasil `download_track()` membawa tag provenance. Tidak ada API baru untuk task lain.

- [ ] **Step 1: Tambahkan import**

Di `orpheus/music_downloader.py`, di bawah baris `from orpheus.tagging import tag_file` (baris 9):

```python
from orpheus.provenance import ORPHEUS_VERSION, Provenance, write_provenance
```

Dan pastikan `datetime` tersedia di puncak file:

```python
from datetime import datetime, timezone
```

- [ ] **Step 2: Lacak codec akhir melewati konversi**

Di baris 313, tepat setelah `codec = track_info.codec`, tambahkan:

```python
        final_codec = codec
```

Lalu di blok konversi, tepat setelah baris `track_location = new_track_location` (sekitar baris 616), tambahkan pada level indentasi yang sama:

```python
                final_codec = new_codec
```

`codec` menyimpan apa yang benar-benar dikirim modul, termasuk kalau `download_info.different_codec` menimpanya di baris 398. `final_codec` menyimpan hasil akhir setelah `codec_conversions`. Keduanya perlu dicatat karena ALAC yang dikonversi ke FLAC tetap lossless, sedangkan AAC yang dibungkus jadi FLAC tidak.

- [ ] **Step 3: Tulis provenance setelah tagging**

Di blok `try` yang memanggil `tag_file` (baris 623 sampai 630), tambahkan setelah kedua panggilan `tag_file`, masih di dalam `try`:

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
                self.print(f'Warning: provenance tidak tertulis: {e}')
```

`track_info.sample_rate` disimpan dalam kHz sebagai float (lihat `utils/models.py`), jadi dikalikan 1000 supaya satuannya sama dengan yang dilaporkan `quality_probe.probe()`.

Kegagalan menulis provenance tidak boleh membatalkan unduhan yang sudah berhasil, karena itu blok `try` sendiri.

- [ ] **Step 4: Cek sintaks**

Run: `python -c "import orpheus.music_downloader"`
Expected: tidak ada output, exit code 0

- [ ] **Step 5: Verifikasi lewat satu unduhan nyata**

Unduh satu track pendek dari modul yang sudah login:

```bash
python orpheus.py <url-track>
```

Lalu baca provenance file hasilnya:

```bash
python -c "from orpheus.provenance import read_provenance; print(read_provenance(r'<path-file-hasil>'))"
```

Expected: sebuah `Provenance` dengan `source_module` sesuai modul yang dipakai, `codec_served` berisi codec yang dikirim server, dan `downloaded_at` berisi waktu hari ini.

Kalau tidak punya modul yang siap login, lewati langkah ini dan catat di commit message bahwa verifikasi unduhan nyata belum dilakukan.

- [ ] **Step 6: Commit**

```bash
git add orpheus/music_downloader.py
git commit -m "feat: tulis provenance ke setiap file yang diunduh"
```

---

### Task 6: Healer memakai status, bukan verdict

**Files:**
- Modify: `orpheus_healer.py:99`, `orpheus_healer.py:114-137`, `orpheus_healer.py:253-311`, `orpheus_healer.py:320-362`, `orpheus_healer.py:405-420`, `orpheus_healer.py:815-1000`, `orpheus_healer.py:1171-1260`, `orpheus_healer.py:1425-1460`, `orpheus_healer.py:1570-1585`
- Modify: `healer_config.toml`

**Interfaces:**
- Consumes: `inspect()`, `ProbeResult` dari Task 4.
- Produces: `orpheus_healer.py` tidak lagi mengekspor `analyze_flac_quality`, `is_truly_lossless`, `_VERDICT_SCORE`, atau `_get_verdict_score`. Tetap mengekspor `_normalize_for_dedup` dan `_DUP_MARKER_RE` untuk `check_duplicates.py`.

- [ ] **Step 1: Hapus mesin verdict lama**

Hapus dari `orpheus_healer.py`:

- `_THRESHOLDS` dan `_compute_rolloff_slope()` (baris 815 sampai 840)
- `analyze_flac_quality()` seluruhnya (baris 841 sampai 954)
- `is_truly_lossless()` seluruhnya (baris 956 sampai 968)
- `_VERDICT_SCORE` (baris 320 sampai 330)
- `_get_verdict_score()` (baris 357 sampai 362)
- Blok `"quality_score"` di `_DEFAULT_CONFIG` (baris 114 dan sekitarnya) dan baris penggabungannya di baris 137
- Entri `"bad_verdicts"` di `_DEFAULT_CONFIG` (baris 99)

Tambahkan import di puncak file:

```python
from quality_probe import inspect
```

- [ ] **Step 2: Ganti pemilihan track bermasalah dari CSV**

`parse_soniq_csv()` sekarang menerima `bad_verdicts` dan menyaring baris CSV dengan mencocokkan string verdict. Soniq punya bukti yang tidak kita punya, jadi outputnya tetap dipakai apa adanya sebagai daftar kandidat, tapi parameternya diganti nama supaya jelas itu data Soniq, bukan verdict kita.

Ubah tanda tangan di baris 253:

```python
def parse_soniq_csv(csv_path: str, soniq_flags: list[str]) -> list[dict]:
```

Ganti pemakaian `bad_verdicts` di dalam fungsi (baris 277 dan 311) menjadi `soniq_flags`. Di baris 1433 sampai 1435, ganti:

```python
    soniq_flags = list(CONFIG["settings"]["soniq_flags"])
```

dan hapus baris `bad_verdicts.append("Possibly Upsampled")` beserta kondisinya. Di baris 1458, panggilannya jadi `parse_soniq_csv(args.csv, soniq_flags)`.

- [ ] **Step 3: Ganti ranking duplikat berbasis verdict**

Ganti `_sort_key` di dalam `_pick_best_in_group()` (baris 411 sampai 419) menjadi:

```python
    def _sort_key(entry):
        bd = _parse_bd(entry.get("bit_depth"))
        bw = _parse_bw(entry.get("bandwidth"))
        sr = _parse_sr(entry.get("sample_rate"))
        # Bonus kecil untuk 44.1 kHz supaya hi-res hasil upsample tidak menang otomatis
        sr_bonus = 0.5 if abs(sr - 44.1) < 0.5 else 0.0
        return (bd, bw, sr_bonus)
```

Baris ini mengurutkan entri CSV Soniq, bukan file di disk. Kolom bit depth dan bandwidth berisi pengukuran, kolom verdict berisi kesimpulan Soniq yang tidak bisa kita audit, jadi yang dipakai cuma pengukurannya. Perbarui juga docstring fungsi itu menjadi `Prioritas: bit depth -> bandwidth -> sample rate`.

Ganti `_colorize_verdict()` (baris 424 sampai 434) dengan versi yang mewarnai status, dan ganti setiap pemanggilnya:

```python
def _colorize_status(status: str) -> str:
    if status in ("suspect", "corrupt"):
        return f"{C.RED}{status}{C.RESET}"
    if status == "verified":
        return f"{C.GREEN}{status}{C.RESET}"
    return f"{C.YELLOW}{status}{C.RESET}"
```

- [ ] **Step 4: Ganti keputusan setelah unduh ulang**

Di baris 1227 sampai 1256, ganti blok analisis menjadi:

```python
        status, measurement, prov = inspect(new_file)
        attempt["status"] = status
        attempt["reasons"] = measurement.reasons

        sr_str = f"{measurement.sample_rate / 1000:.1f}kHz" if measurement.sample_rate else "?"
        co_str = (f"{measurement.cutoff_hz / 1000:.1f}kHz"
                  if measurement.cutoff_hz is not None else "tidak ada tebing")
        src_str = f"{prov.source_module}/{prov.codec_served}" if prov else "tanpa provenance"

        if status in ("verified", "unknown"):
            log.info(f"  {C.GREEN}[TERIMA] {label} → {status} ({src_str}){C.RESET}")
            log.info(f"           {sr_str} | {co_str}")
            if preserved_tags:
                apply_custom_tags(new_file, preserved_tags)
            attempts.append(attempt)
            return {"status": status, "source": module, "label": label,
                    "file_path": new_file, "measurement": measurement, "attempts": attempts}

        log.warning(f"  {C.YELLOW}[TOLAK] {label} → {status}: "
                    f"{'; '.join(measurement.reasons) or measurement.error}{C.RESET}")
        candidates.append({"source": module, "label": label, "file": new_file,
                           "measurement": measurement, "status": status})
        attempts.append(attempt)
```

Status `unknown` diterima. Sistem ini tidak menolak file hanya karena tidak bisa membuktikan apa-apa tentangnya.

Hapus parameter `quality_score` dari tanda tangan fungsi di baris 1171 dan dari pemanggilnya di baris 1579. Untuk memilih kandidat terbaik ketika semua ditolak, urutkan `candidates` dengan kunci: file tanpa alasan `suspect` menang, lalu bit depth efektif lebih tinggi, lalu ukuran file lebih besar.

- [ ] **Step 5: Perbarui config**

Di `healer_config.toml`, hapus blok `[quality_score]` seluruhnya. Ganti `bad_verdicts` di `[settings]` dengan:

```toml
# Verdict Soniq yang dipakai untuk memilih kandidat dari CSV.
# Ini data Soniq, bukan penilaian kita sendiri.
soniq_flags = [
    "Upsampled / Transcoded",
    "Lossy Transcode",
    "Low-Bitrate Lossy",
    "Possibly Upsampled",
    "Error",
]

# Status hasil pengukuran yang memicu unduh ulang.
# Pilihan yang sah: "suspect", "corrupt", "unknown".
# "unknown" tidak disarankan: sebagian besar library lama akan masuk kategori itu.
redownload_status = ["suspect", "corrupt"]
```

Tambahkan `"redownload_status": ["suspect", "corrupt"]` dan `"soniq_flags": [...]` ke `_DEFAULT_CONFIG["settings"]` di `orpheus_healer.py` supaya config lama tetap jalan.

- [ ] **Step 6: Cek sintaks dan jalan kering**

Run: `python -c "import orpheus_healer"`
Expected: tidak ada output, exit code 0

Run: `python -c "import orpheus_healer as h; print(hasattr(h, 'analyze_flac_quality'), hasattr(h, 'is_truly_lossless'), hasattr(h, '_VERDICT_SCORE'))"`
Expected: `False False False`

- [ ] **Step 7: Commit**

```bash
git add orpheus_healer.py healer_config.toml
git commit -m "refactor: healer memakai status terukur, bukan verdict tebakan"
```

---

### Task 7: Ranking duplikat memakai provenance

**Files:**
- Modify: `check_duplicates.py:25-35`, `check_duplicates.py:86-120`, `check_duplicates.py:200-210`

**Interfaces:**
- Consumes: `inspect()` dari Task 4, `_normalize_for_dedup` dan `_DUP_MARKER_RE` dari `orpheus_healer.py`.
- Produces: `get_file_quality_score(file_path: Path) -> tuple` dengan urutan `(status_rank, provenance_rank, bit_depth, sample_rate_bonus, has_no_marker, file_size, -filename_len, display)`. Elemen terakhir adalah dict untuk ditampilkan, sama seperti sekarang, supaya pemanggil yang memakai `score_tuple[-1]` tidak pecah.

- [ ] **Step 1: Perbaiki import**

Di baris 25 sampai 35, hapus `analyze_flac_quality` dan `_VERDICT_SCORE` dari blok import `orpheus_healer`. Sisakan `_normalize_for_dedup` dan `_DUP_MARKER_RE`. Tambahkan:

```python
from quality_probe import inspect
```

- [ ] **Step 2: Tulis ulang skoring**

Ganti isi `get_file_quality_score()` (baris 86 sampai 120):

```python
_STATUS_RANK = {"verified": 3, "unknown": 2, "suspect": 1, "corrupt": 0}


def get_file_quality_score(file_path: Path) -> tuple:
    """Tuple untuk mengurutkan duplikat. Makin besar makin dipilih.

    Provenance menang lebih dulu, lalu bit depth, lalu ukuran file. Ukuran file
    jadi penentu terakhir karena dua file lossless dengan isi sama seharusnya
    berukuran mirip, dan yang lebih besar biasanya yang tidak terpotong.
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

- [ ] **Step 3: Sesuaikan pemakaian tuple**

Di baris 205 sampai 212, ganti kunci pengurutan supaya elemen `display` tidak ikut dibandingkan:

```python
        group_entries.sort(key=lambda x: x["score_tuple"][:-1])
```

Ganti juga `"analysis": score_tuple[-1]` menjadi `"display": score_tuple[-1]`, lalu perbarui setiap tempat yang membaca `entry["analysis"]` untuk membaca `entry["display"]` dengan kunci baru (`status`, `reasons`, `cutoff_hz`, `sample_rate`, `bit_depth`, `provenance`). Kunci lama `verdict` dan `bandwidth_pct` sudah tidak ada.

Ganti `colorize_verdict()` (baris 124 dan sekitarnya) dengan versi status yang sama seperti di `orpheus_healer.py`:

```python
def colorize_status(status: str) -> str:
    if status in ("suspect", "corrupt"):
        return f"{Colors.RED}{status}{Colors.RESET}"
    if status == "verified":
        return f"{Colors.GREEN}{status}{Colors.RESET}"
    return f"{Colors.YELLOW}{status}{Colors.RESET}"
```

Run: `grep -n "verdict\|bandwidth_pct" check_duplicates.py`
Expected: tidak ada hasil. Kalau masih ada, ganti sampai bersih.

- [ ] **Step 4: Jalan kering di folder ground-truth**

Run: `python check_duplicates.py --target-dir ground_truth --dry-run`
Expected: berjalan tanpa exception. File `orig_*` dan `fake_*` punya nama berbeda jadi tidak ada grup duplikat yang terdeteksi. Yang diuji di sini adalah skoring berjalan tanpa error pada 15 file nyata.

- [ ] **Step 5: Commit**

```bash
git add check_duplicates.py
git commit -m "refactor: ranking duplikat memakai provenance dan bit depth efektif"
```

---

### Task 8: Perbaiki config dan bersihkan sisa

**Files:**
- Modify: `config/settings.json`
- Modify: `config/settings.json` bagian `modules.applemusic.codec`
- Delete: `test_analyzer.py`

**Interfaces:**
- Consumes: tidak ada.
- Produces: tidak ada API. Task ini menutup jalan yang membuat target format tak tercapai.

- [ ] **Step 1: Buang pemetaan alac ke flac**

Di `config/settings.json`, di dalam `global.advanced.codec_conversions`, hapus baris `"alac": "flac"`. Sisakan `"wav": "flac"`.

Selama pemetaan itu ada, setiap unduhan ALAC dikonversi begitu tiba, jadi tidak akan pernah ada file ALAC di library.

- [ ] **Step 2: Minta ALAC dari Apple Music**

Di `config/settings.json`, ubah `modules.applemusic.codec` dari `"aac"` menjadi `"alac"`.

`modules/applemusic/interface.py:218` sudah menggerbangi ALAC pada `QualityEnum.LOSSLESS` atau `HIFI`, dan `global.general.download_quality` sudah diisi `hifi`, jadi tidak ada perubahan lain yang diperlukan.

- [ ] **Step 3: Verifikasi config terbaca**

Run: `python -c "import json; d=json.load(open('config/settings.json')); print(d['global']['advanced']['codec_conversions'], d['modules']['applemusic']['codec'])"`
Expected: `{'wav': 'flac'} alac`

- [ ] **Step 4: Hapus probe manual yang sudah mati**

`test_analyzer.py` mengimpor `analyze_flac_quality` dan `is_truly_lossless`, dua fungsi yang sudah tidak ada setelah Task 6.

```bash
git rm test_analyzer.py
```

- [ ] **Step 5: Jalankan seluruh test**

```bash
python test_quality_probe.py && python test_provenance.py
```

Expected: semua `PASS`, exit code 0

- [ ] **Step 6: Pastikan tidak ada sisa verdict lama**

```bash
grep -rn "Natural Rolloff\|Lossy Transcode\|is_truly_lossless\|_VERDICT_SCORE\|analyze_flac_quality" --include=*.py --include=*.toml --include=*.json . | grep -v "^./OrpheusDL-master/" | grep -v "^./docs/"
```

Expected: cuma kecocokan di `orpheus_healer.py` pada daftar `soniq_flags` (itu data Soniq, memang dipertahankan). Kalau ada kecocokan lain di kode, hapus.

- [ ] **Step 7: Commit**

```bash
git add config/settings.json
git commit -m "fix: buka jalan ALAC dan hapus probe analyzer yang sudah mati"
```

---

## Catatan untuk pelaksana

Set ground-truth tidak membuktikan apa-apa tentang AAC 256 ke atas, dan memang tidak dirancang untuk itu. Kalau ada dorongan untuk menurunkan ambang supaya file 256 kbps ikut tertangkap, hasilnya adalah tuduhan palsu pada file asli. Deviasi terukur antara AAC 256 dan sumbernya cuma 0,12 sampai 0,23 dB di semua pita frekuensi. Tidak ada ambang yang bisa memisahkan keduanya.

Kalau ada file ground-truth yang hilang, buat ulang dengan flag `-vn` yang wajib karena cover art tertanam adalah stream h264 yang merusak muxing m4a:

```shell
ffmpeg -vn -i orig.flac -c:a aac -b:a 256k t.m4a && ffmpeg -vn -i t.m4a -c:a flac fake.flac
```
