"""Check read_tags(): tags win, the filename is the last resort."""
from tools_export_playlists import read_tags

# Full tags are used as they are, the filename is ignored.
assert read_tags({"artist": ["Adhitia Sofyan"], "title": ["Sesuatu Di Jogja"],
                  "album": ["Forget Your Plans"]}, r"C:\x\anything.flac") == (
    "Adhitia Sofyan", "Sesuatu Di Jogja", "Forget Your Plans")

# Without tags, "Artist - Title.flac" still resolves.
assert read_tags(None, r"C:\x\Adhitia Sofyan - Sesuatu Di Jogja.flac") == (
    "Adhitia Sofyan", "Sesuatu Di Jogja", "")

# Without tags and without a separator the artist stays empty: this row has to
# show up in the report.
assert read_tags({}, r"C:\x\Nina.flac") == ("", "Nina", "")

# albumartist is used when artist is empty.
assert read_tags({"artist": [""], "albumartist": ["YOASOBI"], "title": ["Idol"]},
                 r"C:\x\Idol.flac") == ("YOASOBI", "Idol", "")

print("ok")
