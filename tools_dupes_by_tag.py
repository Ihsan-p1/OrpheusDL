"""Satukan lagu yang punya lebih dari satu file di G:\\Music\\Library.

check_duplicates.py mencocokkan nama file, jadi satu lagu yang tersimpan
sebagai "Peace Sign.flac" dan "Geek Music - My Hero Academia - Peace Sign -
Season 2 Opening Theme.flac" lolos. Pengelompokan di sini pakai tag artist dan
title, yang sama di kedua file itu.

Yang disimpan: berprovenance dulu, lalu bit depth, sample rate, ukuran. Yang
kalah dipindah ke _FAKE_BACKUP, tidak dihapus. Playlist ditulis ulang supaya
entrinya menunjuk file yang disimpan.

Grup yang durasi anggotanya berbeda lebih dari dua detik dilewati: itu versi
yang berbeda, bukan salinan.

    python tools_dupes_by_tag.py            # laporan saja
    python tools_dupes_by_tag.py --apply    # pindahkan dan tulis ulang playlist
"""
import collections
import os
import re
import shutil
import sys
from datetime import datetime

import mutagen

from orpheus.provenance import read_provenance

LIBRARY = r"G:\Music\Library"
PLAYLISTS = r"G:\Music\Playlists"
BACKUP = r"G:\Music\_FAKE_BACKUP"
AUDIO = (".flac", ".m4a", ".mp3")
BEDA_DURASI_MAKS = 2.0


def kunci(tags):
    """(artist, title) yang sudah dinormalisasi, atau None kalau judulnya kosong."""
    artist = (tags.get("artist") or tags.get("albumartist") or [""])[0]
    title = (tags.get("title") or [""])[0]
    # \W dengan flag unicode, bukan [^a-z0-9]: judul Jepang habis kalau non-ASCII
    # ikut dibuang, dan semua judul CJK menyatu jadi satu grup palsu.
    bersih = tuple(re.sub(r"\W+", " ", s.lower(), flags=re.UNICODE).strip()
                   for s in (artist, title))
    return bersih if bersih[1] else None


def peringkat(berkas):
    """Kunci urut: makin besar makin layak disimpan."""
    return (berkas["provenance"] is not None, berkas["bits"],
            berkas["rate"], berkas["size"])


def kumpulkan(library):
    """Kelompokkan file audio per (artist, title)."""
    grup = collections.defaultdict(list)
    for nama in sorted(os.listdir(library)):
        path = os.path.join(library, nama)
        if not (os.path.isfile(path) and nama.lower().endswith(AUDIO)):
            continue
        try:
            tags = mutagen.File(path, easy=True)
        except Exception:
            continue
        if not tags:
            continue
        k = kunci(tags)
        if not k:
            continue
        grup[k].append({
            "nama": nama, "path": path,
            "provenance": read_provenance(path),
            "bits": getattr(tags.info, "bits_per_sample", 0),
            "rate": getattr(tags.info, "sample_rate", 0),
            "size": os.path.getsize(path),
            "durasi": tags.info.length,
        })
    return grup


def tulis_ulang(baris, ganti):
    """Petakan entri playlist ke file yang disimpan, buang entri kembar.

    `ganti` memetakan nama file yang dilepas ke nama file penggantinya. Urutan
    entri dipertahankan; entri yang jadi sama setelah dipetakan hanya disisakan
    satu.
    """
    keluar, terlihat = [], set()
    for b in baris:
        s = b.strip()
        if not s or s.startswith("#"):
            keluar.append(b)
            continue
        induk, nama = os.path.split(s)
        nama = ganti.get(nama, nama)
        entri = f"{induk}/{nama}" if induk else nama
        if entri not in terlihat:
            terlihat.add(entri)
            keluar.append(entri)
    return keluar


def main():
    apply = "--apply" in sys.argv
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    kembar = {k: v for k, v in kumpulkan(LIBRARY).items() if len(v) > 1}

    ganti, lepas, bytes_lepas, dilewati = {}, [], 0, []
    for (artist, title), files in sorted(kembar.items()):
        durasi = [f["durasi"] for f in files]
        if max(durasi) - min(durasi) > BEDA_DURASI_MAKS:
            dilewati.append((artist, title, files))
            continue
        files.sort(key=peringkat, reverse=True)
        simpan, sisa = files[0], files[1:]
        print(f"\n[{artist} - {title}]")
        print(f"  SIMPAN {simpan['nama']}")
        for f in sisa:
            print(f"  LEPAS  {f['nama']}  ({f['size'] / 1048576:.1f} MB)")
            ganti[f["nama"]] = simpan["nama"]
            lepas.append(f)
            bytes_lepas += f["size"]

    for artist, title, files in dilewati:
        print(f"\n[DILEWATI durasi beda] {artist} - {title}")
        for f in files:
            print(f"  {f['nama']}  ({f['durasi']:.0f} detik)")

    print(f"\n{len(kembar)} grup kembar, {len(dilewati)} dilewati, "
          f"{len(lepas)} file dilepas, {bytes_lepas / 1048576:.0f} MB.")

    if not apply:
        print("\nLaporan saja. Jalankan dengan --apply untuk memindahkan.")
        return

    os.makedirs(BACKUP, exist_ok=True)
    pindah = 0
    for f in lepas:
        base, ext = os.path.splitext(f["nama"])
        shutil.move(f["path"], os.path.join(BACKUP, f"{base}_kembar_{stamp}{ext}"))
        lirik = os.path.splitext(f["path"])[0] + ".lrc"
        if os.path.exists(lirik):
            shutil.move(lirik, os.path.join(BACKUP, f"{base}_kembar_{stamp}.lrc"))
        pindah += 1

    arsip = os.path.join(PLAYLISTS, f"sumber_{stamp}")
    os.makedirs(arsip, exist_ok=True)
    for nama in sorted(os.listdir(PLAYLISTS)):
        path = os.path.join(PLAYLISTS, nama)
        if not (os.path.isfile(path) and nama.lower().endswith(".m3u8")):
            continue
        shutil.copy2(path, os.path.join(arsip, nama))
        with open(path, encoding="utf-8") as fh:
            baris = fh.read().splitlines()
        baru = tulis_ulang(baris, ganti)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(baru) + "\n")
        print(f"  [PLAYLIST] {nama}: {len(baris)} entri -> {len(baru)}")

    print(f"\n{pindah} file dipindah ke {BACKUP}. Playlist lama disalin ke {arsip}.")


if __name__ == "__main__":
    main()
