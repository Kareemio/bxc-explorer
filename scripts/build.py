"""Build the explorer page from the current playlist and the tag library."""
import datetime
import json
import os

HERE = os.path.dirname(__file__)
ROOT = os.path.join(HERE, "..")
tracks = {t["id"]: t for t in json.load(open(os.path.join(ROOT, "data", "tracks.json"), encoding="utf-8"))}
playlist = json.load(open(os.path.join(ROOT, "data", "playlist.json"), encoding="utf-8"))["tracks"]

# Playlist order, newest additions last; only tracks currently in the playlist.
rows = [tracks[p["id"]] for p in playlist if p["id"] in tracks]

# YouTube versions for the YouTube player (overrides win over automatic matches).
def _load(name):
    path = os.path.join(ROOT, "data", name)
    return json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
yt = {k: v.get("v") for k, v in _load("youtube.json").items()}
yt.update(_load("youtube_overrides.json"))
rows = [dict(r, yt=yt[r["id"]]) if yt.get(r["id"]) else r for r in rows]
updated = datetime.datetime.now(datetime.timezone.utc).strftime("%-d %B %Y")
html = (open(os.path.join(ROOT, "site", "template.html"), encoding="utf-8").read()
        .replace("__DATA__", json.dumps(rows, ensure_ascii=False, separators=(",", ":")))
        .replace("__UPDATED__", updated)
        .replace("__PLAYLIST_ID__", json.load(open(os.path.join(ROOT, "data", "playlist.json")))["playlist_id"])
        .replace("__SPOTIFY_CLIENT_ID__", os.environ.get("SPOTIFY_CLIENT_ID", "").strip() or "__SPOTIFY_CLIENT_ID__"))
os.makedirs(os.path.join(ROOT, "_site"), exist_ok=True)
open(os.path.join(ROOT, "_site", "index.html"), "w", encoding="utf-8").write(html)
open(os.path.join(ROOT, "_site", ".nojekyll"), "w").close()
print(f"Built page with {len(rows)} tracks ({sum(1 for r in rows if r.get('pending'))} awaiting tags, {sum(1 for r in rows if r.get('yt'))} with a YouTube version)")
