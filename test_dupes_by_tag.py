"""Cek aturan penyimpan dan penulisan ulang playlist."""
from tools_dupes_by_tag import kunci, normal, peringkat, pilah, tulis_ulang


def test_kunci():
    assert kunci({"artist": ["Hivi!"], "title": ["Pelangi"]}) == ("hivi", "pelangi")
    # Judul Jepang tidak boleh habis jadi string kosong.
    assert kunci({"artist": ["YOASOBI"], "title": ["たぶん"]})[1] == "たぶん"
    # Tanpa judul tidak bisa dikelompokkan.
    assert kunci({"artist": ["X"], "title": [""]}) is None
    # albumartist dipakai kalau artist kosong.
    assert kunci({"albumartist": ["Yura"], "title": ["Jalan Pulang"]})[0] == "yura"


def test_normal_lipat_aksen():
    # Tag dan katalog menulis nama yang sama dengan huruf berbeda.
    assert normal("JAŸ-Z") == normal("JAY-Z")
    assert normal("Bouwéy") == normal("Bouwey")
    assert normal("Devil\u2019s Dance") == normal("Devil's Dance")


def test_normal_jaga_tanda_suara_kana():
    # "が" tidak boleh runtuh jadi "か": itu kata yang berbeda.
    assert normal("がっこう") != normal("かっこう")
    assert normal("がっこう") == "がっこう"


def berkas(prov=None, bits=16, rate=44100, size=1, md5=1):
    return {"provenance": prov, "bits": bits, "rate": rate, "size": size, "md5": md5}


def test_pilah_hanya_lepas_yang_md5_sama():
    kembar = berkas(size=1, md5=7)
    beda = berkas(size=2, md5=8)
    simpan, dilepas, dibiarkan = pilah([berkas(size=9, md5=7), kembar, beda])
    assert simpan["size"] == 9
    assert dilepas == [kembar]
    assert dibiarkan == [beda]


def test_pilah_tanpa_md5_tidak_melepas_apa_pun():
    # m4a dan mp3 tidak menyimpan MD5 audio, jadi tidak ada bukti isinya sama.
    a, b = berkas(size=9, md5=None), berkas(size=1, md5=None)
    simpan, dilepas, dibiarkan = pilah([a, b])
    assert simpan is a
    assert dilepas == []
    assert dibiarkan == [b]


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
    test_normal_lipat_aksen()
    test_normal_jaga_tanda_suara_kana()
    test_peringkat()
    test_pilah_hanya_lepas_yang_md5_sama()
    test_pilah_tanpa_md5_tidak_melepas_apa_pun()
    test_tulis_ulang()
    print("test_dupes_by_tag OK")
