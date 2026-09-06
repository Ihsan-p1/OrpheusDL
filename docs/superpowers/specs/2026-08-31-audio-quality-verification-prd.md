# PRD: audio quality verification system

Date: 2026-08-31
Status: draft, awaiting review
Repo: OrpheusDL-master (fork)

## Background

The pipeline today judges whether a file is genuine through `analyze_flac_quality()` in `orpheus_healer.py`. Measuring that function shows three things:

1. Of the 12 ground-truth files built with ffmpeg (a genuine FLAC, converted to AAC/MP3/Opus, then wrapped back into FLAC), 12 pass as lossless. MP3 128 kbps included. The cause sits at `orpheus_healer.py:914`: the slope measurement range is derived from `cutoff_hz` and capped at `cutoff_hz * 0.98`, so the measurement window always sits below the encoder cliff and never touches it.
2. The verdict changes with the position of the FFT window. Across the 12 sample files, 4 change verdict when the window is moved between 15% and 85% of the track's duration.
3. The thresholds in `_THRESHOLDS` (92 / 72 / -4.5 / 62) have no recorded origin, no test set, and no error rate.

The verdict vocabulary was lifted from the Verdict column of a Soniq Tools export, but without the two axes of evidence Soniq uses (Crest Factor and Clipping). One of the labels, "Natural Rolloff (Vintage Recording)", never appears once in the four Soniq exports in this repo. That label is this code's own invention, and it is the one that let all 12 fakes through. Verdict agreement between the two tools, across the 120 files that are both in the CSV and on disk, is 54.2%.

There is also a physical limit no tool gets past: AAC at 256 kbps and above leaves no spectral artefact. Mean deviation from the source is only 0.12 to 0.23 dB across every frequency band, and the cutoff is identical at the -60, -80, -100 and -120 dB floors. Rendered as spectrograms, a genuine file and an AAC 256 transcode cannot be told apart by eye. For the Apple Music module, which serves AAC 256, spectral analysis proves nothing.

## Goal

Replace the guessing verdict system with one that reports only what can actually be proven, and admits it does not know about the rest.

Measures of success:

- Every fake in the ground-truth set at 192 kbps and below is detected.
- No genuine file in the ground-truth set is wrongly accused.
- The verdict does not change when the analysis is repeated on the same file.
- Every newly downloaded file carries a record of where it came from, readable without analysing its audio.

## Not the goal

- Detecting AAC at 256 kbps and above. Spectrally impossible, so not promised.
- Re-sweeping the 2037 files in `F:\sorted`. Old files are left alone unless the detector finds hard evidence.
- Replacing Adobe Audition or Soniq Tools. Both stay in human hands for settling disputed cases.
- Chasing the 85% FLAC / 15% ALAC ratio. That is separate work, though this PRD clears the way for it through the config fixes.

## Principles

Provenance is the primary evidence. Once we know which module a file was downloaded from, at which tier, and which codec the server sent, there is nothing to gain from guessing by FFT.

Signal analysis is only a supplement, and only for what can be measured again with the same result. Everything else is answered with "unknown". A status of "unknown" is not a system failure, it is the honest answer.

## Layer 1: provenance

When a file finishes downloading and gets tagged, write where it came from into that file's own tags. Not into a separate database, because files in `F:\sorted` get moved and renamed often, and an index keyed by path breaks the moment that happens.

The fields written:

| Field | Content | Source |
|---|---|---|
| `orpheus_source_module` | module name, e.g. `tidal`, `applemusic` | `self.service_name` |
| `orpheus_quality_tier` | requested tier, e.g. `HIFI`, `LOSSLESS` | `quality_tier` in `music_downloader.py:289` |
| `orpheus_codec_served` | the codec the module actually served | `download_info` / `codec` before conversion |
| `orpheus_codec_final` | the codec after `codec_conversions` | the codec when `tag_file` is called |
| `orpheus_bitrate_kbps` | bitrate as reported by the module, empty when absent | `TrackInfo` |
| `orpheus_sample_rate` | source sample rate | `TrackInfo` |
| `orpheus_bit_depth` | source bit depth, empty for a lossy codec | `TrackInfo` |
| `orpheus_downloaded_at` | ISO 8601 UTC timestamp | download time |
| `orpheus_version` | commit hash or fork version | build info |

