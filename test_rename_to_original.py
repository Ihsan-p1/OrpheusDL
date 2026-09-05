"""Cek rename_to_original: nama lama dipakai lagi, tabrakan tidak menimpa."""
import os
import tempfile

from orpheus_healer import rename_to_original


def test():
    with tempfile.TemporaryDirectory() as d:
        old = os.path.join(d, "Artis - Lagu Lama.flac")
        new = os.path.join(d, "01 Lagu (Remaster).m4a")
        open(new, "w").close()
        open(os.path.splitext(new)[0] + ".lrc", "w").close()

        # Ekstensi ikut file baru, stem ikut file lama, lirik ikut pindah.
        hasil = rename_to_original(new, old)
        assert hasil == os.path.join(d, "Artis - Lagu Lama.m4a"), hasil
        assert os.path.exists(hasil)
        assert os.path.exists(os.path.join(d, "Artis - Lagu Lama.lrc"))
        assert not os.path.exists(new)

        # Nama sama = tidak ada kerja.
        assert rename_to_original(hasil, hasil) == hasil

        # Target sudah ada: file unduhan dibiarkan, yang lama tidak ditimpa.
        lain = os.path.join(d, "unduhan baru.m4a")
        open(lain, "w").close()
        assert rename_to_original(lain, old) == lain
        assert os.path.exists(lain)

        # File hilang / argumen kosong: kembalikan apa adanya.
        assert rename_to_original(os.path.join(d, "hantu.flac"), old).endswith("hantu.flac")
        assert rename_to_original("", old) == ""

    print("test_rename_to_original OK")


if __name__ == "__main__":
    test()
