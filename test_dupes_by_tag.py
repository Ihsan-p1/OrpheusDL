"""Check the keeper rules and the playlist rewrite."""
from tools_dupes_by_tag import normalize, rank, rewrite_playlist, split_group, tag_key


def test_tag_key():
    assert tag_key({"artist": ["Hivi!"], "title": ["Pelangi"]}) == ("hivi", "pelangi")
    # A Japanese title must not end up as an empty string.
    assert tag_key({"artist": ["YOASOBI"], "title": ["たぶん"]})[1] == "たぶん"
    # Without a title there is nothing to group by.
    assert tag_key({"artist": ["X"], "title": [""]}) is None
    # albumartist is used when artist is empty.
    assert tag_key({"albumartist": ["Yura"], "title": ["Jalan Pulang"]})[0] == "yura"


def test_normalize_folds_accents():
    # Tags and catalogues write the same name with different letters.
    assert normalize("JAŸ-Z") == normalize("JAY-Z")
    assert normalize("Bouwéy") == normalize("Bouwey")
    assert normalize("Devil’s Dance") == normalize("Devil's Dance")


def test_normalize_keeps_kana_voicing_marks():
    # "が" must not collapse into "か": that is a different word.
    assert normalize("がっこう") != normalize("かっこう")
    assert normalize("がっこう") == "がっこう"


def entry(prov=None, bits=16, rate=44100, size=1, md5=1):
    return {"provenance": prov, "bits": bits, "rate": rate, "size": size, "md5": md5}


def test_split_group_only_releases_matching_md5():
    copy = entry(size=1, md5=7)
    different = entry(size=2, md5=8)
    keeper, released, left = split_group([entry(size=9, md5=7), copy, different])
    assert keeper["size"] == 9
    assert released == [copy]
    assert left == [different]


def test_split_group_without_md5_releases_nothing():
    # m4a and mp3 carry no audio MD5, so there is no proof the content matches.
    a, b = entry(size=9, md5=None), entry(size=1, md5=None)
    keeper, released, left = split_group([a, b])
    assert keeper is a
    assert released == []
    assert left == [b]


def test_rank():
    # Provenance wins even against a bigger file with a higher bit depth.
    prov = entry(prov="tidal")
    big = entry(bits=24, rate=96000, size=999)
    assert max([big, prov], key=rank) is prov
    # Without provenance, bit depth outranks sample rate and size.
    assert max([entry(bits=16, rate=96000, size=999),
                entry(bits=24, rate=44100, size=1)], key=rank)["bits"] == 24
    # Same bit depth and sample rate, size decides.
    assert max([entry(size=5), entry(size=9)], key=rank)["size"] == 9


def test_rewrite_playlist():
    lines = ["#EXTM3U", "../Library/Title.flac", "../Library/Artist - Title.flac",
             "../Library/Other.flac", ""]
    result = rewrite_playlist(lines, {"Artist - Title.flac": "Title.flac"})
    # Two entries now point at the same file, keep one, order unchanged.
    assert result == ["#EXTM3U", "../Library/Title.flac", "../Library/Other.flac", ""]
    # Without a mapping the playlist is untouched.
    assert rewrite_playlist(lines, {}) == lines


if __name__ == "__main__":
    test_tag_key()
    test_normalize_folds_accents()
    test_normalize_keeps_kana_voicing_marks()
    test_rank()
    test_split_group_only_releases_matching_md5()
    test_split_group_without_md5_releases_nothing()
    test_rewrite_playlist()
    print("test_dupes_by_tag OK")
