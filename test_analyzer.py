#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test standalone untuk built-in FLAC spectral analyzer di orpheus_healer.py
Jalankan: python test_analyzer.py [path_folder_flac]
"""
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from pathlib import Path
from orpheus_healer import analyze_flac_quality, is_truly_lossless, NUMPY_AVAILABLE, MUTAGEN_AVAILABLE

def main():
    print("="*60)
    print("  ORPHEUS HEALER - Standalone Analyzer Test")
    print("="*60)
    print(f"  numpy+soundfile available : {NUMPY_AVAILABLE}")
    print(f"  mutagen available         : {MUTAGEN_AVAILABLE}")
    print()

    # Cari folder musik dari argumen atau scan project
    if len(sys.argv) > 1:
        search_root = sys.argv[1]
    else:
        search_root = "."

    print(f"  Mencari file FLAC di: {os.path.abspath(search_root)}")
    print()

    test_files = []
    for p in Path(search_root).rglob("*.flac"):
        test_files.append(str(p))
        if len(test_files) >= 10:
            break

    if not test_files:
        print("[!] Tidak ada file FLAC ditemukan.")
        print(f"    Coba: python test_analyzer.py C:\\Users\\MIS\\Music\\Tidal")
        return

    print(f"  Ditemukan {len(test_files)} file FLAC untuk diuji.\n")

    ok_count = 0
    fake_count = 0
    unknown_count = 0

    for f in test_files:
        fname = Path(f).name
        print(f"[TEST] {fname}")

        result = analyze_flac_quality(f)
        verdict = result["verdict"]
        method  = result["method"]
        sr      = result["sample_rate"]
        bd      = result["bit_depth"]
        co      = result["cutoff_hz"]
        bw      = result["bandwidth_pct"]
        err     = result["error"]

        sr_str  = f"{sr/1000:.1f} kHz" if sr else "?"
        bd_str  = f"{bd}-bit" if bd else "?"
        co_str  = f"{co/1000:.2f} kHz" if isinstance(co, (int, float)) else "?"
        bw_str  = f"{bw:.1f}%" if isinstance(bw, (int, float)) else "?"

        print(f"       Verdict    : {verdict}")
        print(f"       Method     : {method}")
        print(f"       {sr_str} / {bd_str} | Cutoff: {co_str} | BW: {bw_str}")

        if err:
            print(f"       Error      : {err}")

        lossless = is_truly_lossless(result)
        status = "[OK] LOSSLESS" if lossless else "[!!] FAKE/UPSAMPLED"
        print(f"       Status     : {status}")
        print()

        if "unavailable" in method or "failed" in method:
            unknown_count += 1
        elif lossless:
            ok_count += 1
        else:
            fake_count += 1

    print("="*60)
    print(f"  HASIL:")
    print(f"  [OK] Terverifikasi lossless : {ok_count}")
    print(f"  [!!] Terdeteksi fake        : {fake_count}")
    print(f"  [?]  Tidak bisa diverifikasi: {unknown_count}")
    print("="*60)

if __name__ == "__main__":
    main()