Storage: a Vorbis comment for FLAC, Ogg and Opus. The freeform atom `----:com.orpheusdl:<field>` for MP4 and M4A. A TXXX frame for MP3. All through the mutagen that `orpheus/tagging.py` already uses.

Integration point: `tag_file()` in `orpheus/tagging.py`, called from `orpheus/music_downloader.py:625`. That call happens after the codec conversion, so at that point both `codec_served` and `codec_final` are known. The signature of `tag_file()` gains one provenance parameter, a dict, and that parameter is optional so other callers do not break.

Worth recording: a `codec_served` that differs from `codec_final` is not a sign of a bad file. ALAC converted to FLAC is still lossless. What counts as evidence of lossy is a `codec_served` that is itself lossy, AAC or EAC3 for instance.

## Layer 2: a measured detector

Replace the body of `analyze_flac_quality()`. The new function hands down no verdict, only measurements plus one flag.

What is measured:

A hard lowpass. Take five FFT windows spread evenly between 20% and 80% of the track's duration, rather than one window in the middle. Compute the median spectrum of the five. Look for the point where energy falls 30 dB or more inside a 1 kHz span. Report the frequency and the size of the drop. A cliff like that appears in MP3 and AAC at 192 kbps and below, and does not appear in a lossless file. The slope is measured above the cutoff rather than below it, because measuring below is the bug that lets the entire current ground-truth set through. When all five windows agree on a cliff below 19 kHz, the file is marked suspect.

Upsampling. When a file declares 96 kHz but has no meaningful energy above 22.05 kHz, its content almost certainly came from 44.1 kHz. Report the highest energy frequency against the declared Nyquist. This is hard evidence and it repeats.

A dead top band. Added after the measurements: `fake_2_aac128` escapes the cliff detector because its source was already very quiet up high (-88 dB at 16 kHz), so the encoder's cut produced a drop of only 16 dB. What separates them is variation. The noise floor of a genuine recording moves up and down (standard deviation 5.0 to 7.4 dB in the band from 82 to 97.5 percent of Nyquist), while a band the encoder zeroed is flat and still (2.4 to 2.6 dB). The separation is clean, with no overlap, across the ground-truth set.

Padded bit depth. When a file is 24-bit but its lowest eight bits are always zero across every sample, its content is padded 16-bit. Check the integer samples directly, no FFT needed.

Decode integrity. A file that fails to decode, is truncated, or has damaged frames is marked corrupt. That is its own category, not a quality problem.

What is not measured, with the reason written in the code: agreement with Soniq's Crest Factor and Clipping (not computed here), and any attempt to tell AAC 256 and above from lossless (there is no artefact left to measure).

The function also rejects an `.m4a` explicitly rather than forcing a FLAC parser onto it as it does now. The current behaviour makes every m4a return "Cannot verify" and take the lowest score in the duplicate ranking.

## Layer 3: status and decision

Three statuses, no more.

`verified` is given when provenance shows the codec served was genuinely lossless (FLAC, ALAC) from a clear module and tier. No signal analysis needed.

`suspect` is given when Layer 2 finds hard evidence (a lowpass below 19 kHz, upsampling, or a padded bit depth), or when provenance shows a lossy codec inside a file with a lossless extension.

`unknown` covers the rest, including all 2037 old files that have no provenance and trip no detector.

The healer reprocesses only files marked `suspect`. An `unknown` file goes into the report and is not touched. This is a deliberate decision: sweeping thousands of files on a guess damages files that were fine.

