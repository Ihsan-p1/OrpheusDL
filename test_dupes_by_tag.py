"""Cek aturan penyimpan dan penulisan ulang playlist."""
from tools_dupes_by_tag import kunci, peringkat, tulis_ulang


def test_kunci():
    assert kunci({"artist": ["Hivi!"], "title": ["Pelangi"]}) == ("hivi", "pelangi")
    # Judul Jepang tidak boleh habis jadi string kosong.
    assert kunci({"artist": ["YOASOBI"], "title": ["たぶん"]})[1] == "たぶん"
    # Tanpa judul tidak bisa dikelompokkan.
    assert kunci({"artist": ["X"], "title": [""]}) is None
    # albumartist dipakai kalau artist kosong.
    assert kunci({"albumartist": ["Yura"], "title": ["Jalan Pulang"]})[0] == "yura"


def berkas(prov=None, bits=16, rate=44100, size=1):
    return {"provenance": prov, "bits": bits, "rate": rate, "size": size}


def test_peringkat():
    # Provenance menang meski file lebih kecil dan bit depth lebih rendah.
    prov = berkas(prov="tidal")
    besar = berkas(bits=24, rate=96000, size=999)
    assert max([besar, prov], key=peringkat) is prov
    # Tanpa provenance, bit depth di atas sample rate dan ukuran.
    assert max([berkas(bits=16, rate=96000, size=999),
                berkas(bits=24, rate=44100, size=1)], key=peringkat)["bits"] == 24
    # Bit depth dan sample rate sama, ukuran yang menentukan.
    assert max([berkas(size=5), berkas(size=9)], key=peringkat)["size"] == 9


def test_tulis_ulang():
    baris = ["#EXTM3U", "../Library/Judul.flac", "../Library/Artis - Judul.flac",
             "../Library/Lain.flac", ""]
    hasil = tulis_ulang(baris, {"Artis - Judul.flac": "Judul.flac"})
    # Dua entri jadi menunjuk file yang sama, sisakan satu, urutan tetap.
    assert hasil == ["#EXTM3U", "../Library/Judul.flac", "../Library/Lain.flac", ""]
    # Tanpa pemetaan, isi playlist tidak berubah.
    assert tulis_ulang(baris, {}) == baris


if __name__ == "__main__":
    test_kunci()
    test_peringkat()
    test_tulis_ulang()
    print("test_dupes_by_tag OK")
