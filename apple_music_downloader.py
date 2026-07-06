#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║              APPLE MUSIC + TIDAL CSV DOWNLOADER                              ║
║  Baca CSV Apple Music Library → download via orpheus.py dengan fallback      ║
║  dari Tidal dan Apple Music (Direct URL & Lucky Search).                     ║
╚══════════════════════════════════════════════════════════════════════════════╝

Cara Pakai:
  python apple_music_downloader.py

Fitur:
  - Baca "My Apple Music Library.csv" dan extract semua track
  - Skip duplicate (Apple ID atau kombinasi Title-Artist yang sudah diproses)
  - Skip jika file sudah ada di output folder (cek berdasarkan title+artist fuzzy)
  - Prioritas download:
      1. Apple Music Direct URL (jika bukan iCloud track)
      2. Tidal (Lucky Search)
      3. Apple Music (Lucky Search)
  - Progress bar + resume (checkpoint file)
  - Log semua ke apple_dl_log.txt
"""

import sys
import io

# Fix Windows terminal encoding
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import os
import re
import csv
import json
import time
import logging
import subprocess
from pathlib import Path
from datetime import datetime

# ── CONFIG ───────────────────────────────────────────────────────────────────

SCRIPT_DIR    = Path(__file__).parent
CSV_FILE      = SCRIPT_DIR / "My Apple Music Library.csv"
OUTPUT_FOLDER = Path(r"D:\Music\New folder (2)\Mix\MIXING")
ORPHEUS_DIR   = SCRIPT_DIR
CHECKPOINT    = SCRIPT_DIR / "apple_dl_checkpoint.json"
LOG_FILE      = SCRIPT_DIR / "apple_dl_log.txt"

DELAY_BETWEEN = 2   # detik antar download
TIMEOUT       = 300 # timeout per track (detik)

# ── LOGGING ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("MultiSourceDL")


# ── COLORS ───────────────────────────────────────────────────────────────────

class C:
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    RED    = "\033[91m"
    CYAN   = "\033[96m"
    BOLD   = "\033[1m"
    RESET  = "\033[0m"


# ── CHECKPOINT ───────────────────────────────────────────────────────────────

def load_checkpoint() -> set:
    """Load set of already-downloaded Apple IDs."""
    if CHECKPOINT.exists():
        try:
            with open(CHECKPOINT, encoding="utf-8") as f:
                data = json.load(f)
            return set(data.get("done", []))
        except Exception as e:
            log.warning(f"[CHECKPOINT] Gagal load: {e}")
    return set()


def save_checkpoint(done_ids: set) -> None:
    """Save checkpoint."""
    try:
        with open(CHECKPOINT, "w", encoding="utf-8") as f:
            json.dump({"done": sorted(done_ids), "updated": datetime.now().isoformat()}, f, indent=2)
    except Exception as e:
        log.warning(f"[CHECKPOINT] Gagal save: {e}")


# ── CSV PARSING ───────────────────────────────────────────────────────────────

def parse_csv(csv_path: Path) -> list[dict]:
    """
    Parse Apple Music CSV. Kolom: Track name, Artist name, Album,
    Playlist name, Type, ISRC, Apple - id
    """
    tracks = []
    seen_apple_ids = set()
    seen_keys = set()

    try:
        with open(csv_path, encoding="utf-8-sig", errors="replace", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                apple_id = row.get("Apple - id", "").strip()
                title    = row.get("Track name", "").strip()
                artist   = row.get("Artist name", "").strip()
                album    = row.get("Album", "").strip()
                isrc     = row.get("ISRC", "").strip()

                # Skip baris kosong
                if not title:
                    continue

                is_icloud = apple_id.startswith("i.") or not apple_id

                # Deduplicate berdasarkan Apple ID
                if not is_icloud:
                    if apple_id in seen_apple_ids:
                        continue
                    seen_apple_ids.add(apple_id)

                # Deduplicate berdasarkan title + artist
                key = (artist.lower(), title.lower())
                if key in seen_keys:
                    continue
                seen_keys.add(key)

                tracks.append({
                    "apple_id": apple_id,
                    "title":    title,
                    "artist":   artist,
                    "album":    album,
                    "isrc":     isrc,
                    "is_icloud": is_icloud
                })
    except FileNotFoundError:
        log.error(f"[CSV] File tidak ditemukan: {csv_path}")
        sys.exit(1)
    except Exception as e:
        log.error(f"[CSV] Error membaca CSV: {e}")
        sys.exit(1)

    return tracks


# ── DUPLICATE CHECK ───────────────────────────────────────────────────────────

def _normalize(s: str) -> str:
    """Normalize string untuk perbandingan."""
    return re.sub(r"[^\w\s]", "", s.lower()).strip()


def check_existing_files(output_folder: Path) -> set:
    """
    Scan output folder dan return set nama file yang sudah ada (tanpa ekstensi, normalized).
    """
    existing = set()
    if not output_folder.exists():
        return existing
    for f in output_folder.rglob("*"):
        if f.suffix.lower() in (".flac", ".m4a", ".aac", ".mp3", ".alac"):
            existing.add(_normalize(f.stem))
    return existing


def is_duplicate(track: dict, existing_files: set) -> bool:
    """
    Cek apakah track kemungkinan sudah ada di disk.
    Cek berdasarkan title + artist (fuzzy: normalize dan substring match).
    """
    title_norm  = _normalize(track["title"])
    artist_norm = _normalize(track["artist"])

    for fname in existing_files:
        if title_norm in fname or fname in title_norm:
            return True
    return False


# ── DOWNLOAD ──────────────────────────────────────────────────────────────────

def build_apple_url(apple_id: str) -> str:
    """Build Apple Music URL dari ID numerik yang valid untuk parser Orpheus."""
    return f"https://music.apple.com/us/song/track/{apple_id}"


def run_orpheus_cmd(cmd: list) -> tuple[bool, str]:
    """Jalankan command orpheus.py dan return status + error log."""
    try:
        result = subprocess.run(
            cmd,
            cwd=str(ORPHEUS_DIR),
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode == 0:
            return True, ""
        stderr_msg = result.stderr.strip() if result.stderr else ""
        stdout_msg = result.stdout.strip() if result.stdout else ""
        full_err = f"code={result.returncode} | STDOUT: {stdout_msg.replace(chr(10), ' ')} | STDERR: {stderr_msg.replace(chr(10), ' ')}"
        return False, full_err
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT setelah 5 menit"
    except Exception as e:
        return False, str(e)


def download_track(track: dict, existing_files: set) -> str:
    """
    Download satu track. Mencoba:
    1. Apple Music direct URL (jika bukan iCloud).
    2. Tidal Lucky Search.
    3. Apple Music Lucky Search.
    Return: 'ok' | 'skip_dup' | 'fail'
    """
    apple_id  = track["apple_id"]
    title     = track["title"]
    artist    = track["artist"]
    is_icloud = track["is_icloud"]

    # Cek duplikat di disk
    if is_duplicate(track, existing_files):
        log.info(f"  {C.YELLOW}[SKIP-DUP]{C.RESET} Sudah ada: {artist} - {title}")
        return "skip_dup"

    log.info(f"  {C.CYAN}[DL-START]{C.RESET} {artist} - {title}")

    # 1. Apple Music Direct (Jika bukan iCloud)
    if not is_icloud:
        url = build_apple_url(apple_id)
        cmd = [sys.executable, "orpheus.py", url, "-o", str(OUTPUT_FOLDER)]
        log.info(f"    -> Mencoba {C.BOLD}Apple Music (Direct URL){C.RESET}...")
        ok, err = run_orpheus_cmd(cmd)
        if ok:
            log.info(f"    {C.GREEN}[OK]{C.RESET} Berhasil via Apple Music (Direct)")
            existing_files.add(_normalize(f"{title}"))
            return "ok"
        else:
            log.warning(f"    [FAIL] Apple Music Direct gagal: {err}")

    # 2. Tidal Lucky Search
    query = f"{artist} {title}".strip()
    query_clean = re.sub(r"[<>|&\"']", "", query)
    cmd_tidal = [sys.executable, "orpheus.py", "luckysearch", "tidal", "track", query_clean, "-o", str(OUTPUT_FOLDER)]
    log.info(f"    -> Mencoba {C.BOLD}Tidal (Lucky Search){C.RESET} untuk query: '{query_clean}'...")
    ok, err = run_orpheus_cmd(cmd_tidal)
    if ok:
        log.info(f"    {C.GREEN}[OK]{C.RESET} Berhasil via Tidal")
        existing_files.add(_normalize(f"{title}"))
        return "ok"
    else:
        log.warning(f"    [FAIL] Tidal Lucky Search gagal: {err}")

    # 3. Apple Music Lucky Search
    cmd_apple_lucky = [sys.executable, "orpheus.py", "luckysearch", "applemusic", "track", query_clean, "-o", str(OUTPUT_FOLDER)]
    log.info(f"    -> Mencoba {C.BOLD}Apple Music (Lucky Search){C.RESET} untuk query: '{query_clean}'...")
    ok, err = run_orpheus_cmd(cmd_apple_lucky)
    if ok:
        log.info(f"    {C.GREEN}[OK]{C.RESET} Berhasil via Apple Music Search")
        existing_files.add(_normalize(f"{title}"))
        return "ok"
    else:
        log.error(f"    {C.RED}[FAIL-ALL]{C.RESET} Semua metode gagal untuk {artist} - {title}")
        log.debug(f"Detail error Apple Search: {err}")
        return "fail"


# ── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    print(f"""
{C.CYAN}{C.BOLD}
╔══════════════════════════════════════════════════════════════════════════════╗
║              MULTI-SOURCE CSV DOWNLOADER                                     ║
╚══════════════════════════════════════════════════════════════════════════════╝
{C.RESET}
  CSV     : {CSV_FILE}
  Output  : {OUTPUT_FOLDER}
  Sources : Apple Music & Tidal
  Orpheus : {ORPHEUS_DIR / 'orpheus.py'}
