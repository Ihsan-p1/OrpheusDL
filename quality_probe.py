"""Pengukuran kualitas audio yang bisa diulang.

Modul ini tidak mengeluarkan verdict. Ia melaporkan angka yang bisa diukur
ulang dengan hasil sama, dan diam untuk hal yang tidak bisa dibuktikan.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import numpy as np
import soundfile as sf

CLIFF_MIN_DROP_DB = 30.0
CLIFF_SPAN_HZ = 1000.0
CLIFF_RECOVERY_DB = 5.0
CLIFF_SUSPECT_MAX_HZ = 20500.0
CLIFF_MIN_HZ = 8000.0
CLIFF_DEAD_ABOVE_MAX_STD_DB = 2.0
SMOOTH_HZ = 200.0
DEAD_BAND_MAX_STD_DB = 2.8
DEAD_BAND_MIN_GAP_DB = 20.0
DEAD_BAND_RANGE = (0.82, 0.975)
REFERENCE_BAND_RANGE = (0.45, 0.72)
UPSAMPLE_MIN_HZ = 24000.0
N_WINDOWS = 5
N_SAMPLES = 131072

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
    top_band_std_db: float | None = None
    top_band_gap_db: float | None = None
    error: str | None = None


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
    median = np.median(np.vstack(spectra), axis=0)
    return freqs, median - median.max(), sr


def smooth_spectrum(freqs: np.ndarray, db: np.ndarray,
                    width_hz: float = SMOOTH_HZ) -> np.ndarray:
    """Ratakan spektrum di sumbu frekuensi.

    Satu bin FFT di sini lebarnya sepersekian hertz dan nilainya melompat
    puluhan dB antar bin. Tanpa perataan, lembah acak terbaca sebagai tebing
    encoder. Tepi spektrum dipad dengan nilai tepinya sendiri supaya pita
    tertinggi, yang justru paling penting di sini, tidak ikut tertarik.
    """
    bin_hz = float(freqs[1] - freqs[0])
    width = max(1, int(width_hz / bin_hz))
    kernel = np.ones(width) / width
    padded = np.pad(db, width, mode="edge")
    return np.convolve(padded, kernel, mode="same")[width:width + len(db)]


def find_lowpass_cliff(freqs: np.ndarray, db: np.ndarray,
                       min_drop_db: float = CLIFF_MIN_DROP_DB,
                       span_hz: float = CLIFF_SPAN_HZ) -> tuple[float | None, float | None]:
    """Cari tebing encoder: energi jatuh tajam lalu tidak pernah kembali.

    Syarat kedua yang membedakan tebing dari rolloff biasa. Rekaman asli boleh
    saja sepi di frekuensi tinggi, tapi turunnya landai dan energinya masih
    naik turun di atas sana. Encoder memotong, lalu tidak ada apa-apa lagi.

    Tebing di bawah CLIFF_MIN_HZ diabaikan. Tidak ada encoder yang memotong di
    sana, jadi jatuh tajam sebesar itu berasal dari isi rekamannya sendiri,
    biasanya piano atau instrumen tunggal yang spektrumnya memang sepi.

    Syarat ketiga: pita di atas tebing harus mati, bukan cuma sepi. Encoder
    menulis nol di sana, jadi variasinya di bawah satu dB. Rolloff alami yang
    menukik ke arah Nyquist juga turun 30 dB dalam satu kHz dan juga tidak
    pernah kembali, tapi isinya masih bergerak 7 sampai 21 dB. Tanpa syarat ini
    159 file dengan rolloff biasa di 20,5 kHz terbaca bertebing encoder.
    """
    bin_hz = float(freqs[1] - freqs[0])
    span = max(1, int(span_hz / bin_hz))
    smooth = smooth_spectrum(freqs, db)
    drops = smooth[:-span] - smooth[span:]
    for i in np.flatnonzero(drops >= min_drop_db):
        if freqs[i] < CLIFF_MIN_HZ:
            continue
        tail = smooth[i + span:]
        if tail.size < 2:
            continue
        if float(np.median(tail)) > float(smooth[i + span]) + CLIFF_RECOVERY_DB:
            continue
        if float(tail.std()) > CLIFF_DEAD_ABOVE_MAX_STD_DB:
            continue
        return float(freqs[i]), float(drops[i])
    return None, None


def dead_band(freqs: np.ndarray, db: np.ndarray) -> tuple[float | None, float | None]:
    """Ukur seberapa hidup pita frekuensi teratas dibanding pita tengah.

    Rekaman asli punya lantai noise yang bergerak naik turun di sana, bahkan
    ketika isinya sangat sepi. Encoder yang memotong meninggalkan pita yang
    rata tanpa gerakan sama sekali. Yang membedakan bukan seberapa sepi, tapi
    ada atau tidaknya variasi.

    Kembalikan (standar deviasi pita atas, jarak ke pita tengah) dalam dB.
    """
    nyquist = float(freqs[-1])
    top = db[(freqs >= DEAD_BAND_RANGE[0] * nyquist) & (freqs <= DEAD_BAND_RANGE[1] * nyquist)]
    mid = db[(freqs >= REFERENCE_BAND_RANGE[0] * nyquist)
             & (freqs <= REFERENCE_BAND_RANGE[1] * nyquist)]
    if top.size < 2 or mid.size < 2:
        return None, None
    return float(top.std()), float(np.median(mid) - np.median(top))


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
    result.top_band_std_db, result.top_band_gap_db = dead_band(freqs, db)

    try:
        result.declared_bit_depth, result.effective_bit_depth = bit_depths(path)
    except Exception as e:
        result.error = f"bit depth tak terbaca: {e}"

    if result.cutoff_hz is not None and result.cutoff_hz < CLIFF_SUSPECT_MAX_HZ:
        result.reasons.append(
            f"tebing lowpass {result.cutoff_hz / 1000:.1f} kHz "
            f"turun {result.cutoff_drop_db:.0f} dB")

    if (result.top_band_std_db is not None
            and result.top_band_std_db < DEAD_BAND_MAX_STD_DB
            and result.top_band_gap_db >= DEAD_BAND_MIN_GAP_DB):
        result.reasons.append(
            f"pita atas mati: variasi cuma {result.top_band_std_db:.1f} dB, "
            f"{result.top_band_gap_db:.0f} dB di bawah pita tengah")

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
