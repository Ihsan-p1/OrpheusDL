#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
===========================================================================
                      AUDIO QUALITY DUPLICATE CHECKER
===========================================================================
Pendeteksi dan pembersih file duplikat berdasarkan analisis kualitas suara.
Mendukung filter FLAC (analisis spectral & metadata) dan pemindahan otomatis.

Cara Pakai:
  python check_duplicates.py [options]
"""

import os
import re
import sys
import shutil
import argparse
from pathlib import Path

# Setup Windows terminal encoding to UTF-8
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Add parent directory to sys.path to allow importing orpheus_healer
sys.path.append(str(Path(__file__).parent))

try:
    from quality_probe import inspect
    from orpheus_healer import (
        _DUP_MARKER_RE,
        _normalize_for_dedup,
        NUMPY_AVAILABLE,
        MUTAGEN_AVAILABLE
    )
except ImportError as e:
    print(f"[ERROR] Gagal mengimpor orpheus_healer.py: {e}")
    print("Pastikan script ini diletakkan di folder yang sama dengan orpheus_healer.py.")
    sys.exit(1)

# Regex tambahan untuk mencocokkan suffix timestamp seperti _20260701_095825
_TIMESTAMP_RE = re.compile(r"_\d{8}_\d{6}")

# Terminal colors definition
class Colors:
    RED    = "\033[91m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    CYAN   = "\033[96m"
    WHITE  = "\033[97m"
    BOLD   = "\033[1m"
    RESET  = "\033[0m"

def get_canonical_name(filename: str) -> str:
    """
    Mengembalikan nama file canonical (bersih dari suffix timestamp dan duplicate marker),
    dengan tetap mempertahankan casing asli dari nama file.
    """
    path = Path(filename)
    stem = path.stem
    ext = path.suffix
    
    # 1. Hapus timestamp suffix
    stem = _TIMESTAMP_RE.sub("", stem)
    # 2. Hapus duplicate marker
    stem = _DUP_MARKER_RE.sub("", stem)
    # 3. Normalisasi spasi berlebih
    stem = re.sub(r"\s+", " ", stem).strip()
    
    return stem + ext

def normalize_for_grouping(filename: str) -> str:
    """
    Normalisasi nama file khusus untuk grouping duplikat.
    Menghapus timestamp, duplicate markers, menyamakan case, dan membersihkan separator.
    """
    # 1. Hapus timestamp suffix dari stem
    path = Path(filename)
    stem = path.stem
    stem_no_ts = _TIMESTAMP_RE.sub("", stem)
    
    # 2. Panggil normalisasi bawaan orpheus_healer (yang akan menghapus dup markers, lowercase, dll)
    return _normalize_for_dedup(stem_no_ts + path.suffix)

_STATUS_RANK = {"verified": 3, "unknown": 2, "suspect": 1, "corrupt": 0}


def get_file_quality_score(file_path: Path) -> tuple:
    """Tuple untuk mengurutkan duplikat. Makin besar makin dipilih.

    Provenance menang lebih dulu, lalu bit depth, lalu ukuran file. Ukuran file
    jadi penentu terakhir karena dua file lossless dengan isi sama seharusnya
    berukuran mirip, dan yang lebih besar biasanya yang tidak terpotong.

    Elemen terakhir adalah dict untuk ditampilkan, bukan untuk diurutkan.
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


def colorize_status(status: str) -> str:
    if status in ("suspect", "corrupt"):
        return f"{Colors.RED}{status}{Colors.RESET}"
    if status == "verified":
        return f"{Colors.GREEN}{status}{Colors.RESET}"
    return f"{Colors.YELLOW}{status}{Colors.RESET}"


def _quality_line(display: dict) -> str:
    """Satu baris ringkasan kualitas untuk ditampilkan."""
    sr = display.get("sample_rate") or 0
    sr_str = f"{sr/1000:.1f}kHz" if sr else "?"
    bd = display.get("bit_depth") or 0
    bd_str = f"{bd}bit" if bd else "?"
    co = display.get("cutoff_hz")
    co_str = f" tebing {co/1000:.1f}kHz" if co is not None else ""
    src = display.get("provenance")
    src_str = f" | {src}" if src else ""
    return f"{colorize_status(display.get('status', '?'))} ({sr_str}/{bd_str}{co_str}){src_str}"



