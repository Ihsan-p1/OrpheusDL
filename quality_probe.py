"""Pengukuran kualitas audio yang bisa diulang.

Modul ini tidak mengeluarkan verdict. Ia melaporkan angka yang bisa diukur
ulang dengan hasil sama, dan diam untuk hal yang tidak bisa dibuktikan.
"""
from __future__ import annotations

import numpy as np
import soundfile as sf

CLIFF_MIN_DROP_DB = 30.0
CLIFF_SPAN_HZ = 1000.0
CLIFF_RECOVERY_DB = 5.0
CLIFF_SUSPECT_MAX_HZ = 19000.0
SMOOTH_HZ = 200.0
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
    """
    bin_hz = float(freqs[1] - freqs[0])
    span = max(1, int(span_hz / bin_hz))
    smooth = smooth_spectrum(freqs, db)
    drops = smooth[:-span] - smooth[span:]
    for i in np.flatnonzero(drops >= min_drop_db):
        tail = smooth[i + span:]
        if float(np.median(tail)) <= float(smooth[i + span]) + CLIFF_RECOVERY_DB:
            return float(freqs[i]), float(drops[i])
    return None, None
