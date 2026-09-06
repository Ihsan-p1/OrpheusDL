"""Fill empty genre tags from the iTunes Search API, then from Deezer.

The tidal module never writes a genre, so 1385 of the 1459 files in
G:\\Music\\Library have none. The 73 that do came from the applemusic module,
which reads them from genreNames — the same vocabulary is used here so the
library does not end up mixing two of them.

A match has to be firm: the same title after normalization, and the artist name
matching in full — not merely contained, because "Artis" is contained in "Artis
Lain". What does not match is written to a list and its tag is left alone: a
wrong genre is more trouble than an empty one.

    python tools_backfill_genre.py                          # report only
    python tools_backfill_genre.py --apply                  # write the genre tags
    python tools_backfill_genre.py --apply --retry-failed   # ask again for the failures
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

import mutagen

from tools_dupes_by_tag import normalize

LIBRARY = r"G:\Music\Library"
AUDIO = (".flac", ".m4a", ".mp3")
CACHE = "genre_cache.json"
NOT_FOUND_FILE = "genre_not_found.txt"
# The iTunes Search API without a key is capped at roughly 20 requests a minute.
DELAY = 3.0
API = "https://itunes.apple.com/search"
DEEZER = "https://api.deezer.com"
# Deezer uses terms of its own. The ones that differ are mapped onto Apple's so
# a single library does not run on two naming systems.
DEEZER_MAP = {
    "Rap/Hip Hop": "Hip-Hop/Rap",
    "R&B": "R&B/Soul",
    "Electro": "Electronic",
    "Films/Games": "Soundtrack",
    "Musique brésilienne": "Brazilian",
    "Musiques du monde": "Worldwide",
}
# The US catalogue does not carry part of the Indonesian, Japanese and Mandarin
# releases.
COUNTRIES = ("US", "ID", "JP")


# Connecting words between artist names. Dropped from both sides so "Yovie &
# Nuno" and "Yovie and Nuno" read the same.
CONNECTORS = {"and", "dan", "with", "feat", "featuring", "ft", "x", "vs"}


def artist_parts(s):
    """The artist names in one string, each as a tuple of words."""
    out = set()
    for part in re.split(r"[;,&/]|\bfeat\b|\bwith\b", s, flags=re.IGNORECASE):
        token = tuple(w for w in normalize(part).split() if w not in CONNECTORS)
        if token:
            out.add(token)
    token = tuple(w for w in normalize(s).split() if w not in CONNECTORS)
    if token:
        out.add(token)
    return out


def artists_match(tag, catalogue):
    """The artist name in the tag and in the catalogue point at the same people.

    Both sides are split, then one name has to match in full. Both need
    splitting because the tag and the catalogue disagree about who gets listed:
    the tag writes "Zhou Shen; HOYO-MiX" where the catalogue writes "Zhou Shen",
    but the catalogue writes "CHiCO with HoneyWorks" where the tag writes
    "CHiCO".

    Matching demands a whole name, not a contained one. "Artis" is contained in
    "Artis Lain", and those are two different people.
    """
    return bool(artist_parts(tag) & artist_parts(catalogue))


def title_parts(s):
    """The title as it stands, and the title without a trailing bracket.

    The tag and the catalogue disagree about where the version note goes: one
    writes "Dia Milikku (Album Version)" where the other writes "Dia Milikku".
    """
    full = normalize(s)
    short = normalize(re.sub(r"[\(\[].*", " ", s))
    return {x for x in (full, short) if x}


def pick_genre(results, artist, title):
    """The genre of the candidate whose title and artist match, or None.

    `results` is the list of raw entries from the API.
    """
    wanted = title_parts(title)
    for r in results:
        if not (wanted & title_parts(r.get("trackName", ""))):
            continue
        if normalize(artist) and artists_match(artist, r.get("artistName", "")):
            return r.get("primaryGenreName") or None
    return None


def query_itunes(artist, title, country):
    """The raw API results for one catalogue region."""
    query = urllib.parse.urlencode({
        "term": f"{artist} {title}", "entity": "song", "limit": 5, "country": country})
    try:
        with urllib.request.urlopen(f"{API}?{query}", timeout=20) as resp:
            results = json.load(resp).get("results", [])
    except Exception as e:
        print(f"  [API-ERR] {artist} - {title}: {e}")
        results = []
    time.sleep(DELAY)
    return results


def query_deezer(artist, title):
    """The genre from Deezer, or None.

    Deezer's catalogue carries Indonesian and Japanese releases Apple does not
    have. Its genre sits on the album rather than the track, so this takes two
    requests.
    """
    query = urllib.parse.urlencode({"q": f"{artist} {title}", "limit": 5})
    try:
        with urllib.request.urlopen(f"{DEEZER}/search?{query}", timeout=20) as resp:
            results = json.load(resp).get("data", [])
    except Exception as e:
        print(f"  [DEEZER-ERR] {artist} - {title}: {e}")
        return None

    wanted = title_parts(title)
    for r in results:
        if not (wanted & title_parts(r.get("title", ""))):
            continue
        if not artists_match(artist, (r.get("artist") or {}).get("name", "")):
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
        names = [g["name"] for g in genre.get("data", []) if g.get("name")]
        if names:
            return DEEZER_MAP.get(names[0], names[0])
    return None


def lookup(artist, title, cache, retry_failed=False):
    """The genre for one song. API answers are cached so nothing is asked twice."""
    cache_key = f"{artist}|{title}"
    if cache_key in cache and not (retry_failed and cache[cache_key] is None):
        return cache[cache_key]
    genre = None
    for country in COUNTRIES:
        results = query_itunes(artist, title, country)
        genre = pick_genre(results, artist, title)
        if genre:
            break
        # Another region is only tried when the US catalogue does not carry the
        # song at all. If it does carry it and the match was rejected, asking
        # another region is pointless.
        if results:
            break
    if not genre:
        genre = query_deezer(artist, title)
        time.sleep(0.3)
    cache[cache_key] = genre
    return genre


def main():
    apply = "--apply" in sys.argv
    retry_failed = "--retry-failed" in sys.argv
    cache = json.load(open(CACHE, encoding="utf-8")) if os.path.exists(CACHE) else {}

    empty = []
    for name in sorted(os.listdir(LIBRARY)):
        path = os.path.join(LIBRARY, name)
        if not (os.path.isfile(path) and name.lower().endswith(AUDIO)):
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
            empty.append((path, artist, title))

    print(f"{len(empty)} files without a genre. Around {len(empty) * DELAY / 60:.0f} "
          f"minutes.\n")

    found, failed = 0, []
    try:
        for i, (path, artist, title) in enumerate(empty, 1):
            genre = lookup(artist, title, cache, retry_failed)
            if genre:
                found += 1
                print(f"[{i}/{len(empty)}] {artist} - {title} -> {genre}")
                if apply:
                    tags = mutagen.File(path, easy=True)
                    tags["genre"] = genre
                    tags.save()
            else:
                failed.append(f"{artist} - {title}")
                print(f"[{i}/{len(empty)}] {artist} - {title} -> not found")
    finally:
        # The cache is written whatever happens, so a rerun does not hit the API
        # from scratch again.
        with open(CACHE, "w", encoding="utf-8") as fh:
            json.dump(cache, fh, ensure_ascii=False, indent=1)
        with open(NOT_FOUND_FILE, "w", encoding="utf-8") as fh:
            fh.write("\n".join(failed) + "\n")

    print(f"\n{found} found, {len(failed)} not. Missing list: {NOT_FOUND_FILE}")
    if not apply:
        print("Report only. Run with --apply to write the tags.")


if __name__ == "__main__":
    main()
