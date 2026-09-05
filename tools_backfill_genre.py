"""Isi tag genre yang kosong dari iTunes Search API, lalu Deezer.

Modul tidal tidak pernah menulis genre, jadi 1385 dari 1459 file di
G:\\Music\\Library tidak punya. Yang 73 file punya datang dari modul applemusic,
yang membacanya dari genreNames — kosakata yang sama dipakai di sini supaya
library tidak jadi campur aduk.

Kecocokan harus tegas: judul sama persis setelah dinormalisasi, dan nama artis
sama utuh — bukan sekadar termuat, karena "Artis" termuat di "Artis Lain".
Yang tidak cocok dicatat, tagnya tidak disentuh: genre yang salah lebih
merepotkan daripada genre yang kosong.

    python tools_backfill_genre.py                 # laporan saja
    python tools_backfill_genre.py --apply         # tulis tag genre
    python tools_backfill_genre.py --apply --ulang-gagal   # tanya ulang yang gagal
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

import mutagen

from tools_dupes_by_tag import normal

LIBRARY = r"G:\Music\Library"
AUDIO = (".flac", ".m4a", ".mp3")
CACHE = "genre_cache.json"
TAK_KETEMU = "genre_tak_ketemu.txt"
# iTunes Search API tanpa kunci dibatasi sekitar 20 permintaan per menit.
JEDA = 3.0
API = "https://itunes.apple.com/search"
DEEZER = "https://api.deezer.com"
# Deezer memakai istilah sendiri. Yang berbeda dipetakan ke istilah Apple supaya
# satu library tidak memakai dua sistem penamaan.
PETA_DEEZER = {
    "Rap/Hip Hop": "Hip-Hop/Rap",
    "R&B": "R&B/Soul",
    "Electro": "Electronic",
    "Films/Games": "Soundtrack",
    "Musique brésilienne": "Brazilian",
    "Musiques du monde": "Worldwide",
}
# Katalog US tidak memuat sebagian rilis Indonesia, Jepang, dan Mandarin.
NEGARA = ("US", "ID", "JP")


# Kata sambung antar nama artis. Dibuang dari kedua sisi supaya "Yovie & Nuno"
# dan "Yovie and Nuno" dibaca sama.
SAMBUNG = {"and", "dan", "with", "feat", "featuring", "ft", "x", "vs"}


def bagian_artis(s):
    """Nama-nama artis dalam satu string, masing-masing sebagai tuple kata."""
    keluar = set()
    for bagian in re.split(r"[;,&/]|\bfeat\b|\bwith\b", s, flags=re.IGNORECASE):
        token = tuple(w for w in normal(bagian).split() if w not in SAMBUNG)
        if token:
            keluar.add(token)
    token = tuple(w for w in normal(s).split() if w not in SAMBUNG)
    if token:
        keluar.add(token)
    return keluar


def cocok_artis(tag, katalog):
    """Nama artis di tag dan di katalog menunjuk orang yang sama.

    Kedua sisi dipecah, lalu dicari satu nama yang sama utuh. Keduanya perlu
    dipecah karena tag dan katalog tidak sepakat siapa yang didaftar: tag
    menulis "Zhou Shen; HOYO-MiX" untuk yang katalognya "Zhou Shen", tapi
    katalog menulis "CHiCO with HoneyWorks" untuk yang tagnya "CHiCO".

    Pencocokan menuntut nama yang utuh sama, bukan termuat. "Artis" termuat di
    "Artis Lain", padahal itu dua orang.
    """
    return bool(bagian_artis(tag) & bagian_artis(katalog))


def bagian_judul(s):
    """Judul apa adanya, dan judul tanpa ekor dalam kurung.

    Tag dan katalog tidak sepakat menaruh keterangan versi: satu menulis
    "Dia Milikku (Album Version)" untuk yang lain menulis "Dia Milikku".
    """
    penuh = normal(s)
    pendek = normal(re.sub(r"[\(\[].*", " ", s))
    return {x for x in (penuh, pendek) if x}


def pilih(hasil, artist, title):
    """Genre dari kandidat yang judul dan artisnya cocok, atau None.

    `hasil` adalah daftar entri mentah dari API.
    """
    t = bagian_judul(title)
    for r in hasil:
        if not (t & bagian_judul(r.get("trackName", ""))):
            continue
        if normal(artist) and cocok_artis(artist, r.get("artistName", "")):
            return r.get("primaryGenreName") or None
    return None


def tanya(artist, title, negara):
    """Hasil mentah API untuk satu wilayah katalog."""
    query = urllib.parse.urlencode({
        "term": f"{artist} {title}", "entity": "song", "limit": 5, "country": negara})
    try:
        with urllib.request.urlopen(f"{API}?{query}", timeout=20) as resp:
            hasil = json.load(resp).get("results", [])
    except Exception as e:
        print(f"  [API-ERR] {artist} - {title}: {e}")
        hasil = []
    time.sleep(JEDA)
    return hasil


def tanya_deezer(artist, title):
    """Genre dari Deezer, atau None.

    Katalog Deezer memuat rilis Indonesia dan Jepang yang tidak ada di Apple.
    Genre-nya menempel di album, bukan di lagu, jadi perlu dua permintaan.
    """
    query = urllib.parse.urlencode({"q": f"{artist} {title}", "limit": 5})
    try:
        with urllib.request.urlopen(f"{DEEZER}/search?{query}", timeout=20) as resp:
            hasil = json.load(resp).get("data", [])
    except Exception as e:
        print(f"  [DEEZER-ERR] {artist} - {title}: {e}")
        return None

    t = bagian_judul(title)
    for r in hasil:
        if not (t & bagian_judul(r.get("title", ""))):
            continue
        if not cocok_artis(artist, (r.get("artist") or {}).get("name", "")):
            continue
        album = (r.get("album") or {}).get("id")
        if not album:
            continue
        try:
            with urllib.request.urlopen(f"{DEEZER}/album/{album}", timeout=20) as resp:
                genre = json.load(resp).get("genres") or {}
        except Exception as e:
            print(f"  [DEEZER-ERR] album {album}: {e}")
            return None
        nama = [g["name"] for g in genre.get("data", []) if g.get("name")]
        if nama:
            return PETA_DEEZER.get(nama[0], nama[0])
    return None


def cari(artist, title, cache, ulang_gagal=False):
    """Genre untuk satu lagu. Jawaban API disimpan supaya tidak ditembak dua kali."""
    kunci_cache = f"{artist}|{title}"
    if kunci_cache in cache and not (ulang_gagal and cache[kunci_cache] is None):
        return cache[kunci_cache]
    genre = None
    for negara in NEGARA:
        hasil = tanya(artist, title, negara)
        genre = pilih(hasil, artist, title)
        if genre:
            break
        # Wilayah lain hanya dicoba kalau katalog US memang tidak punya lagunya.
        # Kalau lagunya ada tapi ditolak, mengulang di wilayah lain sia-sia.
        if hasil:
            break
    if not genre:
        genre = tanya_deezer(artist, title)
        time.sleep(0.3)
    cache[kunci_cache] = genre
    return genre


def main():
    apply = "--apply" in sys.argv
    ulang_gagal = "--ulang-gagal" in sys.argv
    cache = json.load(open(CACHE, encoding="utf-8")) if os.path.exists(CACHE) else {}

    kosong = []
    for nama in sorted(os.listdir(LIBRARY)):
        path = os.path.join(LIBRARY, nama)
        if not (os.path.isfile(path) and nama.lower().endswith(AUDIO)):
            continue
        try:
            tags = mutagen.File(path, easy=True)
        except Exception:
            continue
        if not tags or (tags.get("genre") or [""])[0].strip():
            continue
        artist = (tags.get("artist") or tags.get("albumartist") or [""])[0]
        title = (tags.get("title") or [""])[0]
        if artist and title:
            kosong.append((path, artist, title))

    print(f"{len(kosong)} file tanpa genre. Perkiraan {len(kosong) * JEDA / 60:.0f} menit.\n")

    ketemu, gagal = 0, []
    try:
        for i, (path, artist, title) in enumerate(kosong, 1):
            genre = cari(artist, title, cache, ulang_gagal)
            if genre:
                ketemu += 1
                print(f"[{i}/{len(kosong)}] {artist} - {title} -> {genre}")
                if apply:
                    tags = mutagen.File(path, easy=True)
                    tags["genre"] = genre
                    tags.save()
            else:
                gagal.append(f"{artist} - {title}")
                print(f"[{i}/{len(kosong)}] {artist} - {title} -> tidak ketemu")
    finally:
        # Cache ditulis apa pun yang terjadi, supaya jalan ulang tidak menembak
        # API dari nol lagi.
        with open(CACHE, "w", encoding="utf-8") as fh:
            json.dump(cache, fh, ensure_ascii=False, indent=1)
        with open(TAK_KETEMU, "w", encoding="utf-8") as fh:
            fh.write("\n".join(gagal) + "\n")

    print(f"\n{ketemu} ketemu, {len(gagal)} tidak. Daftar tak ketemu: {TAK_KETEMU}")
    if not apply:
        print("Laporan saja. Jalankan dengan --apply untuk menulis tag.")


if __name__ == "__main__":
    main()
