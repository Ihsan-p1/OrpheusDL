#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import sys
import io

# Fix Windows terminal encoding
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

"""
+===========================================================================+
|                     ORPHEUS HEALER  v2.1                                  |
|  Auto-detect, redownload (multi-source), and verify FLAC quality          |
+===========================================================================+

Cara Pakai:
  1. Edit healer_config.toml sesuai path kamu
  2. Export laporan Soniq Tools ke CSV (File -> Export -> CSV)
  3. Jalankan: python orpheus_healer.py
  4. Tinjau preview duplicate, lalu pilih mode: Auto / Interactive

Workflow:
  CSV Soniq -> Parse -> [DUPLICATE CHECK] -> Match file -> Backup
           -> Multi-source DL -> Verify -> Report

Fixes v2.1 (on top of v2.0):
  [FIX-F2]  Bare except -> semua pakai except Exception as e dengan logging
  [FIX-F3]  isinstance check yang benar (bukan 'is list')
  [FIX-F8]  Mutable default args {} -> pakai None default
  [FIX-F9]  is_truly_lossless verdict matching yang benar
  [FIX-M3]  File handle leaks -> semua pakai 'with open(...) as f:'
  [FIX-M5]  sys.exit() bukan exit() untuk production code
  [NEW-DUP] Duplicate detection dengan preview & user confirmation
  [NEW-DUP] Penanganan cerdas: keep versi terbaik, backup/hapus duplikat
"""

import os
import re
import csv
import time
import json
import shutil
import logging
import argparse
import subprocess
from pathlib import Path
from datetime import datetime
from difflib import SequenceMatcher
from logging.handlers import RotatingFileHandler

# ── Fallback tomllib for Python < 3.11 ───────────────────────────────────────
try:
    import tomllib
except ImportError:
    import tomli as tomllib

# ── Optional: spectral analysis libraries ────────────────────────────────────
try:
    import numpy as np
    import soundfile as sf
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False

try:
    from mutagen.flac import FLAC as MutagenFLAC
    MUTAGEN_AVAILABLE = True
except ImportError:
    MUTAGEN_AVAILABLE = False

# ── Optional: desktop notification ───────────────────────────────────────────
try:
    # pyrefly: ignore [missing-import]
    from plyer import notification as plyer_notification
    
    PLYER_AVAILABLE = True
except ImportError:
    PLYER_AVAILABLE = False
# ═══════════════════════════════════════════════════════════════════════════
#  [M6] CONFIG LOADING FROM healer_config.toml
# ═══════════════════════════════════════════════════════════════════════════

CONFIG_FILE     = Path(__file__).parent / "healer_config.toml"
CHECKPOINT_FILE = Path(__file__).parent / "healer_checkpoint.json"

_DEFAULT_CONFIG = {
    "paths": {
        "soniq_csv":     r"D:\College Project\music\OrpheusDL-master\soniqtools-batch-2026-07-01.csv",
        "music_folder":  r"D:\Music\New folder (2)\Mix\MIXING",
        "orpheus_dir":   r"D:\College Project\music\OrpheusDL-master",
        "backup_folder": r"D:\Music\New folder (2)\Mix\MIXING\_FAKE_BACKUP",
        "log_file":      "orpheus_healer_log.txt",
    },
    "settings": {
        "delay_between_downloads": 3,
        "delete_fake_files": False,
        "bad_verdicts": ["Upsampled / Transcoded", "Lossy Transcode", "Low-Bitrate Lossy", "Error"],
        "preserve_tags": [
            "comment", "rating", "fmps_rating", "fmps_playcount",
            "replaygain_track_gain", "replaygain_track_peak",
            "replaygain_album_gain", "replaygain_album_peak",
            "lyrics", "musicbrainz_trackid",
        ],
    },
    "source_priority": [
        {"module": "tidal",       "label": "Tidal HiFi",     "enabled": True},
        {"module": "qobuz",       "label": "Qobuz",           "enabled": False},
        {"module": "deezer",      "label": "Deezer HiFi",     "enabled": False},
        {"module": "applemusic",  "label": "Apple Music",     "enabled": False},
        {"module": "amazon",      "label": "Amazon Music HD", "enabled": False},
    ],
    "quality_score": {
        "True High-Resolution Audio":          120,
        "Standard Quality (CD / Near-CD)":     100,
        "Natural Rolloff (Vintage Recording)":  95,
        "Possibly Upsampled":                   70,
        "Upsampled / Transcoded":               40,
        "Lossy Transcode":                      20,
        "Unknown":                              10,
        "Error":                                 0,
    },
}


def load_config() -> dict:
    """[M6] Load config dari healer_config.toml, fallback ke default."""
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "rb") as f:   # [FIX-M3]
                toml = tomllib.load(f)
            cfg = {
                "paths":           {**_DEFAULT_CONFIG["paths"],    **toml.get("paths", {})},
                "settings":        {**_DEFAULT_CONFIG["settings"], **toml.get("settings", {})},
                "source_priority": toml.get("source_priority", _DEFAULT_CONFIG["source_priority"]),
                "quality_score":   {**_DEFAULT_CONFIG["quality_score"], **toml.get("quality_score", {})},
            }
            return cfg
        except Exception as e:   # [FIX-F2]
            print(f"[WARN] Gagal load healer_config.toml: {e}. Pakai built-in default.")
    else:
        print(f"[INFO] healer_config.toml tidak ditemukan. Pakai built-in default.")
        print(f"       Tip: edit healer_config.toml untuk konfigurasi tanpa edit kode.\n")
    return {
        k: (v.copy() if isinstance(v, dict) else list(v) if isinstance(v, list) else v)
        for k, v in _DEFAULT_CONFIG.items()
    }


CONFIG = load_config()


# ═══════════════════════════════════════════════════════════════════════════
#  TERMINAL COLORS
# ═══════════════════════════════════════════════════════════════════════════

