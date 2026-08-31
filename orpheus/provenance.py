"""Catatan asal-usul file: modul, tier, codec, waktu unduh.

Disimpan di dalam tag file, bukan di database terpisah. File di library sering
dipindah dan diganti nama, dan index yang memakai path sebagai kunci akan putus
begitu itu terjadi.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, fields

import mutagen
from mutagen.flac import FLAC
from mutagen.id3 import TXXX
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis

from utils.models import ContainerEnum

PREFIX = "orpheus_"
MP4_PREFIX = "----:com.orpheusdl:"
INT_FIELDS = {"bitrate_kbps", "sample_rate", "bit_depth"}
LOSSLESS_CODECS = {"flac", "alac", "wav", "aiff"}


def _detect_version() -> str:
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        done = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              cwd=repo_root, capture_output=True, text=True, timeout=5)
        return done.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


ORPHEUS_VERSION = _detect_version()


@dataclass
class Provenance:
    source_module: str
    quality_tier: str
    codec_served: str
    codec_final: str
    downloaded_at: str
    orpheus_version: str
    bitrate_kbps: int | None = None
    sample_rate: int | None = None
    bit_depth: int | None = None


def _pairs(prov: Provenance) -> list[tuple[str, str]]:
    out = []
    for f in fields(Provenance):
        value = getattr(prov, f.name)
        if value is not None and value != "":
            out.append((PREFIX + f.name, str(value)))
    return out


def write_provenance(file_path: str, container: ContainerEnum, prov: Provenance) -> None:
    """Tulis provenance ke tag file. Tag lain tidak disentuh."""
    if container is ContainerEnum.flac:
        tagger = FLAC(file_path)
        for key, value in _pairs(prov):
            tagger[key] = value
    elif container is ContainerEnum.ogg:
        tagger = OggVorbis(file_path)
        for key, value in _pairs(prov):
            tagger[key] = value
    elif container is ContainerEnum.opus:
        tagger = OggOpus(file_path)
        for key, value in _pairs(prov):
            tagger[key] = value
    elif container is ContainerEnum.m4a:
        tagger = MP4(file_path)
        for key, value in _pairs(prov):
            tagger[MP4_PREFIX + key] = [value.encode("utf-8")]
    elif container is ContainerEnum.mp3:
        tagger = MP3(file_path)
        if tagger.tags is None:
            tagger.add_tags()
        for key, value in _pairs(prov):
            tagger.tags.add(TXXX(encoding=3, desc=key, text=value))
    else:
        raise ValueError(f"container tidak didukung untuk provenance: {container}")
    tagger.save()


def _flatten(value) -> str:
    if isinstance(value, TXXX):
        value = value.text
    if isinstance(value, list):
        value = value[0] if value else ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    return str(value)


def read_provenance(file_path: str) -> Provenance | None:
    """Baca provenance dari file. Kembalikan None kalau tidak ada."""
    try:
        audio = mutagen.File(file_path)
    except Exception:
        return None
    if audio is None or audio.tags is None:
        return None

    found: dict[str, str] = {}
    for key, value in dict(audio.tags).items():
        name = str(key).lower()
        for marker in (MP4_PREFIX.lower(), "txxx:"):
            if name.startswith(marker):
                name = name[len(marker):]
        if name.startswith(PREFIX):
            found[name[len(PREFIX):]] = _flatten(value)

    if not found:
        return None

    kwargs = {}
    for f in fields(Provenance):
        raw = found.get(f.name)
        if raw is None or raw == "":
            kwargs[f.name] = None if f.name in INT_FIELDS else ""
        elif f.name in INT_FIELDS:
            try:
                kwargs[f.name] = int(float(raw))
            except ValueError:
                kwargs[f.name] = None
        else:
            kwargs[f.name] = raw
    return Provenance(**kwargs)
