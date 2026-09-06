"""Repeatable audio quality measurements.

This module hands down no verdict. It reports numbers that measure the same on
every run, and stays quiet about anything it cannot prove.
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
    median = np.median(np.vstack(spectra), axis=0)
    return freqs, median - median.max(), sr


def smooth_spectrum(freqs: np.ndarray, db: np.ndarray,
                    width_hz: float = SMOOTH_HZ) -> np.ndarray:
    """Smooth the spectrum along the frequency axis.

    One FFT bin here is a fraction of a hertz wide and its value jumps tens of
    dB from bin to bin. Without smoothing, a random dip reads as an encoder
    cliff. The edges are padded with their own edge value so the highest band,
    the one that matters most here, is not dragged down.
    """
    bin_hz = float(freqs[1] - freqs[0])
    width = max(1, int(width_hz / bin_hz))
    kernel = np.ones(width) / width
    padded = np.pad(db, width, mode="edge")
    return np.convolve(padded, kernel, mode="same")[width:width + len(db)]


def find_lowpass_cliff(freqs: np.ndarray, db: np.ndarray,
                       min_drop_db: float = CLIFF_MIN_DROP_DB,
                       span_hz: float = CLIFF_SPAN_HZ) -> tuple[float | None, float | None]:
    """Find the encoder cliff: energy drops hard and never comes back.

    The second condition is what separates a cliff from an ordinary rolloff. A
    genuine recording may well be quiet up high, but it fades gently and its
    energy still moves up there. An encoder cuts, and after that there is
    nothing at all.

    Cliffs below CLIFF_MIN_HZ are ignored. No encoder cuts down there, so a
    drop that steep comes from the recording's own content, usually a piano or
    another solo instrument whose spectrum is simply empty.

    Third condition: the band above the cliff has to be dead, not merely quiet.
    An encoder writes zeroes there, so its variation stays under a dB. A
    natural rolloff diving toward Nyquist also drops 30 dB inside a kilohertz
    and also never recovers, but its content still moves 7 to 21 dB. Without
    this condition, 159 files with an ordinary rolloff at 20.5 kHz read as
    having an encoder cliff.
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
    """Measure how alive the top frequency band is next to a middle band.

    A genuine recording has a noise floor that moves up there even when the
    content is very quiet. An encoder that cuts leaves a band that is flat,
    with no movement at all. What tells them apart is not how quiet it is but
    whether anything varies.

    Returns (top band standard deviation, gap to the middle band) in dB.
    """
    nyquist = float(freqs[-1])
    top = db[(freqs >= DEAD_BAND_RANGE[0] * nyquist) & (freqs <= DEAD_BAND_RANGE[1] * nyquist)]
    mid = db[(freqs >= REFERENCE_BAND_RANGE[0] * nyquist)
             & (freqs <= REFERENCE_BAND_RANGE[1] * nyquist)]
    if top.size < 2 or mid.size < 2:
        return None, None
    return float(top.std()), float(np.median(mid) - np.median(top))


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
        # libsndfile refuses formats it has not implemented (32-bit FLAC, for
        # one) with a read error shaped exactly like the one a truncated file
        # gives. The first is not damage: the file is whole, only unmeasurable
        # here.
        if "unimplemented format" in str(e).lower():
            return ProbeResult(status="unknown", error=str(e))
        return ProbeResult(status="corrupt", error=str(e))

    result.sample_rate = sr
    result.cutoff_hz, result.cutoff_drop_db = find_lowpass_cliff(freqs, db)

    audible = np.where(db >= -80.0)[0]
    result.highest_energy_hz = float(freqs[audible[-1]]) if len(audible) else 0.0
    result.top_band_std_db, result.top_band_gap_db = dead_band(freqs, db)

    try:
        result.declared_bit_depth, result.effective_bit_depth = bit_depths(path)
    except Exception as e:
        result.error = f"bit depth unreadable: {e}"

    if result.cutoff_hz is not None and result.cutoff_hz < CLIFF_SUSPECT_MAX_HZ:
        result.reasons.append(
            f"lowpass cliff {result.cutoff_hz / 1000:.1f} kHz "
            f"dropping {result.cutoff_drop_db:.0f} dB")

    if (result.top_band_std_db is not None
            and result.top_band_std_db < DEAD_BAND_MAX_STD_DB
            and result.top_band_gap_db >= DEAD_BAND_MIN_GAP_DB):
        result.reasons.append(
            f"dead top band: only {result.top_band_std_db:.1f} dB of variation, "
            f"{result.top_band_gap_db:.0f} dB below the middle band")

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
