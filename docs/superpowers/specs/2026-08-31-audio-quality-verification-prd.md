# PRD: Sistem verifikasi kualitas audio

Tanggal: 2026-08-31
Status: draft, menunggu review
Repo: OrpheusDL-master (fork)

## Latar belakang

Pipeline sekarang menilai keaslian file lewat `analyze_flac_quality()` di `orpheus_healer.py`. Pengukuran terhadap fungsi itu menunjukkan tiga hal:

1. Dari 12 file ground-truth yang dibuat dengan ffmpeg (FLAC asli, dikonversi ke AAC/MP3/Opus, lalu dibungkus balik jadi FLAC), 12 lolos sebagai lossless. Termasuk MP3 128 kbps. Penyebabnya ada di `orpheus_healer.py:914`: rentang pengukuran slope diturunkan dari `cutoff_hz` dan dibatasi `cutoff_hz * 0.98`, jadi jendela pengukuran selalu berada di bawah tebing encoder dan tak pernah menyentuhnya.
2. Verdict berubah tergantung posisi jendela FFT. Pada sampel 12 file, 4 file ganti verdict ketika jendela digeser antara 15% dan 85% durasi track.
3. Threshold di `_THRESHOLDS` (92 / 72 / -4.5 / 62) tidak punya catatan asal, tidak punya test set, dan tidak punya angka error rate.

Kosakata verdict yang dipakai dicomot dari kolom Verdict ekspor Soniq Tools, tapi tanpa dua sumbu bukti yang dipakai Soniq (Crest Factor dan Clipping). Salah satu label, "Natural Rolloff (Vintage Recording)", tidak pernah muncul sekali pun di empat ekspor Soniq yang ada di repo ini. Label itu buatan kode ini sendiri, dan label itulah yang meloloskan 12 file palsu tadi. Kecocokan verdict antara kedua tool, pada 120 file yang ada di CSV sekaligus ada di disk, adalah 54,2%.

Ada juga batas fisik yang tak bisa dilewati tool mana pun: AAC 256 kbps ke atas tidak menyisakan artefak spektral. Deviasi rata-rata terhadap sumber cuma 0,12 sampai 0,23 dB di semua pita frekuensi, dan cutoff-nya identik di ambang -60, -80, -100, dan -120 dB. Spektrogram file asli dan hasil transcode AAC 256 tidak bisa dibedakan mata. Untuk modul Apple Music yang menyajikan AAC 256, analisis spektral tidak bisa membuktikan apa pun.

## Tujuan

Ganti sistem verdict yang menebak dengan sistem yang cuma melaporkan apa yang benar-benar bisa dibuktikan, dan mengaku tidak tahu untuk sisanya.

Ukuran keberhasilan:

- Semua file palsu di set ground-truth pada 192 kbps ke bawah terdeteksi.
- Tidak ada file asli di set ground-truth yang salah dituduh.
- Verdict tidak berubah kalau analisis diulang pada file yang sama.
- Setiap file hasil download baru punya catatan asal yang bisa dibaca ulang tanpa menganalisis audionya.

## Bukan tujuan

- Mendeteksi AAC 256 kbps ke atas. Tidak mungkin secara spektral, jadi tidak dijanjikan.
- Menyapu ulang 2037 file di `F:\sorted`. File lama tidak disentuh kecuali detektor menemukan bukti keras.
- Mengganti Adobe Audition atau Soniq Tools. Keduanya tetap dipakai manusia untuk memutus kasus sengketa.
- Mengejar rasio 85% FLAC / 15% ALAC. Itu pekerjaan terpisah, walau PRD ini membuka jalannya lewat perbaikan config.

## Prinsip

Provenance adalah bukti utama. Kalau kita tahu file diunduh dari modul mana, dengan tier apa, dan codec apa yang dikirim server, tidak ada gunanya menebak lewat FFT.

Analisis sinyal cuma pelengkap, dan cuma untuk hal yang bisa diukur ulang dengan hasil sama. Sisanya dijawab "tidak diketahui". Status "tidak diketahui" bukan kegagalan sistem, itu jawaban yang jujur.

## Lapis 1: provenance

Saat file selesai diunduh dan diberi tag, tulis asal-usulnya ke dalam tag file itu sendiri. Bukan ke database terpisah, karena file di `F:\sorted` sering dipindah dan diganti nama, dan index yang memakai path sebagai kunci akan langsung putus.

Field yang ditulis:

