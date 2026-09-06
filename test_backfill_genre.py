"""Check candidate selection against iTunes responses. No network."""
from tools_backfill_genre import pick_genre


def r(artist, track, genre="Pop"):
    return {"artistName": artist, "trackName": track, "primaryGenreName": genre}


def test_exact_match():
    assert pick_genre([r("Hivi!", "Pelangi", "Indie Pop")], "Hivi!", "Pelangi") == "Indie Pop"


def test_punctuation_is_ignored():
    # Tag "Yovie & Nuno", catalogue "Yovie and Nuno" — the same once normalized.
    assert pick_genre([r("Yovie and Nuno", "Merindu Lagi")],
                      "Yovie & Nuno", "Merindu Lagi") == "Pop"


def test_guest_artist_in_the_tag():
    # The tag lists every artist, the catalogue only the main one.
    assert pick_genre([r("Zhou Shen", "Rubia", "Soundtrack")],
                      "Zhou Shen; HOYO-MiX", "Rubia") == "Soundtrack"


def test_guest_artist_in_the_catalogue():
    # The other direction: the catalogue is the one listing more.
    assert pick_genre([r("CHiCO with HoneyWorks", "Sekaiwa Koi Ni Ochiteiru", "Anime")],
                      "CHiCO", "Sekaiwa Koi Ni Ochiteiru") == "Anime"
    assert pick_genre([r("Lil Baby & Lil Durk", "2040", "Hip-Hop/Rap")],
                      "Lil Baby", "2040") == "Hip-Hop/Rap"


def test_trailing_bracket_is_ignored():
    # The version note is on one side only.
    assert pick_genre([r("HOYO-MiX", "TruE (Instrumental)", "Soundtrack")],
                      "HOYO-MiX", "TruE") == "Soundtrack"
    assert pick_genre([r("Yovie & Nuno", "Dia Milikku", "Pop")],
                      "Yovie & Nuno", "Dia Milikku (Album Version)") == "Pop"


def test_different_title_is_rejected():
    assert pick_genre([r("Hivi!", "Pelangi Lain")], "Hivi!", "Pelangi") is None


def test_different_artist_is_rejected():
    # Same title, another artist: exactly the case that swaps songs around.
    assert pick_genre([r("The Walters", "Make You Mine")],
                      "GIVEON", "Make You Mine") is None
    # An artist name contained in another one is still rejected.
    assert pick_genre([r("Artis Lain", "Lagu")], "Artis", "Lagu") is None
    assert pick_genre([r("Lynyrd Skynyrd", "Double Trouble")],
                      "Quality Control", "Double Trouble") is None


def test_first_matching_candidate_wins():
    results = [r("Artis Lain", "Lagu", "Rock"), r("Artis", "Lagu", "Jazz")]
    assert pick_genre(results, "Artis", "Lagu") == "Jazz"


def test_empty():
    assert pick_genre([], "Artis", "Lagu") is None
    assert pick_genre([r("", "Lagu")], "Artis", "Lagu") is None
    # An empty genre in the catalogue is not an answer.
    assert pick_genre([r("Artis", "Lagu", "")], "Artis", "Lagu") is None


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print("PASS", name)
