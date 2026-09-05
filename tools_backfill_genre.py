"""Isi tag genre yang kosong dari iTunes Search API.

Modul tidal tidak pernah menulis genre, jadi 1385 dari 1459 file di
G:\\Music\\Library tidak punya. Yang 73 file punya datang dari modul applemusic,
yang membacanya dari genreNames — kosakata yang sama dipakai di sini supaya
library tidak jadi campur aduk.

Kecocokan harus tegas: judul sama persis setelah dinormalisasi, dan nama artis
sama utuh — bukan sekadar termuat, karena "Artis" termuat di "Artis Lain".
Yang tidak cocok dicatat, tagnya tidak disentuh: genre yang salah lebih
merepotkan daripada genre yang kosong.

    python tools_backfill_genre.py            # laporan saja
    python tools_backfill_genre.py --apply    # tulis tag genre
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


# Kata sambung antar nama artis. Dibuang dari kedua sisi supaya "Yovie & Nuno"
# dan "Yovie and Nuno" dibaca sama.
SAMBUNG = {"and", "dan", "with", "feat", "featuring", "ft", "x", "vs"}


def cocok_artis(tag, katalog):
    """Nama artis di tag dan di katalog menunjuk orang yang sama.

    Substring terlalu longgar: "Artis" termuat di "Artis Lain", padahal itu dua
    orang. Yang diterima hanya dua hal — nama lengkapnya sama, atau nama di
    katalog sama dengan salah satu artis yang didaftar tag (tag sering menulis
    artis tamu, katalog Apple hanya yang utama).
    """
    def token(s):
        return tuple(w for w in normal(s).split() if w not in SAMBUNG)

    k = token(katalog)
    if not k:
        return False
    if k == token(tag):
        return True
    return any(k == token(bagian) for bagian in re.split(r"[;,&/]|feat", tag))


def pilih(hasil, artist, title):
    """Genre dari kandidat yang judul dan artisnya cocok, atau None.

    `hasil` adalah daftar entri mentah dari API.
    """
    t = normal(title)
    a = normal(artist)
    for r in hasil:
        if normal(r.get("trackName", "")) != t:
            continue
        if a and cocok_artis(artist, r.get("artistName", "")):
            return r.get("primaryGenreName") or None
    return None


def cari(artist, title, cache):
    """Genre untuk satu lagu. Jawaban API disimpan supaya tidak ditembak dua kali."""
    kunci_cache = f"{artist}|{title}"
    if kunci_cache in cache:
        return cache[kunci_cache]
    query = urllib.parse.urlencode({
        "term": f"{artist} {title}", "entity": "song", "limit": 5, "country": "US"})
    try:
        with urllib.request.urlopen(f"{API}?{query}", timeout=20) as resp:
            hasil = json.load(resp).get("results", [])
    except Exception as e:
        print(f"  [API-ERR] {artist} - {title}: {e}")
        return None
    genre = pilih(hasil, artist, title)
    cache[kunci_cache] = genre
    time.sleep(JEDA)
    return genre


def main():
    apply = "--apply" in sys.argv
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
            genre = cari(artist, title, cache)
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