| Field | Isi | Sumber |
|---|---|---|
| `orpheus_source_module` | nama modul, misal `tidal`, `applemusic` | `self.service_name` |
| `orpheus_quality_tier` | tier yang diminta, misal `HIFI`, `LOSSLESS` | `quality_tier` di `music_downloader.py:289` |
| `orpheus_codec_served` | codec yang benar-benar dikirim modul | `download_info` / `codec` sebelum konversi |
| `orpheus_codec_final` | codec setelah `codec_conversions` | codec saat `tag_file` dipanggil |
| `orpheus_bitrate_kbps` | bitrate yang dilaporkan modul, kosongkan kalau tak ada | `TrackInfo` |
| `orpheus_sample_rate` | sample rate sumber | `TrackInfo` |
| `orpheus_bit_depth` | bit depth sumber, kosongkan untuk codec lossy | `TrackInfo` |
| `orpheus_downloaded_at` | timestamp ISO 8601 UTC | waktu unduh |
| `orpheus_version` | commit hash atau versi fork | build info |

Penyimpanan: Vorbis comment untuk FLAC, Ogg, dan Opus. Freeform atom `----:com.orpheusdl:<field>` untuk MP4 dan M4A. TXXX frame untuk MP3. Semua lewat mutagen yang sudah dipakai `orpheus/tagging.py`.

Titik integrasi: `tag_file()` di `orpheus/tagging.py`, dipanggil dari `orpheus/music_downloader.py:625`. Panggilan itu terjadi setelah konversi codec, jadi di titik tersebut nilai `codec_served` dan `codec_final` dua-duanya sudah diketahui. Tanda tangan `tag_file()` ditambah satu parameter provenance berbentuk dict, dan parameter itu opsional supaya pemanggil lain tidak pecah.

Yang penting dicatat: `codec_served` yang berbeda dari `codec_final` bukan tanda file buruk. Konversi ALAC ke FLAC tetap lossless. Yang jadi bukti lossy adalah `codec_served` yang memang lossy, misalnya AAC atau EAC3.

## Lapis 2: detektor terukur

Ganti isi `analyze_flac_quality()`. Fungsi baru tidak mengeluarkan verdict, cuma mengeluarkan pengukuran plus satu flag.

Yang diukur:

Lowpass keras. Ambil lima jendela FFT yang tersebar merata antara 20% dan 80% durasi track, bukan satu jendela di tengah. Hitung median spektrum dari kelima jendela. Cari titik di mana energi jatuh 30 dB atau lebih dalam rentang 1 kHz. Laporkan frekuensinya dan besar jatuhnya. Tebing seperti ini muncul di MP3 dan AAC 192 kbps ke bawah, dan tidak muncul di file lossless. Pengukuran slope dilakukan di atas cutoff, bukan di bawahnya, karena itu bug yang meloloskan seluruh set ground-truth sekarang. Kalau kelima jendela sepakat ada tebing di bawah 19 kHz, file ditandai suspect.

Upsampling. Kalau file mendeklarasikan 96 kHz tapi tidak ada energi berarti di atas 22,05 kHz, isinya kemungkinan besar berasal dari 44,1 kHz. Laporkan frekuensi energi tertinggi terhadap Nyquist yang dideklarasikan. Ini bukti keras dan bisa diulang.

Bit depth semu. Kalau file 24-bit tapi delapan bit terbawah selalu nol di seluruh sampel, isinya 16-bit yang dipadding. Cek langsung ke sampel integer, tidak perlu FFT.

Integritas decode. File yang gagal di-decode, terpotong, atau punya frame rusak ditandai corrupt. Ini kategori tersendiri, bukan masalah kualitas.

Yang tidak diukur, dan alasannya ditulis di kode: kecocokan dengan Crest Factor dan Clipping milik Soniq (tidak dihitung di sini), serta segala usaha membedakan AAC 256 ke atas dari lossless (tak ada artefak yang tersisa untuk diukur).

Fungsi ini juga menolak file `.m4a` secara eksplisit, bukan memaksakan parser FLAC ke atasnya seperti sekarang. Perilaku sekarang membuat setiap m4a mengembalikan "Cannot verify" dan mendapat skor terendah di ranking duplikat.

## Lapis 3: status dan keputusan

Tiga status, tidak lebih.

`verified` diberikan kalau provenance menunjukkan codec yang diserve memang lossless (FLAC, ALAC) dari modul dan tier yang jelas. Tidak perlu analisis sinyal.

`suspect` diberikan kalau Lapis 2 menemukan bukti keras (lowpass di bawah 19 kHz, upsampling, atau bit depth semu), atau provenance menunjukkan codec lossy padahal file berekstensi lossless.

`unknown` untuk sisanya, termasuk seluruh 2037 file lama yang tidak punya provenance dan tidak memicu detektor apa pun.

Healer cuma memproses ulang file berstatus `suspect`. File `unknown` masuk laporan dan tidak disentuh. Ini keputusan sadar: menyapu ribuan file berdasarkan tebakan justru merusak file yang sebenarnya baik-baik saja.