def main():
    parser = argparse.ArgumentParser(description="Audio Quality Duplicate Checker")
    parser.add_argument("--target-dir", default=r"D:\Music\New folder (2)\Mix\MIXING\flac", 
                        help="Folder target yang berisi file FLAC untuk dicek")
    parser.add_argument("--backup-dir", default=r"D:\Music\New folder (2)\Mix\MIXING\flac\_duplicates_backup",
                        help="Folder tujuan untuk mem-backup duplikat")
    parser.add_argument("--delete", action="store_true", 
                        help="Hapus file duplikat secara permanen (bukan backup)")
    parser.add_argument("--dry-run", action="store_true", 
                        help="Hanya preview duplikat tanpa memindahkan atau mengubah file")
    parser.add_argument("--auto", action="store_true",
                        help="Jalankan otomatis tanpa konfirmasi interaktif")
    
    args = parser.parse_args()
    
    target_path = Path(args.target_dir)
    backup_path = Path(args.backup_dir)
    
    print("=" * 70)
    print(f" {Colors.CYAN}{Colors.BOLD}AUDIO QUALITY DUPLICATE CHECKER v1.0{Colors.RESET}")
    print("=" * 70)
    print(f" Target Folder : {target_path}")
    if args.delete:
        print(f" Action        : {Colors.RED}PERMANENT DELETE{Colors.RESET}")
    else:
        print(f" Action        : Backup ke {backup_path}")
    print(f" Dry Run       : {args.dry_run}")
    print(f" numpy+sf      : {'OK' if NUMPY_AVAILABLE else 'MISSING (spectral check disabled)'}")
    print(f" mutagen       : {'OK' if MUTAGEN_AVAILABLE else 'MISSING (metadata check disabled)'}")
    print("-" * 70)
    
    if not target_path.exists():
        print(f"{Colors.RED}[ERROR] Folder target tidak ditemukan: {target_path}{Colors.RESET}")
        sys.exit(1)
        
    # Scan files
    print("Scanning folder...")
    all_files = []
    # Scan .flac dan .m4a
    for ext in ("*.flac", "*.m4a"):
        all_files.extend(list(target_path.rglob(ext)))
        
    print(f"Ditemukan {len(all_files)} file audio di disk.")
    
    # Grouping by normalized name
    groups = {}
    for fp in all_files:
        # Abaikan file di dalam folder backup jika folder backup berada di dalam target_dir
        if backup_path.resolve() in fp.resolve().parents:
            continue
        norm = normalize_for_grouping(fp.name)
        if norm:
            groups.setdefault(norm, []).append(fp)
            
    # Filter groups that actually have duplicates
    dup_groups = {k: v for k, v in groups.items() if len(v) > 1}
    
    if not dup_groups:
        print(f"\n{Colors.GREEN}[INFO] Tidak ada duplikat terdeteksi. Folder bersih!{Colors.RESET}\n")
        return
        
    print(f"Terdeteksi {len(dup_groups)} grup duplikat (total {sum(len(v) for v in dup_groups.values())} file).\n")
    print("Menganalisis kualitas audio untuk setiap duplikat...")
    
    # Analyze quality and rank files in each group
    analyzed_groups = []
    for idx, (norm_name, file_list) in enumerate(dup_groups.items(), 1):
        group_entries = []
        for fp in file_list:
            score_tuple = get_file_quality_score(fp)
            group_entries.append({
                "path": fp,
                "score_tuple": score_tuple,
                "display": score_tuple[-1]
            })
            
        # Sort group entries so the best is at the end (max)
        group_entries.sort(key=lambda x: x["score_tuple"][:-1])
        best_entry = group_entries[-1]
        other_entries = group_entries[:-1]
        
        analyzed_groups.append({
            "norm_name": norm_name,
            "best": best_entry,
            "others": other_entries
        })
        
    # Show preview
    print("\n" + "="*70)
    print(f" PREVIEW DUPLIKAT YANG TERDETEKSI")
    print("="*70)
    
    for idx, group in enumerate(analyzed_groups, 1):
        best_fp = group["best"]["path"]
        best_display = group["best"]["display"]
        canonical_name = get_canonical_name(best_fp.name)
        
        print(f"\n[Grup {idx}] Base: {Colors.BOLD}{group['norm_name']}{Colors.RESET}")
        
        # Print the best file (KEEP)
        size_mb = best_fp.stat().st_size / (1024*1024) if best_fp.exists() else 0.0

        print(f"  {Colors.GREEN}[KEEP]{Colors.RESET} {best_fp.name}")
        print(f"         Quality  : {_quality_line(best_display)} | Size: {size_mb:.2f} MB")
        if best_fp.name != canonical_name:
            print(f"         Rename to: {Colors.CYAN}{canonical_name}{Colors.RESET}")
            
        # Print files to remove
        for entry in group["others"]:
            fp = entry["path"]
            size_mb = fp.stat().st_size / (1024*1024) if fp.exists() else 0.0

            action_label = f"{Colors.RED}[DELETE]{Colors.RESET}" if args.delete else f"{Colors.YELLOW}[BACKUP]{Colors.RESET}"
            print(f"  {action_label} {fp.name}")
            print(f"         Quality  : {_quality_line(entry['display'])} | Size: {size_mb:.2f} MB")
            
    print("\n" + "="*70)
    
    if args.dry_run:
        print("[DRY RUN] Selesai. Tidak ada file yang diubah.")
        return
        
    # Ask for confirmation
    if not args.auto:
        confirm = input("Apakah Anda ingin memproses duplikat di atas? (y/N): ").strip().lower()
        if confirm != 'y':
            print("Dibatalkan.")
            return

    # Process files
    if not args.delete and not args.dry_run:
        backup_path.mkdir(parents=True, exist_ok=True)
        
    print("\nMemulai pemrosesan...")
    
    removed_count = 0
    renamed_count = 0
    error_count = 0
    
    for group in analyzed_groups:
        best_entry = group["best"]
        best_fp = best_entry["path"]
        canonical_name = get_canonical_name(best_fp.name)
        
        # 1. Hapus atau backup file duplikat lainnya
        for entry in group["others"]:
            fp = entry["path"]
            try:
                if args.delete:
                    fp.unlink()
                    print(f"  {Colors.RED}[DELETED]{Colors.RESET} {fp.name}")
                else:
                    dest = backup_path / fp.name
                    # Handle jika file backup dengan nama sama sudah ada
                    if dest.exists():
                        dest.unlink()
                    shutil.move(str(fp), str(dest))
                    print(f"  {Colors.YELLOW}[BACKUPED]{Colors.RESET} {fp.name} -> backup")
                removed_count += 1
            except Exception as e:
                print(f"  {Colors.RED}[ERROR]{Colors.RESET} Gagal memproses {fp.name}: {e}")
                error_count += 1
                
        # 2. Rename file terbaik ke nama canonical jika diperlukan dan tidak konflik
        if best_fp.name != canonical_name:
            dest_fp = best_fp.parent / canonical_name
            try:
                if dest_fp.exists() and dest_fp.resolve() != best_fp.resolve():
                    # Jika file canonical ada (sangat jarang jika grouping berjalan sempurna)
                    print(f"  {Colors.YELLOW}[WARN]{Colors.RESET} Tidak bisa rename {best_fp.name} ke {canonical_name} karena file target sudah ada.")
                else:
                    best_fp.rename(dest_fp)
                    print(f"  {Colors.GREEN}[RENAMED]{Colors.RESET} {best_fp.name} -> {canonical_name}")
                    renamed_count += 1
            except Exception as e:
                print(f"  {Colors.RED}[ERROR]{Colors.RESET} Gagal merename {best_fp.name} ke {canonical_name}: {e}")
                error_count += 1
                
    print("\n" + "="*70)
    print(f" {Colors.GREEN}{Colors.BOLD}PROSES SELESAI{Colors.RESET}")
    print("="*70)
    action_verb = "dihapus" if args.delete else "di-backup"
    print(f" Total file {action_verb} : {removed_count}")
    print(f" Total file di-rename    : {renamed_count}")
    print(f" Total error             : {error_count}")
    print("="*70)

if __name__ == "__main__":
    main()