## What gets removed

- Every old verdict string: "Standard Quality (CD / Near-CD)", "True High-Resolution Audio", "Natural Rolloff (Vintage Recording)", "Possibly Upsampled", "Upsampled / Transcoded", "Lossy Transcode".
- `is_truly_lossless()` and its whitelist.
- `_VERDICT_SCORE` and the `[quality_score]` block in `healer_config.toml`.
- `bad_verdicts` in `healer_config.toml`.

Those last two contradict each other as things stand: the config says "Possibly Upsampled" needs repair, while `is_truly_lossless()` accepts it as adequate quality. The healer can flag a file, redownload it, and then accept a replacement carrying exactly the same verdict.

`check_duplicates.py` imports `_VERDICT_SCORE`, so its duplicate ranking is replaced too. The new order: a file with lossless provenance wins, then higher bit depth and sample rate, then larger file size. A `suspect` status always loses to `unknown`.

## Config changes

Two traps that make the format target unreachable:

`advanced.codec_conversions` in `config/settings.json` maps `alac -> flac`. While that setting is active, every ALAC download is converted on arrival, so an ALAC file can never exist in the library. That mapping is removed.

`modules.applemusic.codec` is set to `"aac"`. ALAC is a valid value (see `modules/applemusic/gamdl/gamdl/interface/enums.py`) and `modules/applemusic/interface.py:218` already gates it on `QualityEnum.LOSSLESS` or `HIFI`. The value becomes `"alac"`.

`healer_config.toml` loses `bad_verdicts` and `[quality_score]`, replaced by a single setting: which status triggers a redownload. The default is `suspect` alone.

## Checks

Two test files, no framework: `test_quality_probe.py` for the Layer 2 detector and `test_provenance.py` for the tag writing. Both run through `python test_<name>.py`.

The ground-truth set lives in `ground_truth/` at the repo root, 370 MB, outside git: 3 genuine FLAC files and 12 transcodes (aac128, aac256, aac320 for three sources, plus mp3128, mp3320, opus128 for the first source). Assertions:

- All five 128 kbps transcodes (three AAC, one MP3, one Opus) come out `suspect`.
- MP3 320 kbps comes out `suspect` too. That was not expected: its cliff sits at 19.2 kHz, lower even than Opus 128, which cuts at 19.7 kHz.
- All three genuine files come out as something other than `suspect`.
- All six AAC 256 and 320 kbps transcodes come out `unknown`. Not one has a cliff, and their top-band variation (4.6 to 7.4 dB) overlaps the genuine files (5.0 to 7.4 dB) exactly. The test records this as the expected result, not as a failure.
- Running the detector twice on the same file gives identical results.

How to rebuild the ground-truth set if it is lost. The `-vn` flag is required because embedded cover art is an h264 stream that breaks m4a muxing:

```shell
ffmpeg -vn -i orig.flac -c:a aac -b:a 256k t.m4a && ffmpeg -vn -i t.m4a -c:a flac fake.flac
```

## Open questions

Three decisions are not settled and none of them blocks the work in this PRD.

What the 15% ALAC is for. FLAC and ALAC are both lossless, so the split is a container preference rather than a quality one, and it saves no space. The reason needs writing down before that ratio becomes a target.

The boundary of tier C. Some tracks have no lossless source anywhere, AAC 96 kbps and one rip from a YouTube video for instance. A third tier excluded from the ratio makes the target reachable, but the criteria for entering that tier are not defined yet.

How `check_duplicates.py` compares across playlists. It uses `glob()` rather than `rglob()`, so it sees only the files sitting directly inside `--target-dir` and never enters a subfolder.

## Out of scope

Metadata completeness (a genre exists on 1 of the 44 files in `downloads/`), clearing the 19 duplicates in `F:\sorted\output`, and the `python orpheus.py settings ...` stubs whose body is `return  # TODO`. All real, none part of quality verification.
