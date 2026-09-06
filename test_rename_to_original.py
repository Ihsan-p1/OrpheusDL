"""Check rename_to_original: the replacement lands on the old file's path and name."""
import os
import tempfile

from orpheus_healer import rename_to_original


def test():
    with tempfile.TemporaryDirectory() as d:
        library = os.path.join(d, "Library")
        staging = os.path.join(d, "_HEAL_STAGING")
        os.makedirs(library)
        os.makedirs(staging)

        old = os.path.join(library, "Artist - Old Song.flac")
        new = os.path.join(staging, "01 Song (Remaster).m4a")
        open(new, "w").close()
        open(os.path.splitext(new)[0] + ".lrc", "w").close()

        # Moves into the old file's folder, keeps the old stem and the new
        # extension, and takes the lyrics along.
        result = rename_to_original(new, old)
        assert result == os.path.join(library, "Artist - Old Song.m4a"), result
        assert os.path.exists(result)
        assert os.path.exists(os.path.join(library, "Artist - Old Song.lrc"))
        assert not os.path.exists(new)

        # Already in the right place under the right name: nothing to do.
        assert rename_to_original(result, result) == result

        # The target name is taken: the download is left alone and the old file
        # is not overwritten.
        other = os.path.join(staging, "new download.m4a")
        open(other, "w").close()
        assert rename_to_original(other, old) == other
        assert os.path.exists(other)

        # Missing file or empty argument: hand back what came in.
        assert rename_to_original(os.path.join(staging, "ghost.flac"), old).endswith("ghost.flac")
        assert rename_to_original("", old) == ""

    print("test_rename_to_original OK")


if __name__ == "__main__":
    test()
