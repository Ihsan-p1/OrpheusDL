"""Cek rename_to_original: pengganti mendarat di tempat dan nama file lama."""
import os
import tempfile

from orpheus_healer import rename_to_original


def test():
    with tempfile.TemporaryDirectory() as d:
        library = os.path.join(d, "Library")
        singgah = os.path.join(d, "_HEAL_STAGING")
        os.makedirs(library)
        os.makedirs(singgah)

        old = os.path.join(library, "Artis - Lagu Lama.flac")
        new = os.path.join(singgah, "01 Lagu (Remaster).m4a")
        open(new, "w").close()
        open(os.path.splitext(new)[0] + ".lrc", "w").close()

        # Pindah ke folder file lama, stem ikut yang lama, ekstensi ikut yang
        # baru, lirik ikut.
        hasil = rename_to_original(new, old)
        assert hasil == os.path.join(library, "Artis - Lagu Lama.m4a"), hasil
        assert os.path.exists(hasil)
        assert os.path.exists(os.path.join(library, "Artis - Lagu Lama.lrc"))
        assert not os.path.exists(new)

        # Sudah di tempat dan nama yang benar: tidak ada kerja.
        assert rename_to_original(hasil, hasil) == hasil

        # Nama tujuan sudah terpakai: file unduhan dibiarkan, yang lama tidak
        # ditimpa.
        lain = os.path.join(singgah, "unduhan baru.m4a")
        open(lain, "w").close()
        assert rename_to_original(lain, old) == lain
        assert os.path.exists(lain)

        # File hilang atau argumen kosong: kembalikan apa adanya.
        assert rename_to_original(os.path.join(singgah, "hantu.flac"), old).endswith("hantu.flac")
        assert rename_to_original("", old) == ""

    print("test_rename_to_original OK")


if __name__ == "__main__":
    test()