""")

    # Validasi: cek module terinstall
    for mod in ["applemusic", "tidal"]:
        module_path = ORPHEUS_DIR / "modules" / mod / "interface.py"
        if not module_path.exists():
            log.error(f"{C.RED}[ERROR] Module '{mod}' tidak ditemukan di: {module_path}")
            sys.exit(1)

    # Validasi: cek orpheus.py
    if not (ORPHEUS_DIR / "orpheus.py").exists():
        log.error(f"{C.RED}[ERROR] orpheus.py tidak ditemukan di: {ORPHEUS_DIR}{C.RESET}")
        sys.exit(1)

    # Buat output folder jika belum ada
    OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)

    # Parse CSV
    log.info("[INIT] Membaca CSV...")
    tracks = parse_csv(CSV_FILE)
    log.info(f"[INIT] {len(tracks)} track unik ditemukan di CSV")

    # Load checkpoint (sudah didownload sebelumnya)
    done_ids = load_checkpoint()
    log.info(f"[INIT] {len(done_ids)} track sudah didownload sebelumnya (dari checkpoint)")

    # Filter yang belum didownload
    pending = [t for t in tracks if t["apple_id"] not in done_ids]
    log.info(f"[INIT] {len(pending)} track perlu didownload")

    if not pending:
        log.info(f"{C.GREEN}[DONE] Semua track sudah didownload!{C.RESET}")
        return

    # Scan existing files di disk
    log.info(f"[SCAN] Indexing file yang sudah ada di: {OUTPUT_FOLDER}")
    existing_files = check_existing_files(OUTPUT_FOLDER)
    log.info(f"[SCAN] {len(existing_files)} file ditemukan di disk")

    # ── Download Loop ──
    stats = {"ok": 0, "skip_dup": 0, "fail": 0}
    total = len(pending)

    print(f"\n{C.BOLD}{'─' * 70}{C.RESET}")
    print(f"  Memulai download {total} track...\n")

    for idx, track in enumerate(pending, 1):
        apple_id = track["apple_id"]
        print(f"\n  [{idx:>4}/{total}] ", end="")

        result = download_track(track, existing_files)
        stats[result if result in stats else "fail"] += 1

        # Mark done
        done_ids.add(apple_id)

        # Save checkpoint setiap 10 track
        if idx % 10 == 0:
            save_checkpoint(done_ids)

        # Delay antar download (kecuali yang di-skip)
        if result not in ("skip_dup",) and idx < total:
            time.sleep(DELAY_BETWEEN)

    # Final checkpoint save
    save_checkpoint(done_ids)

    # ── Summary ──
    print(f"\n{C.BOLD}{'═' * 70}{C.RESET}")
    print(f"""
  {C.BOLD}HASIL DOWNLOAD:{C.RESET}
  ✅  Berhasil   : {C.GREEN}{stats['ok']}{C.RESET}
  ⏭️  Skip (dup) : {C.YELLOW}{stats['skip_dup']}{C.RESET}
  ❌  Gagal      : {C.RED}{stats['fail']}{C.RESET}
  📁  Output     : {OUTPUT_FOLDER}
  📋  Log        : {LOG_FILE}
""")

    if stats["fail"] > 0:
        log.warning(f"[DONE] {stats['fail']} track gagal. Cek {LOG_FILE} untuk detail.")
    else:
        log.info(f"{C.GREEN}[DONE] Semua track berhasil didownload!{C.RESET}")


if __name__ == "__main__":
    main()
