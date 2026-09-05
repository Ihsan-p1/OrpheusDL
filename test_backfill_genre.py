"""Cek pemilihan kandidat dari respons iTunes. Tanpa jaringan."""
from tools_backfill_genre import pilih


def r(artist, track, genre="Pop"):
    return {"artistName": artist, "trackName": track, "primaryGenreName": genre}


def test_cocok_persis():
    assert pilih([r("Hivi!", "Pelangi", "Indie Pop")], "Hivi!", "Pelangi") == "Indie Pop"


def test_tanda_baca_diabaikan():
    # Tag "Yovie & Nuno", katalog "Yovie and Nuno" — sama setelah dinormalisasi.
    assert pilih([r("Yovie and Nuno", "Merindu Lagi")],
                 "Yovie & Nuno", "Merindu Lagi") == "Pop"


def test_artis_tamu_di_tag():
    # Tag menulis semua artis, katalog hanya yang utama.
    assert pilih([r("Zhou Shen", "Rubia", "Soundtrack")],
                 "Zhou Shen; HOYO-MiX", "Rubia") == "Soundtrack"


def test_judul_beda_ditolak():
    assert pilih([r("Hivi!", "Pelangi Lain")], "Hivi!", "Pelangi") is None


def test_artis_beda_ditolak():
    # Judul sama, artis lain: justru kasus yang bikin lagu ketukar.
    assert pilih([r("The Walters", "Make You Mine")],
                 "GIVEON", "Make You Mine") is None


def test_kandidat_pertama_yang_cocok_dipakai():
    hasil = [r("Artis Lain", "Lagu", "Rock"), r("Artis", "Lagu", "Jazz")]
    assert pilih(hasil, "Artis", "Lagu") == "Jazz"


def test_kosong():
    assert pilih([], "Artis", "Lagu") is None
    assert pilih([r("", "Lagu")], "Artis", "Lagu") is None
    # Genre kosong di katalog bukan jawaban.
    assert pilih([r("Artis", "Lagu", "")], "Artis", "Lagu") is None


if __name__ == "__main__":
    for nama, fn in sorted(globals().items()):
        if nama.startswith("test_"):
            fn()
            print("PASS", nama)