## Yang dihapus

- Semua string verdict lama: "Standard Quality (CD / Near-CD)", "True High-Resolution Audio", "Natural Rolloff (Vintage Recording)", "Possibly Upsampled", "Upsampled / Transcoded", "Lossy Transcode".
- `is_truly_lossless()` beserta whitelist-nya.
- `_VERDICT_SCORE` dan blok `[quality_score]` di `healer_config.toml`.
- `bad_verdicts` di `healer_config.toml`.

Dua hal terakhir itu saling bertentangan sekarang: config menyebut "Possibly Upsampled" perlu diperbaiki, sementara `is_truly_lossless()` menerimanya sebagai kualitas yang layak. Healer bisa menandai file, mengunduh ulang, lalu menerima pengganti dengan verdict yang sama persis.

`check_duplicates.py` mengimpor `_VERDICT_SCORE`, jadi ranking duplikatnya ikut diganti. Urutan baru: file dengan provenance lossless menang, lalu bit depth dan sample rate lebih tinggi, lalu ukuran file lebih besar. Status `suspect` selalu kalah dari `unknown`.

## Perubahan config

Dua trap yang membuat target format tak mungkin tercapai:

`advanced.codec_conversions` di `config/settings.json` memetakan `alac -> flac`. Selama setelan ini aktif, setiap unduhan ALAC dikonversi begitu tiba, jadi tidak akan pernah ada file ALAC di library. Pemetaan itu dihapus.

`modules.applemusic.codec` diisi `"aac"`. ALAC adalah nilai yang sah (lihat `modules/applemusic/gamdl/gamdl/interface/enums.py`) dan `modules/applemusic/interface.py:218` sudah menggerbanginya pada `QualityEnum.LOSSLESS` atau `HIFI`. Nilainya diganti ke `"alac"`.

`healer_config.toml` kehilangan `bad_verdicts` dan `[quality_score]`, diganti satu setelan: status mana yang memicu unduh ulang. Defaultnya cuma `suspect`.

## Cek

Dua file test tanpa framework: `test_quality_probe.py` untuk detektor Lapis 2 dan `test_provenance.py` untuk penulisan tag. Keduanya jalan lewat `python test_<nama>.py`.

Set ground-truth ada di `ground_truth/` di root repo, 370 MB, di luar git: 3 file FLAC asli dan 12 hasil transcode (aac128, aac256, aac320 untuk tiga sumber, plus mp3128, mp3320, opus128 untuk sumber pertama). Assertion:

- Kelima transcode 128 kbps (tiga AAC, satu MP3, satu Opus) keluar sebagai `suspect`. Cutoff-nya ada di 16 sampai 17 kHz, jauh di bawah ambang 19 kHz.
- Ketiga file asli keluar bukan `suspect`.
- Transcode 256 dan 320 kbps keluar `unknown`. Keduanya tidak punya tebing di bawah 19 kHz, jadi detektor memang tidak boleh menuduhnya. Test menuliskan ini sebagai hasil yang diharapkan, bukan sebagai kegagalan.
- Menjalankan detektor dua kali pada file yang sama memberi hasil identik.

Cara membuat ulang set ground-truth kalau hilang. Flag `-vn` wajib karena cover art tertanam adalah stream h264 yang merusak muxing m4a:

```shell
ffmpeg -vn -i orig.flac -c:a aac -b:a 256k t.m4a && ffmpeg -vn -i t.m4a -c:a flac fake.flac
```

## Pertanyaan terbuka

Tiga keputusan belum dikunci dan tidak menghalangi pekerjaan di PRD ini.

Untuk apa 15% ALAC. FLAC dan ALAC dua-duanya lossless, jadi pembagiannya soal preferensi container, bukan kualitas, dan tidak menghemat ruang. Alasannya perlu ditulis sebelum rasio itu dijadikan target.

Batas tier C. Sebagian track tidak punya sumber lossless di mana pun, misalnya AAC 96 kbps dan satu rip dari video YouTube. Tier ketiga yang dikecualikan dari rasio membuat targetnya bisa dicapai, tapi syarat masuk tier itu belum didefinisikan.

Cara `check_duplicates.py` membandingkan antar playlist. Fungsi itu memakai `glob()`, bukan `rglob()`, jadi cuma melihat file yang langsung ada di dalam `--target-dir` dan tidak pernah masuk subfolder.

## Di luar cakupan

Kelengkapan metadata (genre cuma ada di 1 dari 44 file di `downloads/`), pembersihan 19 duplikat di `F:\sorted\output`, dan stub `python orpheus.py settings ...` yang isinya `return  # TODO`. Semuanya nyata, tapi bukan bagian dari verifikasi kualitas.