class C:
    RED    = "\033[91m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    CYAN   = "\033[96m"
    WHITE  = "\033[97m"
    BOLD   = "\033[1m"
    RESET  = "\033[0m"


# ═══════════════════════════════════════════════════════════════════════════
#  [S8] LOGGING WITH ROTATION
# ═══════════════════════════════════════════════════════════════════════════

log = logging.getLogger("OrpheusHealer")
log.setLevel(logging.DEBUG)

_log_path = CONFIG["paths"]["log_file"]
_fh = RotatingFileHandler(_log_path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
_fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
_fh.setLevel(logging.DEBUG)

_ch = logging.StreamHandler(sys.stdout)
_ch.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
_ch.setLevel(logging.INFO)

log.addHandler(_fh)
log.addHandler(_ch)


# ═══════════════════════════════════════════════════════════════════════════
#  BANNER
# ═══════════════════════════════════════════════════════════════════════════

def print_banner() -> None:
    enabled_sources = [s["label"] for s in CONFIG["source_priority"] if s.get("enabled")]
    src_str = " -> ".join(enabled_sources) if enabled_sources else "NONE (edit healer_config.toml!)"
    banner = f"""
{C.CYAN}{C.BOLD}
+===========================================================================+
|                     ORPHEUS HEALER  v2.1                                  |
|  Duplicate detect | Snapshot detect | Vintage fix | Multi-source fallback |
+===========================================================================+
  Sources : {src_str}
  Config  : {"healer_config.toml" if CONFIG_FILE.exists() else "built-in default"}
  numpy   : {"OK" if NUMPY_AVAILABLE else "MISSING (pip install numpy soundfile)"}
  mutagen : {"OK" if MUTAGEN_AVAILABLE else "MISSING (pip install mutagen)"}
{C.RESET}"""
    print(banner)


# ═══════════════════════════════════════════════════════════════════════════
#  [S11] CSV VALIDATION + STEP 1: PARSE SONIQ CSV
# ═══════════════════════════════════════════════════════════════════════════

REQUIRED_CSV_COLUMNS = {"File", "Verdict"}


def validate_csv_columns(csv_path: str) -> tuple[bool, list[str]]:
    """[S11] Validasi apakah CSV punya kolom yang diperlukan."""
    try:
        with open(csv_path, encoding="utf-8-sig", errors="replace") as f:   # [FIX-M3]
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                return False, ["CSV kosong atau tidak valid"]
            actual  = set(reader.fieldnames)
            missing = REQUIRED_CSV_COLUMNS - actual
            if missing:
                return False, [
                    f"Kolom tidak ditemukan: {', '.join(missing)}",
                    f"Kolom yang ada: {', '.join(actual)}",
                    "Pastikan export dari Soniq Tools format CSV yang benar.",
                ]
            return True, []
    except FileNotFoundError:
        return False, [f"File tidak ditemukan: {csv_path}"]
    except Exception as e:   # [FIX-F2]
        return False, [str(e)]


def _parse_filename(filepath: str) -> tuple[str, list[str]]:
    """Extract title dan artists dari path/nama file."""
    stem = Path(filepath).stem
    stem = re.sub(r"^\d+[\.\s]+", "", stem).strip()
    if " - " in stem:
        parts       = stem.split(" - ", 1)
        artists_raw = parts[0].strip()
        title       = parts[1].strip()
        artists     = [a.strip() for a in re.split(r"[;,&_]", artists_raw) if a.strip()]
    else:
        title   = stem
        artists = []
    return title, artists


def parse_soniq_csv(csv_path: str, bad_verdicts: list[str]) -> list[dict]:
    """[S11] Parse CSV Soniq Tools dan kembalikan daftar track bermasalah."""
    valid, errors = validate_csv_columns(csv_path)
    if not valid:
        for e in errors:
            log.error(f"[CSV] {e}")
        return []

    bad_tracks = []
    log.info(f"Membaca laporan Soniq Tools: {csv_path}")

    with open(csv_path, encoding="utf-8-sig", errors="replace") as f:   # [FIX-M3]
        reader     = csv.DictReader(f)
        fieldnames = [fn.strip() for fn in (reader.fieldnames or [])]

        sr_col  = next((c for c in fieldnames if "sample rate" in c.lower()), None)
        bd_col  = next((c for c in fieldnames if "bit depth"   in c.lower()), None)
        co_col  = next((c for c in fieldnames if "cutoff"      in c.lower()), None)
        bw_col  = next((c for c in fieldnames if "bandwidth"   in c.lower()), None)
        fmt_col = next((c for c in fieldnames if "format"      in c.lower()), None)
        dur_col = next((c for c in fieldnames if "duration"    in c.lower()), None)

        for row in reader:
            verdict = row.get("Verdict", "").strip()
            if not any(bv.lower() in verdict.lower() for bv in bad_verdicts):
                continue

            filepath = row.get("File", "").strip()
            filename = Path(filepath).name if filepath else ""
            fmt      = row.get(fmt_col, "").strip().upper() if fmt_col else ""
            title, artists = _parse_filename(filepath)
            duration_str   = row.get(dur_col, "").strip() if dur_col else ""

            def _safe_float(val, default=None):
                try:
                    return float(str(val).replace(",", ".").strip()) if val else default
                except (ValueError, TypeError):
                    return default

            track = {
                "filename":      filename,
                "filepath_csv":  filepath,
                "title":         title,
                "artists":       artists,
                "verdict":       verdict,
                "format":        fmt,
                "sample_rate":   row.get(sr_col, "").strip() if sr_col else None,
                "bit_depth":     row.get(bd_col, "").strip() if bd_col else None,
                "cutoff":        _safe_float(row.get(co_col, "")) if co_col else None,
                "bandwidth":     _safe_float(row.get(bw_col, "")) if bw_col else None,
                "duration":      duration_str,
                "file_path":     None,
            }
            bad_tracks.append(track)

    lossy_tracks = [t for t in bad_tracks if t["format"] not in ("FLAC", "")]
    if lossy_tracks:
        log.info(f"  [CSV] {len(lossy_tracks)} file non-FLAC — akan di-redownload sebagai FLAC")
    log.info(f"Ditemukan {len(bad_tracks)} track bermasalah dari {len(bad_verdicts)} verdict category.")
    return bad_tracks


# ═══════════════════════════════════════════════════════════════════════════
#  [NEW-DUP] DUPLICATE DETECTION & USER CONFIRMATION
# ═══════════════════════════════════════════════════════════════════════════

# Quality score untuk memilih versi terbaik dari duplicate group
_VERDICT_SCORE: dict[str, int] = {
    "True High-Resolution Audio":          120,
    "Standard Quality (CD / Near-CD)":     100,
    "Natural Rolloff (Vintage Recording)":  95,
    "Possibly Upsampled":                   70,
    "Upsampled / Transcoded":               40,
    "Lossy Transcode":                      20,
    "Low-Bitrate Lossy":                    10,
    "Error":                                 0,
}

# Regex untuk marker yang menandai "versi cadangan" di nama file
_DUP_MARKER_RE = re.compile(
    r"\s*\(High\)\s*"
    r"|\s*\[REAL\s*\d+\]\s*"
    r"|\s*\(\d+\)\s*"
    r"|\s*\[CORRUPTED\]\s*"
    r"|\s*\(High\)\s*\(\d+\)\s*",
    re.IGNORECASE,
)


def _normalize_for_dedup(filename: str) -> str:
    """
    Normalisasi nama file untuk pendeteksian duplikat.
    Hapus extension, marker duplikat, normalize whitespace & case.
    """
    stem       = Path(filename).stem
    normalized = _DUP_MARKER_RE.sub(" ", stem)
    normalized = re.sub(r"\s{2,}", " ", normalized).strip().lower()
    # Normalize separator variants
    normalized = re.sub(r"[·•∶]", "-", normalized)
    normalized = re.sub(r"[^\x20-\x7E\u00C0-\u024F\u4E00-\u9FFF\u3000-\u303F\u3040-\u30FF]",
                        "", normalized)
    return re.sub(r"\s{2,}", " ", normalized).strip()


def _get_verdict_score(verdict: str) -> int:
    """Ambil skor kualitas dari verdict string."""
    for key, score in _VERDICT_SCORE.items():
        if key.lower() in verdict.lower():
            return score
    return -1


def _parse_bw(bw_val) -> float:
    if bw_val is None:
        return 0.0
    try:
        return float(str(bw_val).replace("%", "").strip())
    except (ValueError, TypeError):
        return 0.0


def _parse_bd(bd_val) -> int:
    if bd_val is None:
        return 0
    try:
        parts = str(bd_val).replace("-bit", "").replace("bit", "").strip().split()
        return int(parts[0]) if parts else 0
    except (ValueError, TypeError):
        return 0


def _parse_sr(sr_val) -> float:
    if sr_val is None:
        return 0.0
    try:
        return float(str(sr_val).replace("kHz", "").replace("khz", "").strip())
    except (ValueError, TypeError):
        return 0.0


def detect_duplicates_from_csv(all_rows: list[dict]) -> list[list[dict]]:
    """
    [NEW-DUP] Deteksi grup duplikat dari SEMUA baris CSV.
    Returns: list of groups, setiap group berisi >= 2 baris dict.
    """
    groups: dict[str, list[dict]] = {}
    for row in all_rows:
        key = _normalize_for_dedup(row.get("filename", ""))
        if not key:
            continue
        groups.setdefault(key, []).append(row)
    return [rows for rows in groups.values() if len(rows) > 1]


def _pick_best_in_group(group: list[dict]) -> dict:
    """
    Pilih entri terbaik dari satu grup duplikat.
    Prioritas: verdict score -> bandwidth -> bit depth
    """
    def _sort_key(entry):
        vs = _get_verdict_score(entry.get("verdict", ""))
        bw = _parse_bw(entry.get("bandwidth"))
        bd = _parse_bd(entry.get("bit_depth"))
        sr = _parse_sr(entry.get("sample_rate"))
        # Slight bonus for CD-standard 44.1 vs potentially-upsampled hi-res
        sr_bonus = 0.5 if abs(sr - 44.1) < 0.5 else 0.0
        return (vs, bw, bd, sr_bonus)

    return max(group, key=_sort_key)


def _colorize_verdict(verdict: str) -> str:
    if any(v in verdict for v in ["Lossy", "Upsampled", "Error", "Low-Bitrate"]):
        return f"{C.RED}{verdict}{C.RESET}"
    elif "Possibly" in verdict:
        return f"{C.YELLOW}{verdict}{C.RESET}"
    elif "Standard" in verdict or "Natural" in verdict:
        return f"{C.GREEN}{verdict}{C.RESET}"
    elif "True High" in verdict:
        return f"{C.CYAN}{verdict}{C.RESET}"
    return verdict


def show_duplicate_preview(dup_groups: list[list[dict]]) -> str:
    """
    [NEW-DUP] Tampilkan preview semua duplikat, minta konfirmasi user.
    Returns: 'Y' (auto semua), 'I' (interaktif per-grup), 'S' (skip).
    """
    total_to_remove = sum(len(g) - 1 for g in dup_groups)

    print(f"\n{C.BOLD}{C.CYAN}{'=' * 70}")
    print(f"  [DUPLICATE SCAN] Ditemukan {len(dup_groups)} grup duplikat")
    print(f"  Total file berlebih yang akan diproses: {total_to_remove} file")
    print(f"{'=' * 70}{C.RESET}")
    print(f"\n  {C.YELLOW}Keterangan:{C.RESET}")
    print(f"  File dengan marker (High), [REAL 320], (1), (2), [CORRUPTED] dianggap duplikat.")
    print(f"  {C.GREEN}[KEEP]  {C.RESET} = versi terbaik yang dipertahankan")
    print(f"  {C.RED}[REMOVE]{C.RESET} = duplikat yang akan di-backup/hapus")
    print()

    # Batasi preview max 50 grup agar tidak banjir terminal
    preview_limit = 50
    for idx, group in enumerate(dup_groups[:preview_limit], 1):
        best = _pick_best_in_group(group)
        print(f"  {C.BOLD}Grup {idx}/{len(dup_groups)}:{C.RESET}")
        for entry in sorted(group, key=lambda e: e.get("filename", "")):
            is_best = (entry is best)
            marker  = f"{C.GREEN}[KEEP]  {C.RESET}" if is_best else f"{C.RED}[REMOVE]{C.RESET}"
            fname   = entry.get("filename", "?")
            verdict = _colorize_verdict(entry.get("verdict", "?"))
            sr      = entry.get("sample_rate", "?")
            bd      = entry.get("bit_depth", "?")
            bw      = entry.get("bandwidth", "?")
            print(f"    {marker} {fname}")
            print(f"             Verdict: {verdict} | {sr} | {bd} | BW: {bw}%")
        print()

    if len(dup_groups) > preview_limit:
        print(f"  {C.YELLOW}... dan {len(dup_groups) - preview_limit} grup lainnya (tidak ditampilkan).{C.RESET}\n")

    print(f"{C.BOLD}{'─' * 70}{C.RESET}")
    delete_mode = CONFIG["settings"]["delete_fake_files"]
    action_word = "DIHAPUS PERMANEN" if delete_mode else "di-backup ke folder backup"
    print(f"  {C.YELLOW}File [REMOVE] akan {action_word}.{C.RESET}")
    if not delete_mode:
        print(f"  Backup folder: {CONFIG['paths']['backup_folder']}")
    print()

    while True:
        choice = input(
            f"  Lanjutkan pembersihan duplikat? "
            f"[{C.GREEN}Y{C.RESET}=Auto semua / "
            f"{C.CYAN}I{C.RESET}=Interaktif per-grup / "
            f"{C.YELLOW}S{C.RESET}=Skip / "
            f"{C.RED}Q{C.RESET}=Quit]: "
        ).strip().upper()
        if choice in ("Y", ""):
            return "Y"
        elif choice == "I":
            log.info("[DUP] Mode interaktif per-grup dipilih.")
            return "I"
        elif choice == "S":
            log.info("[DUP] User memilih skip pembersihan duplikat.")
            return "S"
        elif choice == "Q":
            log.info("[DUP] User memilih quit.")
            sys.exit(0)   # [FIX-M5]
        else:
            print(f"  {C.YELLOW}Masukkan Y, I, S, atau Q.{C.RESET}")


def _interactive_group_pick(group: list[dict], auto_best: dict, idx: int, total: int) -> dict | None:
    """
    [NEW-DUP-I] Tampilkan satu grup dan beri user pilihan:
      - Enter / A : konfirmasi auto-pick
      - 1..N      : override, pilih nomor yang di-KEEP
      - S         : skip grup ini (tidak hapus apa-apa)
      - Q         : quit
    Returns dict entry yang akan di-KEEP, atau None jika grup di-skip.
    """
    sorted_entries = sorted(group, key=lambda e: e.get("filename", ""))
    auto_idx       = sorted_entries.index(auto_best) + 1  # 1-based

    print(f"\n  {C.BOLD}{'─' * 66}{C.RESET}")
    print(f"  {C.BOLD}Grup {idx}/{total}{C.RESET}  "
          f"(auto-pilih: [{C.GREEN}{auto_idx}{C.RESET}])")
    for i, entry in enumerate(sorted_entries, 1):
        is_auto = (entry is auto_best)
        star    = f"{C.GREEN}★{C.RESET}" if is_auto else " "
        fname   = entry.get("filename", "?")
        verdict = _colorize_verdict(entry.get("verdict", "?"))
        sr      = entry.get("sample_rate", "?")
        bd      = entry.get("bit_depth", "?")
        bw      = entry.get("bandwidth", "?")
        print(f"  {C.BOLD}[{i}]{C.RESET} {star} {fname}")
        print(f"       Verdict: {verdict} | {sr} | {bd} | BW: {bw}%")

    valid_nums = set(str(i) for i in range(1, len(sorted_entries) + 1))
    while True:
        raw = input(
            f"  [{C.GREEN}Enter/A{C.RESET}]=Auto [{C.CYAN}1-{len(sorted_entries)}{C.RESET}]=Override "
            f"[{C.YELLOW}S{C.RESET}]=Skip grup [{C.RED}Q{C.RESET}]=Quit: "
        ).strip().upper()
        if raw in ("", "A"):
            return auto_best
        elif raw in valid_nums:
            chosen = sorted_entries[int(raw) - 1]
            if chosen is auto_best:
                print(f"  {C.GREEN}(Sama dengan auto-pick.){C.RESET}")
            else:
                print(f"  {C.CYAN}[OVERRIDE]{C.RESET} KEEP: {chosen['filename']}")
            return chosen
        elif raw == "S":
            print(f"  {C.YELLOW}[SKIP] Grup ini dilewati.{C.RESET}")
            return None
        elif raw == "Q":
            log.info("[DUP] User quit dari mode interaktif.")
            sys.exit(0)   # [FIX-M5]
        else:
            print(f"  {C.YELLOW}Masukkan angka 1-{len(sorted_entries)}, A, S, atau Q.{C.RESET}")


def _move_or_delete_file(file_path: str, delete: bool, backup_folder: str) -> bool:
    """Backup atau hapus satu file. Returns True jika berhasil."""
    if not file_path or not os.path.exists(file_path):
        return True  # Tidak ada yang perlu dilakukan

    if delete:
        try:
            os.remove(file_path)
            log.info(f"  [DUP-DEL] Dihapus: {os.path.basename(file_path)}")
            return True
        except Exception as e:   # [FIX-F2]
            log.error(f"  [DUP-ERR] Gagal hapus {os.path.basename(file_path)}: {e}")
            return False
    else:
        try:
            os.makedirs(backup_folder, exist_ok=True)
            dest = os.path.join(backup_folder, os.path.basename(file_path))
            if os.path.exists(dest):
                ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
                stem = Path(file_path).stem
                dest = os.path.join(backup_folder, f"{stem}_{ts}.flac")
            shutil.move(file_path, dest)
            log.info(f"  [DUP-BCK] Di-backup: {os.path.basename(dest)}")
            return True
        except Exception as e:   # [FIX-F2]
            log.error(f"  [DUP-ERR] Gagal backup {os.path.basename(file_path)}: {e}")
            return False


def parse_full_csv(csv_path: str) -> list[dict]:
    """
    [NEW-DUP] Baca SEMUA baris CSV untuk keperluan duplicate detection.
    (Berbeda dengan parse_soniq_csv yang hanya filter bad verdicts.)
    """
    rows = []
    try:
        with open(csv_path, encoding="utf-8-sig", errors="replace") as f:   # [FIX-M3]
            reader     = csv.DictReader(f)
            fieldnames = [fn.strip() for fn in (reader.fieldnames or [])]
            sr_col  = next((c for c in fieldnames if "sample rate" in c.lower()), None)
            bd_col  = next((c for c in fieldnames if "bit depth"   in c.lower()), None)
            bw_col  = next((c for c in fieldnames if "bandwidth"   in c.lower()), None)
            fmt_col = next((c for c in fieldnames if "format"      in c.lower()), None)
            dur_col = next((c for c in fieldnames if "duration"    in c.lower()), None)

            for row in reader:
                filepath = row.get("File", "").strip()
                filename = Path(filepath).name if filepath else ""
                if not filename:
                    continue

                def _sf(val, default=None):
                    try:
                        return float(str(val).replace(",", ".").strip()) if val else default
                    except (ValueError, TypeError):
                        return default

                rows.append({
                    "filename":     filename,
                    "filepath_csv": filepath,
                    "verdict":      row.get("Verdict", "").strip(),
                    "format":       row.get(fmt_col, "").strip().upper() if fmt_col else "",
                    "sample_rate":  row.get(sr_col, "").strip() if sr_col else None,
                    "bit_depth":    row.get(bd_col, "").strip() if bd_col else None,
                    "bandwidth":    _sf(row.get(bw_col, "")) if bw_col else None,
                    "duration":     row.get(dur_col, "").strip() if dur_col else "",
                })
    except Exception as e:   # [FIX-F2]
        log.error(f"[CSV] Gagal membaca full CSV: {e}")
    return rows


def _resolve_disk_path(fname: str, all_flacs: dict[str, str]) -> str | None:
    """Exact match lalu fuzzy fallback >= 90% untuk cari file di disk."""
    if fname in all_flacs:
        return all_flacs[fname]
    best_score, best_path = 0.0, None
    for dname, dp in all_flacs.items():
        score = SequenceMatcher(None, fname.lower(), dname.lower()).ratio()
        if score > best_score:
            best_score, best_path = score, dp
    if best_score >= 0.90:
        log.debug(f"  [DUP-FUZZY] {fname} -> {Path(best_path).name} ({best_score:.0%})")
        return best_path
    return None


def run_duplicate_check(csv_path: str, music_folder: str,
                        backup_folder: str, delete: bool) -> dict:
    """
    [NEW-DUP] Entry point: parse full CSV -> detect dups -> preview -> handle.
    Mode 'Y': auto semua. Mode 'I': interaktif per-grup (user bisa override KEEP).
    """
    log.info("[DUP] Memulai duplicate detection dari CSV...")
    all_rows   = parse_full_csv(csv_path)
    dup_groups = detect_duplicates_from_csv(all_rows)

    if not dup_groups:
        print(f"\n  {C.GREEN}[DUP] Tidak ada duplikat terdeteksi. Library bersih!{C.RESET}\n")
        return {"groups": 0, "removed": 0, "skipped": 0, "errors": 0}

    mode = show_duplicate_preview(dup_groups)   # "Y" | "I" | "S"
    if mode == "S":
        return {"groups": len(dup_groups), "removed": 0,
                "skipped": len(dup_groups), "errors": 0}

    # Index semua FLAC di disk
    log.info(f"[DUP] Indexing FLAC di: {music_folder}")
    all_flacs: dict[str, str] = {}
    if os.path.exists(music_folder):
        for p in Path(music_folder).rglob("*.flac"):
            all_flacs[p.name] = str(p)
    log.info(f"[DUP] {len(all_flacs)} FLAC ditemukan di disk.")

    removed_count = 0
    skipped_count = 0
    error_count   = 0
    total         = len(dup_groups)

    if mode == "Y":
        print(f"\n{C.BOLD}[DUP] Auto-mode: memproses {total} grup...{C.RESET}\n")
    else:
        print(f"\n{C.BOLD}[DUP] Interaktif-mode: {total} grup "
              f"(Enter=auto, angka=override, S=skip, Q=quit){C.RESET}")

    for idx, group in enumerate(dup_groups, 1):
        auto_best = _pick_best_in_group(group)

        if mode == "I":
            chosen_best = _interactive_group_pick(group, auto_best, idx, total)
            if chosen_best is None:           # user pilih S = skip grup
                skipped_count += len(group) - 1
                continue
        else:
            chosen_best = auto_best

        to_remove = [e for e in group if e is not chosen_best]

        if mode == "Y":
            print(f"  Grup {idx}/{total}: "
                  f"KEEP -> {C.GREEN}{chosen_best['filename']}{C.RESET}")

        for entry in to_remove:
            fname     = entry.get("filename", "")
            disk_path = _resolve_disk_path(fname, all_flacs)

            if disk_path:
                ok = _move_or_delete_file(disk_path, delete, backup_folder)
                if ok:
                    removed_count += 1
                    action = "Dihapus" if delete else "Di-backup"
                    print(f"    {C.RED}[REMOVE]{C.RESET} {fname} -> {action}")
                else:
                    error_count += 1
                    print(f"    {C.YELLOW}[WARN]{C.RESET} Gagal proses: {fname}")
            else:
                skipped_count += 1
                print(f"    {C.YELLOW}[SKIP]{C.RESET} Tidak ditemukan di disk: {fname}")

    print()
    log.info(f"[DUP] Selesai: {removed_count} removed, "
             f"{skipped_count} skip, {error_count} errors")
    return {
        "groups":  total,
        "removed": removed_count,
        "skipped": skipped_count,
        "errors":  error_count,
    }


# ═══════════════════════════════════════════════════════════════════════════
#  STEP 2: LOCATE FILES ON DISK
# ═══════════════════════════════════════════════════════════════════════════

def locate_files(bad_tracks: list[dict], music_folder: str) -> list[dict]:
    """Cari lokasi file di disk. Exact match dulu, lalu fuzzy >= 85%."""
    if not os.path.exists(music_folder):
        log.warning(f"[SCAN] Folder musik tidak ditemukan: {music_folder}")
        return bad_tracks

    log.info(f"[SCAN] Indexing FLAC di: {music_folder}")
    all_flacs = {p.name: str(p) for p in Path(music_folder).rglob("*.flac")}
    log.info(f"[SCAN] {len(all_flacs)} FLAC ditemukan di disk.")

    found = 0
    for track in bad_tracks:
        fname = track["filename"]
        if fname in all_flacs:
            track["file_path"] = all_flacs[fname]
            found += 1
            continue
        best_score, best_path = 0.0, None
        for disk_name, disk_path in all_flacs.items():
            score = SequenceMatcher(None, fname.lower(), disk_name.lower()).ratio()
            if score > best_score:
                best_score, best_path = score, disk_path
        if best_score >= 0.85:
            track["file_path"] = best_path
            log.debug(f"  [FUZZY] {fname} -> {Path(best_path).name} ({best_score:.0%})")
            found += 1

    log.info(f"[SCAN] {found}/{len(bad_tracks)} track ditemukan di disk.")
    return bad_tracks


# ═══════════════════════════════════════════════════════════════════════════
#  STEP 3: METADATA PRESERVATION
# ═══════════════════════════════════════════════════════════════════════════

def extract_custom_tags(file_path: str, preserve_tags: list[str]) -> dict:
    """[M5] Baca custom tags sebelum file di-backup/hapus."""
    if not MUTAGEN_AVAILABLE or not file_path or not os.path.exists(file_path):
        return {}
    try:
        flac = MutagenFLAC(file_path)
        if not flac.tags:
            return {}
        tags      = {}
        lower_set = {p.lower() for p in preserve_tags}
        for key, val in flac.tags.items():
            if key.lower() in lower_set:
                tags[key] = (list(val)
                             if hasattr(val, "__iter__") and not isinstance(val, str)
                             else val)
        if tags:
            log.debug(f"  [META] Preserved {len(tags)} tags: {list(tags.keys())}")
        return tags
    except Exception as e:   # [FIX-F2]
        log.debug(f"  [META] Gagal baca tags: {e}")
        return {}


def apply_custom_tags(file_path: str, tags: dict) -> bool:
    """[M5] Terapkan custom tags yang tersimpan ke file baru."""
    if not MUTAGEN_AVAILABLE or not tags or not os.path.exists(file_path):
        return False
    try:
        flac = MutagenFLAC(file_path)
        if flac.tags is None:
            flac.add_tags()
        for key, val in tags.items():
            flac.tags[key] = val
        flac.save()
        log.debug(f"  [META] Applied {len(tags)} preserved tags.")
        return True
    except Exception as e:   # [FIX-F2]
        log.warning(f"  [META] Gagal apply tags: {e}")
        return False


def handle_fake_file(track: dict, delete: bool, backup_folder: str) -> bool:
    """Backup atau hapus file fake sebelum redownload."""
    file_path = track.get("file_path")
    return _move_or_delete_file(file_path or "", delete, backup_folder)


# ═══════════════════════════════════════════════════════════════════════════
#  [C2] STEP 3b: BUILT-IN FLAC SPECTRAL ANALYZER
# ═══════════════════════════════════════════════════════════════════════════

_THRESHOLDS = {
    "standard_bw_min":       92.0,
    "borderline_bw_min":     72.0,
    "lossy_slope_threshold": -4.5,
    "upsampled_bw_max":      62.0,
    "hires_cutoff_min":      24000,
}


def _compute_rolloff_slope(fft_db: "np.ndarray", freqs: "np.ndarray",
                            f_low: float, f_high: float) -> float:
    """Hitung rata-rata slope (dB/kHz) di range frekuensi tertentu."""
    mask    = (freqs >= f_low) & (freqs <= f_high)
    f_range = freqs[mask]
    db_range = fft_db[mask]
    if len(f_range) < 2:
        return 0.0
    x = f_range / 1000.0
    y = db_range
    n = len(x)
    denom = n * (x**2).sum() - x.sum()**2
    if abs(denom) < 1e-9:
        return 0.0
    return float((n * (x * y).sum() - x.sum() * y.sum()) / denom)


def analyze_flac_quality(file_path: str, n_samples: int = 131072) -> dict:
    """[C2] Analisis kualitas FLAC via FFT spectral + rolloff slope."""
    result = {
        "verdict":       "Unknown",
        "cutoff_hz":     None,
        "bandwidth_pct": None,
        "sample_rate":   None,
        "bit_depth":     None,
        "method":        "none",
        "rolloff_slope": None,
        "confidence":    "low",
        "error":         None,
    }

    if not os.path.exists(file_path):
        result["error"]   = "File tidak ditemukan"
        result["verdict"] = "Error"
        return result

    if NUMPY_AVAILABLE:
        try:
            result["method"] = "spectral"

            with sf.SoundFile(file_path) as af:
                sr           = af.samplerate
                total_frames = len(af)
                result["sample_rate"] = sr

                start  = max(0, total_frames // 2 - n_samples // 2)
                af.seek(start)
                n_read  = min(n_samples, total_frames - start)
                samples = af.read(n_read, dtype="float32")
                if af.channels > 1:
                    samples = samples.mean(axis=1)

            if len(samples) < 1024:
                result["error"]   = "File terlalu pendek"
                result["verdict"] = "Too Short"
                return result

            nyquist  = sr / 2.0
            window   = np.hanning(len(samples))
            fft_data = np.abs(np.fft.rfft(samples * window))
            fft_db   = 20 * np.log10(np.maximum(fft_data, 1e-6))
            fft_db  -= fft_db.max()
            freqs    = np.fft.rfftfreq(len(samples), d=1.0 / sr)

            above        = np.where(fft_db >= -80.0)[0]
            cutoff_hz    = float(freqs[above[-1]]) if len(above) > 0 else 0.0
            bandwidth_pct = (cutoff_hz / nyquist) * 100.0

            result["cutoff_hz"]     = round(cutoff_hz, 0)
            result["bandwidth_pct"] = round(bandwidth_pct, 1)

            if MUTAGEN_AVAILABLE:
                try:
                    result["bit_depth"] = MutagenFLAC(file_path).info.bits_per_sample
                except Exception:
                    pass

            t = _THRESHOLDS
            if sr >= 88200:
                if cutoff_hz >= t["hires_cutoff_min"] and bandwidth_pct > t["upsampled_bw_max"]:
                    result["verdict"], result["confidence"] = "True High-Resolution Audio", "high"
                else:
                    result["verdict"], result["confidence"] = "Upsampled / Transcoded", "high"

            elif sr in (44100, 48000):
                if bandwidth_pct >= t["standard_bw_min"]:
                    v = "Standard Quality (CD / Near-CD)" if sr == 44100 else "Possibly Upsampled"
                    result["verdict"], result["confidence"] = v, "high"
                elif bandwidth_pct >= t["borderline_bw_min"]:
                    f_low  = min(14000.0, cutoff_hz * 0.7)
                    f_high = min(20000.0, cutoff_hz * 0.98)
                    slope  = _compute_rolloff_slope(fft_db, freqs, f_low, f_high)
                    result["rolloff_slope"] = round(slope, 3)
                    if slope >= t["lossy_slope_threshold"]:
                        result["verdict"], result["confidence"] = "Natural Rolloff (Vintage Recording)", "medium"
                    else:
                        result["verdict"], result["confidence"] = "Lossy Transcode", "high"
                else:
                    result["verdict"], result["confidence"] = "Lossy Transcode", "high"
            else:
                result["verdict"], result["confidence"] = "Unknown Sample Rate", "low"

            return result

        except Exception as e:   # [FIX-F2]
            result["method"] = "spectral_failed"
            result["error"]  = str(e)
            log.debug(f"  [ANALYZER] Spectral failed: {e}")

    if MUTAGEN_AVAILABLE:
        try:
            result["method"] = "metadata_only"
            meta = MutagenFLAC(file_path)
            result["sample_rate"] = meta.info.sample_rate
            result["bit_depth"]   = meta.info.bits_per_sample
            result["confidence"]  = "low"
            sr, bd = meta.info.sample_rate, meta.info.bits_per_sample
            if sr >= 88200 and bd >= 24:
                result["verdict"] = "Possibly Hi-Res (no spectral check)"
            elif sr <= 48000 and bd <= 16:
                result["verdict"] = "Standard Quality (no spectral check)"
            else:
                result["verdict"] = "Unknown (no spectral check)"
            return result
        except Exception as e:   # [FIX-F2]
            result["error"] = str(e)

    result["method"]  = "unavailable"
    result["verdict"] = "Cannot verify (pip install numpy soundfile mutagen)"
    return result


def is_truly_lossless(analysis: dict) -> bool:
    """[FIX-F9] Returns True jika verdict dianggap kualitas yang acceptable."""
    good_verdicts = [
        "Standard Quality (CD / Near-CD)",
        "True High-Resolution Audio",
        "Natural Rolloff (Vintage Recording)",
        "Possibly Upsampled",
        "Possibly Hi-Res (no spectral check)",
        "Standard Quality (no spectral check)",
    ]
    verdict = analysis.get("verdict", "")
    return any(v in verdict for v in good_verdicts)


# ═══════════════════════════════════════════════════════════════════════════
#  [C1] SNAPSHOT-BASED FILE DETECTION
# ═══════════════════════════════════════════════════════════════════════════

def snapshot_flac_files(folder: str) -> set[str]:
    """[C1] Snapshot semua .flac di folder, kecuali subfolder backup."""
    if not os.path.exists(folder):
        return set()
    backup_name = "_fake_backup"
    return {
        p.as_posix()
        for p in Path(folder).rglob("*.flac")
        if backup_name not in [part.lower() for part in p.parts]
    }


def find_new_download_v2(track: dict, pre_snap: set[str],
                          post_snap: set[str], start_time: float = None) -> str | None:
    """[C1] Cari file baru via snapshot diff. [FIX-F3] pakai isinstance()."""
    new_files = post_snap - pre_snap
    if start_time is not None:
        for p in post_snap:
            if p in pre_snap:
                try:
                    mtime = os.path.getmtime(p)
                    if mtime >= start_time - 2:
                        new_files.add(p)
                except OSError:
                    pass

    if not new_files:
        log.debug("  [SNAP] Tidak ada file baru terdeteksi.")
        return None
    if len(new_files) == 1:
        path = next(iter(new_files))
        log.debug(f"  [SNAP] 1 file baru: {Path(path).name}")
        return path

    log.debug(f"  [SNAP] {len(new_files)} file baru, memilih via fuzzy...")
    title   = track.get("title", "").lower()
    artists = track.get("artists")
    # [FIX-F3] isinstance() yang benar
    artist  = artists[0].lower() if isinstance(artists, list) and artists else ""

    scored = []
    for fp in new_files:
        stem  = Path(fp).stem.lower()
        score = max(
            SequenceMatcher(None, title, stem).ratio(),
            SequenceMatcher(None, f"{artist} {title}", stem).ratio(),
            SequenceMatcher(None, f"{artist} - {title}", stem).ratio(),
        )
        scored.append((score, fp))
    scored.sort(reverse=True)
    best_score, best_path = scored[0]
    log.debug(f"  [SNAP] Best: {Path(best_path).name} ({best_score:.0%})")
    return best_path


# ═══════════════════════════════════════════════════════════════════════════
#  [C3] TRACK IDENTITY VALIDATION
# ═══════════════════════════════════════════════════════════════════════════

def validate_track_identity(downloaded_file: str, expected_track: dict,
                             title_threshold: float = 0.72,
                             artist_threshold: float = 0.60) -> tuple[bool, str]:
    """[C3] Validasi file yang didownload adalah track yang benar.
    [FIX-F3] isinstance() yang benar pada artists list check."""
    if not MUTAGEN_AVAILABLE:
        return True, "mutagen unavailable — skipping validation"
    if not os.path.exists(downloaded_file):
        return False, "File tidak ditemukan"
    try:
        flac = MutagenFLAC(downloaded_file)
        if not flac.tags:
            return True, "No tags — cannot validate, assuming OK"

        dl_title  = str(flac.tags.get("title",  [""])[0]).lower().strip()
        dl_artist = str(flac.tags.get("artist", [""])[0]).lower().strip()
        exp_title = expected_track.get("title", "").lower().strip()

        # [FIX-F3]
        exp_artists = expected_track.get("artists")
        exp_artist  = (exp_artists[0].lower().strip()
                       if isinstance(exp_artists, list) and exp_artists else "")

        title_sim  = SequenceMatcher(None, exp_title,  dl_title).ratio()
        artist_sim = SequenceMatcher(None, exp_artist, dl_artist).ratio() if exp_artist else 1.0
        detail     = f"title={title_sim:.0%} artist={artist_sim:.0%}"

        if title_sim < title_threshold:
            return False, f"Title mismatch ({detail}) expected '{exp_title}' got '{dl_title}'"
        if exp_artist and artist_sim < artist_threshold:
            # Fallback: cek apakah exp_artist adalah substring/token dari dl_artist
            # Mengatasi kasus kolaborasi: '8ball' dalam '8-ball, cee-lo & mjg'
            exp_norm = re.sub(r"[^a-z0-9]", "", exp_artist)
            dl_norm  = re.sub(r"[^a-z0-9]", "", dl_artist)
            if exp_norm and exp_norm in dl_norm:
                pass  # artist ditemukan sebagai bagian dari dl_artist → OK
            else:
                return False, f"Artist mismatch ({detail}) expected '{exp_artist}' got '{dl_artist}'"


        try:
            dl_dur  = flac.info.length
            dur_str = expected_track.get("duration", "")
            if dur_str and dl_dur and ":" in str(dur_str):
                parts = str(dur_str).split(":")
                exp_dur = int(parts[0]) * 60 + float(parts[1]) if len(parts) == 2 else 0.0
                if exp_dur > 0 and abs(dl_dur - exp_dur) > 15:
                    return False, f"Duration mismatch: ~{exp_dur:.0f}s vs {dl_dur:.0f}s"
        except Exception:
            pass

        return True, f"OK ({detail})"
    except Exception as e:   # [FIX-F2]
        return True, f"Validation error: {e} — assuming OK"


# ═══════════════════════════════════════════════════════════════════════════
#  [S9] MODULE PRE-VALIDATION
# ═══════════════════════════════════════════════════════════════════════════

def validate_modules(source_priority: list[dict], orpheus_dir: str) -> list[dict]:
    """[S9] Cek apakah setiap enabled module terinstall."""
    valid_sources = []
    for source in source_priority:
        if not source.get("enabled", False):
            continue
        module_path = Path(orpheus_dir) / "modules" / source["module"] / "interface.py"
        if module_path.exists():
            valid_sources.append(source)
            log.debug(f"  [MOD] {source['label']}: OK")
        else:
            log.warning(f"  [MOD] {C.YELLOW}{source['label']} tidak terinstall — di-skip.{C.RESET}")
            log.warning(f"        Install: git clone <repo> {orpheus_dir}\\modules\\{source['module']}")
    if not valid_sources:
        log.error(f"  {C.RED}[MOD] Tidak ada module yang valid!{C.RESET}")
    return valid_sources


# ═══════════════════════════════════════════════════════════════════════════
#  STEP 5: DOWNLOAD DARI SATU SOURCE
# ═══════════════════════════════════════════════════════════════════════════

def _download_from_source(track: dict, orpheus_dir: str, module: str,
                           output_folder: str | None = None) -> bool:   # [FIX-F8]
    """Download track dari satu source via OrpheusDL luckysearch."""
    artists = track.get("artists")
    title   = track.get("title", "")

    # Sertakan SEMUA artis di query, bukan hanya artis pertama
    if isinstance(artists, list) and artists:
        artist_str = " ".join(artists)   # misal: "8Ball MJG"
    else:
        artist_str = str(artists) if artists else ""

    query       = f"{artist_str} {title}".strip()
    query_clean = re.sub(r"[<>|&\"']", "", query).strip()

    cmd = [sys.executable, "orpheus.py", "luckysearch", module, "track", query_clean]
    if output_folder:
        cmd += ["-o", output_folder]

    # Log yang lebih informatif: artis dan judul dipisah
    artist_display = " & ".join(artists) if isinstance(artists, list) and artists else str(artists or "?")
    log.info(f"  [DL] {module}: '{artist_display} — {title}' (query: '{query_clean}')")
    try:
        result = subprocess.run(
            cmd, cwd=orpheus_dir, capture_output=True,
            text=True, timeout=300, encoding="utf-8", errors="replace",
        )
        if result.returncode == 0:
            log.info(f"  {C.GREEN}[DL-OK] {module} berhasil{C.RESET}")
            return True
        else:
            log.warning(f"  {C.YELLOW}[DL-FAIL] {module} code={result.returncode}{C.RESET}")
            stderr_preview = (result.stderr or "").strip()[-800:]   # 800 char, ambil bagian akhir (paling relevan)
            if stderr_preview:
                log.debug(f"  STDERR:\n{stderr_preview}")
            return False
    except subprocess.TimeoutExpired:
        log.warning(f"  [DL-TIMEOUT] {module} >5 menit")
        return False
    except Exception as e:   # [FIX-F2]
        log.warning(f"  [DL-ERR] {module}: {e}")
        return False



# ═══════════════════════════════════════════════════════════════════════════
#  STEP 5b: MULTI-SOURCE FALLBACK DOWNLOAD + VERIFY
# ═══════════════════════════════════════════════════════════════════════════

def redownload_with_fallback(
    track: dict,
    orpheus_dir: str,
    music_folder: str,
    preserved_tags: dict,
    output_folder: str | None = None,     # [FIX-F8]
    valid_sources: list | None = None,    # [FIX-F8]
    quality_score: dict | None = None,    # [FIX-F8]
) -> dict:
    """Download ulang dengan multi-source fallback + spectral verify."""
    if valid_sources is None:
        valid_sources = []
    if quality_score is None:
        quality_score = CONFIG["quality_score"]

    search_dir = output_folder or music_folder
    attempts   = []
    candidates = []

    for idx, source in enumerate(valid_sources, 1):
        module = source["module"]
        label  = source["label"]
        print(f"\n  {C.CYAN}[SOURCE {idx}/{len(valid_sources)}] {label} ({module}){C.RESET}")

        pre_snap = snapshot_flac_files(search_dir)
        start_time = time.time()
        dl_ok    = _download_from_source(track, orpheus_dir, module, output_folder)
        attempt  = {"source": module, "label": label, "dl_ok": dl_ok,
                    "analysis": None, "file": None, "identity_ok": None}

        if not dl_ok:
            # Proses orpheus crash / exit non-0 — lewati source ini
            log.warning(f"  [DL-FAIL] ↳ {label}: proses download crash (exit non-0), skip ke source berikutnya.")
            attempts.append(attempt)
            continue

        time.sleep(1)
        post_snap = snapshot_flac_files(search_dir)
        new_file  = find_new_download_v2(track, pre_snap, post_snap, start_time)

        if not new_file:
            # Proses selesai (exit 0) tapi tidak ada file baru muncul di disk
            log.warning(f"  [NO-FILE] ↳ {label}: proses selesai tapi file tidak muncul di disk "
                        f"(mungkin track tidak ditemukan di katalog, atau disimpan di lokasi lain), skip.")
            attempts.append(attempt)
            continue

        attempt["file"] = new_file
        log.info(f"  [FILE-OK] File ditemukan: {Path(new_file).name}")

        id_ok, id_reason = validate_track_identity(new_file, track)
        attempt["identity_ok"] = id_ok
        if not id_ok:
            log.warning(f"  {C.YELLOW}[ID-FAIL] Metadata tidak cocok — {id_reason}{C.RESET}")
            log.warning(f"  [ID-FAIL] ↳ File dihapus, skip ke source berikutnya.")
            try:
                os.remove(new_file)
            except OSError as e:
                log.debug(f"  [ID-FAIL] Gagal hapus: {e}")
            attempts.append(attempt)
            continue

        log.info(f"  [ID-OK]   Identitas cocok — melanjutkan analisis spektral...")
        analysis       = analyze_flac_quality(new_file)
        attempt["analysis"] = analysis

        verdict  = analysis["verdict"]
        sr       = analysis["sample_rate"]
        bw       = analysis["bandwidth_pct"]
        co       = analysis["cutoff_hz"]
        slope    = analysis.get("rolloff_slope")
        conf     = analysis.get("confidence", "?")
        sr_str   = f"{sr/1000:.1f}kHz" if sr else "?"
        co_str   = f"{co/1000:.1f}kHz" if isinstance(co, (int, float)) else "?"
        bw_str   = f"{bw:.1f}%" if bw is not None else "?"
        sl_str   = f"{slope:.2f}dB/kHz" if slope is not None else "N/A"

        if is_truly_lossless(analysis):
            log.info(f"  {C.GREEN}[SPECTRAL-OK] {label} → lossless terverifikasi: {verdict}{C.RESET}")
            log.info(f"               {sr_str} | {co_str} | {bw_str} | {sl_str} [{conf}]")
            if preserved_tags:
                apply_custom_tags(new_file, preserved_tags)
            attempts.append(attempt)
            return {"status": "verified", "source": module, "label": label,
                    "file_path": new_file, "analysis": analysis, "attempts": attempts}
        else:
            score = quality_score.get(verdict, 10)
            if bw is not None:
                score += bw / 5
            candidates.append({"source": module, "label": label, "file": new_file,
                                "analysis": analysis, "score": score, "verdict": verdict})
            log.warning(f"  {C.YELLOW}[SPECTRAL-FAIL] {label} → masih lossy/fake: {verdict} (skor: {score:.1f}){C.RESET}")
            log.warning(f"                 {sr_str} | {co_str} | {bw_str} | {sl_str} — disimpan sebagai kandidat.")

        attempts.append(attempt)

    if not candidates:
        log.error(f"  {C.RED}[ALL-FAIL] Tidak ada source yang menghasilkan file valid.{C.RESET}")
        log.error(f"  [ALL-FAIL] ↳ Penyebab umum: track tidak ada di katalog, metadata tidak cocok, atau semua proses crash.")
        return {"status": "all_failed", "source": None, "label": None,
                "file_path": None, "analysis": None, "attempts": attempts}

    best = max(candidates, key=lambda x: x["score"])
    log.warning(f"  {C.YELLOW}[BEST] Semua fake. Terbaik: {best['label']} -> "
                f"{best['verdict']} (score: {best['score']:.1f}){C.RESET}")

    if preserved_tags:
        apply_custom_tags(best["file"], preserved_tags)

    for cand in candidates:
        if cand["file"] != best["file"] and os.path.exists(cand["file"]):
            try:
                os.remove(cand["file"])
                log.debug(f"  [CLEAN] Hapus inferior: {Path(cand['file']).name}")
            except OSError as e:
                log.debug(f"  [CLEAN] Gagal hapus: {e}")

    return {"status": "best_available", "source": best["source"], "label": best["label"],
            "file_path": best["file"], "analysis": best["analysis"], "attempts": attempts}


# ═══════════════════════════════════════════════════════════════════════════
#  [M4] CHECKPOINT / RESUME SYSTEM
# ═══════════════════════════════════════════════════════════════════════════

def save_checkpoint(session_id: str, processed_idx: int,
                    results: dict, bad_tracks: list[dict]) -> None:
    data = {"session_id": session_id, "processed_idx": processed_idx,
            "results": results, "timestamp": datetime.now().isoformat()}
    try:
        with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:   # [FIX-M3]
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:   # [FIX-F2]
        log.debug(f"  [CKPT] Gagal simpan: {e}")


def load_checkpoint() -> dict | None:
    if not CHECKPOINT_FILE.exists():
        return None
    try:
        with open(CHECKPOINT_FILE, encoding="utf-8") as f:   # [FIX-M3]
            return json.load(f)
    except Exception as e:   # [FIX-F2]
        log.debug(f"[CKPT] Gagal load: {e}")
        return None


def clear_checkpoint() -> None:
    try:
        if CHECKPOINT_FILE.exists():
            CHECKPOINT_FILE.unlink()
    except Exception as e:   # [FIX-F2]
        log.debug(f"[CKPT] Gagal hapus: {e}")


# ═══════════════════════════════════════════════════════════════════════════
#  STEP 6: SUMMARY REPORT
# ═══════════════════════════════════════════════════════════════════════════

def print_summary(bad_tracks: list[dict], results: dict) -> dict:
    verified_ok  = sum(1 for r in results.values() if r == "success_verified")
    best_avail   = sum(1 for r in results.values() if r == "best_available")
    unverified   = sum(1 for r in results.values() if r == "success_unverified")
    failed_count = sum(1 for r in results.values() if r == "failed")
    skip_count   = sum(1 for r in results.values() if r == "skipped")
    legacy_ok    = sum(1 for r in results.values() if r == "success")

    total_attempted = len(results) - skip_count

    print(f"\n{C.BOLD}{C.CYAN}{'=' * 68}")
    print(f"  [RINGKASAN] ORPHEUS HEALER v2.1")
    print(f"{'=' * 68}{C.RESET}")
    print(f"  Total track bermasalah            : {C.YELLOW}{len(bad_tracks)}{C.RESET}")
    print(f"  Diproses sesi ini                 : {total_attempted}")
    print()
    print(f"  {C.GREEN}[OK]{C.RESET}  Terverifikasi TRUE LOSSLESS   : {C.GREEN}{verified_ok + legacy_ok}{C.RESET}")
    print(f"  {C.YELLOW}[~]{C.RESET}   Best available (semua fake)   : {C.YELLOW}{best_avail}{C.RESET}")
    print(f"  {C.YELLOW}[?]{C.RESET}   Download OK, tidak terverif   : {C.YELLOW}{unverified}{C.RESET}")
    print(f"  {C.RED}[X]{C.RESET}   Semua source gagal            : {C.RED}{failed_count}{C.RESET}")
    print(f"  {C.YELLOW}[>>]{C.RESET}  Dilewati                      : {C.YELLOW}{skip_count}{C.RESET}")

    if best_avail > 0:
        print(f"\n{C.YELLOW}  BEST AVAILABLE:{C.RESET}")
        for track in bad_tracks:
            fname = track["filename"]
            if results.get(fname) == "best_available":
                fb      = track.get("fallback_result", {})
                a       = fb.get("analysis") or {}
                co      = a.get("cutoff_hz")
                bw      = a.get("bandwidth_pct")
                co_str  = f"{co/1000:.1f}kHz" if isinstance(co, (int, float)) else "?"
                bw_str  = f"{bw:.1f}%" if isinstance(bw, float) else "?"
                src_list = ", ".join(att["label"] for att in fb.get("attempts", [])
                                     if att.get("dl_ok"))
                print(f"  [~] {fname}")
                print(f"      Dari: {fb.get('label','?')} -> {a.get('verdict','?')} "
                      f"| {co_str} | BW: {bw_str}")
                print(f"      Dicoba: {src_list or '?'}")

    if failed_count > 0:
        print(f"\n{C.RED}  Track GAGAL:{C.RESET}")
        for track in bad_tracks:
            if results.get(track["filename"]) == "failed":
                print(f"  [X] {track['filename']} [{track['verdict']}]")

    print(f"\n{C.CYAN}  Log: {CONFIG['paths']['log_file']}{C.RESET}")
    print(f"{C.BOLD}{C.CYAN}{'=' * 68}{C.RESET}\n")

    return {"verified": verified_ok + legacy_ok, "best_available": best_avail,
            "failed": failed_count, "skipped": skip_count}


# ═══════════════════════════════════════════════════════════════════════════
#  [S10] COMPLETION NOTIFICATION
# ═══════════════════════════════════════════════════════════════════════════

def notify_done(summary: dict, total: int) -> None:
    msg = (f"{summary['verified']} verified | {summary['best_available']} best-avail | "
           f"{summary['failed']} failed | {summary['skipped']} skipped")
    if PLYER_AVAILABLE:
        try:
            plyer_notification.notify(
                title="Orpheus Healer — Selesai!",
                message=f"{total} tracks: {msg}",
                app_name="OrpheusHealer",
                timeout=10,
            )
            return
        except Exception:
            pass
    print(f"\n{C.GREEN}{C.BOLD}")
    print("  ╔══════════════════════════════════════════════════╗")
    print("  ║           ORPHEUS HEALER — SELESAI!             ║")
    print(f"  ║  {msg[:48].center(48)} ║")
    print("  ╚══════════════════════════════════════════════════╝")
    print(f"{C.RESET}")


# ═══════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    print_banner()

    parser = argparse.ArgumentParser(description="Orpheus Healer v2.1")
    parser.add_argument("--csv",
        default=CONFIG["paths"]["soniq_csv"],
        help="Path ke CSV Soniq Tools")
    parser.add_argument("--music-folder",
        default=CONFIG["paths"]["music_folder"],
        help="Folder musik tempat FLAC tersimpan")
    parser.add_argument("--output",
        default=None,
        help="Folder output download")
    parser.add_argument("--dry-run", action="store_true",
        help="Simulasi saja, tidak download")
    parser.add_argument("--auto", action="store_true",
        help="Download semua tanpa konfirmasi")
    parser.add_argument("--include-possibly-upsampled", action="store_true",
        help="Tambahkan 'Possibly Upsampled' ke bad verdicts")
    parser.add_argument("--report-only", action="store_true",
        help="Simpan laporan JSON saja, tidak download")
    parser.add_argument("--no-checkpoint", action="store_true",
        help="Abaikan checkpoint, mulai dari awal")
    parser.add_argument("--skip-dedup", action="store_true",
        help="[NEW-DUP] Skip langkah duplicate detection")
    args = parser.parse_args()

    bad_verdicts = list(CONFIG["settings"]["bad_verdicts"])
    if args.include_possibly_upsampled:
        bad_verdicts.append("Possibly Upsampled")

    if args.output is None:
        args.output = args.music_folder

    # ── [NEW-DUP] STEP 0: Duplicate Detection ─────────────────────────────
    if not args.skip_dedup and not args.report_only and not args.dry_run:
        print(f"\n{C.BOLD}{C.CYAN}[STEP 0] Duplicate Detection{C.RESET}")
        dup_summary = run_duplicate_check(
            csv_path      = args.csv,
            music_folder  = args.music_folder,
            backup_folder = CONFIG["paths"]["backup_folder"],
            delete        = CONFIG["settings"]["delete_fake_files"],
        )
        if dup_summary["groups"] > 0:
            print(f"\n  {C.CYAN}[DUP SELESAI]{C.RESET} "
                  f"{dup_summary['removed']} removed, "
                  f"{dup_summary['skipped']} skip, "
                  f"{dup_summary['errors']} error.\n")
    elif args.skip_dedup:
        log.info("[DUP] Duplicate detection di-skip (--skip-dedup).")

    # ── STEP 1: Parse CSV ──────────────────────────────────────────────────
    bad_tracks = parse_soniq_csv(args.csv, bad_verdicts)
    if not bad_tracks:
        log.info(f"{C.GREEN}Tidak ada track bermasalah!{C.RESET}")
        return

    print(f"\n{C.BOLD}{C.YELLOW}[!!] DITEMUKAN {len(bad_tracks)} TRACK BERMASALAH:{C.RESET}")
    print("─" * 65)

    verdict_groups: dict[str, list] = {}
    for track in bad_tracks:
        verdict_groups.setdefault(track["verdict"], []).append(track)

    for verdict, tracks in sorted(verdict_groups.items()):
        color = C.RED if ("Upsampled" in verdict or "Lossy" in verdict) else C.YELLOW
        print(f"\n  {color}[{verdict}] — {len(tracks)} track:{C.RESET}")
        for t in tracks:
            # [FIX-F3] isinstance yang benar
            arts = t.get("artists")
            artists_str = "; ".join(arts) if isinstance(arts, list) and arts else "Unknown"
            print(f"    * {artists_str} — {t['title']}")
            if t["sample_rate"]:
                print(f"      -> {t['sample_rate']} | Cutoff: {t['cutoff']} kHz | BW: {t['bandwidth']}%")

    print("\n" + "─" * 65)

    if args.report_only:
        report_path = "orpheus_healer_report.json"
        with open(report_path, "w", encoding="utf-8") as f:   # [FIX-M3]
            json.dump(bad_tracks, f, ensure_ascii=False, indent=2)
        log.info(f"[REPORT] Disimpan ke: {report_path}")
        return

    if args.dry_run:
        log.info("[DRY-RUN] Selesai.")
        return

    orpheus_dir   = CONFIG["paths"]["orpheus_dir"]
    valid_sources = validate_modules(CONFIG["source_priority"], orpheus_dir)
    if not valid_sources:
        print(f"\n{C.RED}[ERROR] Tidak ada module valid. Install minimal 1 module.{C.RESET}")
        sys.exit(1)   # [FIX-M5]

    print(f"\n  Sources: {' -> '.join(s['label'] for s in valid_sources)}")

    # ── [M4] Checkpoint ────────────────────────────────────────────────────
    resume_idx = 0
    results    = {}
    session_id = f"{Path(args.csv).stem}_{datetime.now().strftime('%Y%m%d')}"

    if not args.no_checkpoint:
        ckpt = load_checkpoint()
        if ckpt and ckpt.get("session_id") == session_id:
            last_idx = ckpt.get("processed_idx", 0)
            print(f"\n{C.YELLOW}  [CHECKPOINT] Progress: track {last_idx}/{len(bad_tracks)}{C.RESET}")
            ans = input("  Resume? [Y/n]: ").strip().lower()
            if ans != "n":
                resume_idx = last_idx
                results    = ckpt.get("results", {})
                print(f"  Melanjutkan dari track ke-{resume_idx + 1}...\n")
            else:
                clear_checkpoint()

    # ── Mode selection ─────────────────────────────────────────────────────
    if not args.auto:
        print(f"\n{C.BOLD}Pilih mode:{C.RESET}")
        print(f"  [A] Auto        — download semua {len(bad_tracks)} track")
        print(f"  [I] Interactive — konfirmasi satu per satu")
        print(f"  [Q] Quit\n")
        choice = input("Pilihan (A/I/Q): ").strip().upper()
        if choice == "Q":
            return
        interactive_mode = (choice == "I")
    else:
        interactive_mode = False

    log.info("[SCAN] Mencari file di disk...")
    bad_tracks         = locate_files(bad_tracks, args.music_folder)
    preserve_tags_list = CONFIG["settings"].get("preserve_tags", [])

    print(f"\n{C.BOLD}[START] Proses download (multi-source v2.1)...{C.RESET}\n")

    for i, track in enumerate(bad_tracks):
        if i < resume_idx:
            continue

        filename    = track["filename"]
        # [FIX-F3]
        arts        = track.get("artists")
        artists_str = "; ".join(arts) if isinstance(arts, list) and arts else "Unknown"

        print(f"{C.BOLD}[{i+1}/{len(bad_tracks)}]{C.RESET} "
              f"{C.WHITE}{artists_str} — {track['title']}{C.RESET}")
        print(f"         Verdict: {C.RED}{track['verdict']}{C.RESET}")

        if interactive_mode:
            print(f"         File: {track['file_path'] or 'tidak ditemukan'}")
            choice = input("         Download ulang? [Y/n/q]: ").strip().lower()
            if choice == "q":
                break
            if choice == "n":
                results[filename] = "skipped"
                save_checkpoint(session_id, i + 1, results, bad_tracks)
                continue

        preserved_tags: dict = {}
        fp = track.get("file_path")
        if fp and os.path.exists(fp):
            preserved_tags = extract_custom_tags(fp, preserve_tags_list)

        if track.get("file_path"):
            handle_fake_file(track,
                             delete=CONFIG["settings"]["delete_fake_files"],
                             backup_folder=CONFIG["paths"]["backup_folder"])

        fb = redownload_with_fallback(
            track,
            orpheus_dir    = orpheus_dir,
            music_folder   = args.music_folder,
            preserved_tags = preserved_tags,
            output_folder  = args.output,
            valid_sources  = valid_sources,
            quality_score  = CONFIG["quality_score"],
        )

        track["fallback_result"] = fb
        status = fb["status"]

        if status == "verified":
            a      = fb["analysis"]
            sr_str = f"{a['sample_rate']/1000:.1f}kHz" if a.get("sample_rate") else "?"
            bd_str = f"{a['bit_depth']}-bit" if a.get("bit_depth") else "?"
            co     = a.get("cutoff_hz")
            bw     = a.get("bandwidth_pct")
            sl     = a.get("rolloff_slope")
            co_str = f"{co/1000:.1f}kHz" if isinstance(co, (int, float)) else "?"
            bw_str = f"{bw:.1f}%" if bw is not None else "?"
            sl_str = f"{sl:.2f}dB/kHz" if sl is not None else "N/A"
            log.info(f"  {C.GREEN}[RESULT] ✓ LOSSLESS TERVERIFIKASI dari {fb['label']}{C.RESET}")
            log.info(f"           {sr_str}/{bd_str} | Cutoff:{co_str} | BW:{bw_str} | Slope:{sl_str}")
            results[filename] = "success_verified"
        elif status == "best_available":
            a      = fb.get("analysis") or {}
            co     = a.get("cutoff_hz")
            bw     = a.get("bandwidth_pct")
            verdict_str = a.get('verdict', '?')
            co_str = f"{co/1000:.1f}kHz" if isinstance(co, (int, float)) else "?"
            bw_str = f"{bw:.1f}%" if bw is not None else "?"
            log.warning(f"  {C.YELLOW}[RESULT] ~ BEST AVAILABLE dari {fb['label']}: "
                        f"{verdict_str} — Cutoff:{co_str} | BW:{bw_str}{C.RESET}")
            log.warning(f"  [RESULT] ↳ Tidak ada source lossless, file terbaik yang tersedia disimpan.")
            results[filename] = "best_available"
        else:
            # ALL-FAIL sudah di-log di dalam redownload_with_fallback, tidak perlu duplikat
            log.error(f"  {C.RED}[RESULT] ✗ GAGAL — track tidak bisa didownload dari manapun.{C.RESET}")
            results[filename] = "failed"

        save_checkpoint(session_id, i + 1, results, bad_tracks)

        if i + 1 < len(bad_tracks):
            delay = CONFIG["settings"]["delay_between_downloads"]
            log.info(f"  [WAIT] {delay}s...")
            time.sleep(delay)

        print()

    summary = print_summary(bad_tracks, results)

    result_path = f"healer_session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(result_path, "w", encoding="utf-8") as f:   # [FIX-M3]
        json.dump({
            "version": "2.1", "timestamp": datetime.now().isoformat(),
            "csv_source": args.csv, "total_bad": len(bad_tracks),
            "results": results, "tracks": bad_tracks,
        }, f, ensure_ascii=False, indent=2, default=str)
    log.info(f"[SAVE] Session disimpan: {result_path}")

    clear_checkpoint()
    notify_done(summary, len(bad_tracks))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n{C.YELLOW}[!] Dihentikan (Ctrl+C). "
              f"Checkpoint tersimpan — jalankan lagi untuk resume.{C.RESET}")
        sys.exit(0)   # [FIX-M5]
