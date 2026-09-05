"""Satukan lagu yang punya lebih dari satu file di G:\\Music\\Library.

check_duplicates.py mencocokkan nama file, jadi satu lagu yang tersimpan
sebagai "Peace Sign.flac" dan "Geek Music - My Hero Academia - Peace Sign -
Season 2 Opening Theme.flac" lolos. Pengelompokan di sini pakai tag artist dan
title, yang sama di kedua file itu.

Yang disimpan: berprovenance dulu, lalu bit depth, sample rate, ukuran. Yang
kalah dipindah ke _FAKE_BACKUP, tidak dihapus. Playlist ditulis ulang supaya
entrinya menunjuk file yang disimpan.

File hanya dilepas kalau MD5 audio mentahnya sama dengan yang disimpan. FLAC
menyimpan MD5 itu sendiri di blok STREAMINFO, jadi kesamaan isi bisa dibuktikan
sampel per sampel, bukan disimpulkan dari nama, durasi, atau ukuran. Grup yang
MD5 anggotanya berbeda dilaporkan dan dibiarkan utuh: durasi boleh sama persis
sementara isinya master yang berbeda.

    python tools_dupes_by_tag.py            # laporan saja
    python tools_dupes_by_tag.py --apply    # pindahkan dan tulis ulang playlist
"""
import collections
import os
import re
import shutil
import sys
import unicodedata
from datetime import datetime

import mutagen
from mutagen.flac import FLAC

from orpheus.provenance import read_provenance

LIBRARY = r"G:\Music\Library"
PLAYLISTS = r"G:\Music\Playlists"
BACKUP = r"G:\Music\_FAKE_BACKUP"
AUDIO = (".flac", ".m4a", ".mp3")


# Tanda baca kana. Ikut dibuang bersama aksen lain, "が" jadi "か" dan itu kata
# yang berbeda, jadi keduanya dikecualikan dari pelipatan.
KANA_SUARA = {"\u3099", "\u309a"}


def normal(s):
    """Kecilkan huruf, lipat aksen, satukan pemisah jadi spasi.

    \W dengan flag unicode, bukan [^a-z0-9]: judul Jepang habis kalau non-ASCII
    ikut dibuang, dan semua judul CJK menyatu jadi satu grup palsu.

    Aksen dilipat karena tag dan katalog sering menulis nama yang sama dengan
    huruf berbeda: "JAŸ-Z" untuk "JAY-Z", "Bouwéy" untuk "Bouwey".
    """
    urai = unicodedata.normalize("NFKD", s.lower())
    tanpa_aksen = "".join(c for c in urai
                          if unicodedata.category(c) != "Mn" or c in KANA_SUARA)
    # Disusun ulang supaya tanda suara menempel lagi ke kananya; kalau dibiarkan
    # terpisah, \W+ mengubahnya jadi spasi dan memotong satu huruf jadi dua.
    rapat = unicodedata.normalize("NFC", tanpa_aksen)
    return re.sub(r"\W+", " ", rapat, flags=re.UNICODE).strip()


def kunci(tags):
    """(artist, title) yang sudah dinormalisasi, atau None kalau judulnya kosong."""
    artist = (tags.get("artist") or tags.get("albumartist") or [""])[0]
    title = (tags.get("title") or [""])[0]
    bersih = (normal(artist), normal(title))
    return bersih if bersih[1] else None


def md5_audio(path):
    """MD5 audio mentah dari STREAMINFO, atau None kalau bukan FLAC."""
    try:
        return FLAC(path).info.md5_signature or None
    except Exception:
        return None


def peringkat(berkas):
    """Kunci urut: makin besar makin layak disimpan."""
    return (berkas["provenance"] is not None, berkas["bits"],
            berkas["rate"], berkas["size"])


def pilah(files):
    """Bagi satu grup jadi (yang disimpan, yang dilepas, yang dibiarkan).

    Yang dilepas hanya file yang MD5 audionya sama persis dengan yang disimpan.
    Tanpa MD5, misalnya pada m4a dan mp3, tidak ada bukti isinya sama, jadi
    tidak ada yang dilepas.
    """
    files = sorted(files, key=peringkat, reverse=True)
    simpan = files[0]
    kembaran = [f for f in files[1:]
                if simpan["md5"] is not None and f["md5"] == simpan["md5"]]
    lain = [f for f in files[1:] if f not in kembaran]
    return simpan, kembaran, lain


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
            "md5": md5_audio(path),
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
        simpan, kembaran, lain = pilah(files)
        if kembaran:
            print(f"\n[{artist} - {title}]")
            print(f"  SIMPAN {simpan['nama']}")
            for f in kembaran:
                print(f"  LEPAS  {f['nama']}  ({f['size'] / 1048576:.1f} MB)")
                ganti[f["nama"]] = simpan["nama"]
                lepas.append(f)
                bytes_lepas += f["size"]
        if lain:
            dilewati.append((artist, title, [simpan] + lain if not kembaran else lain))

    for artist, title, files in dilewati:
        print(f"\n[DIBIARKAN audio berbeda] {artist} - {title}")
        for f in files:
            print(f"  {f['nama']}  ({f['durasi']:.1f} detik, {f['bits']}bit/{f['rate']}Hz)")

    print(f"\n{len(kembar)} grup kembar, {len(dilewati)} dibiarkan karena audionya "
          f"berbeda, {len(lepas)} file dilepas, {bytes_lepas / 1048576:.0f} MB.")

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
