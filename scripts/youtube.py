"""Find a YouTube version of each playlist track, for the explorer's YouTube player.

Two ways to look songs up:
  --mode unofficial   YouTube Music search via ytmusicapi. No key, no limit. Used once
                      to fill in every existing track.
  --mode official     YouTube Data API (needs the YOUTUBE_API_KEY secret). Free quota is
                      about 100 searches a day, plenty for the few new songs added daily.

Results go to data/youtube.json:  {spotify_id: {"v": video_id or null, "s": source, "d": date}}
To fix a wrong match, put the right video in data/youtube_overrides.json:
  {"<spotify track id>": "<youtube video id>"}   (use null to hide a song from YouTube mode)
"""
import argparse
import datetime
import difflib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.join(os.path.dirname(__file__), "..")
OUT = os.path.join(ROOT, "data", "youtube.json")
TODAY = datetime.date.today().isoformat()
RETRY_DAYS = 30          # look again for songs that weren't found after this long
OFFICIAL_BUDGET = 90     # searches per run; each costs 100 of the 10,000 daily quota units


def norm(s):
    s = (s or "").lower()
    s = re.sub(r"\s*[\(\[][^)\]]*(remaster|version|edit|mix|mono|stereo|live|feat|ft\.|with |deluxe|bonus|single|album)[^)\]]*[\)\]]", "", s)
    s = re.sub(r"\s+-\s+.*(remaster|version|edit|mono|stereo|live|single|from ).*$", "", s)
    s = re.sub(r"\b(feat|ft)\.?\s.*$", "", s)
    s = s.replace("&", "and")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def sim(a, b):
    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    if a == b or a in b or b in a:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def score(track, title, artists):
    t = sim(track["t"], title)
    want = [x.strip() for x in re.split(r",|&| and | x ", track["a"]) if x.strip()]
    a = max((sim(w, h) for w in want for h in artists), default=0.0)
    # official uploads often put "Artist - Title" in the video title
    if a < 0.7 and any(sim(w, title) >= 0.9 or norm(w) in norm(title) for w in want):
        a = 0.85
    return 0.55 * t + 0.45 * a, t, a


def best(track, candidates):
    """candidates: list of (video_id, title, [artists], bonus)."""
    top = None
    for vid, title, artists, bonus in candidates:
        if not vid:
            continue
        s, t, a = score(track, title, artists)
        if t < 0.6 or a < 0.5:
            continue
        s += bonus
        if not top or s > top[0]:
            top = (s, vid)
    return top[1] if top else None


def find_unofficial(yt, track):
    q = f'{track["a"]} {track["t"]}'
    cands = []
    for filt, bonus in (("songs", 0.1), ("videos", 0.0)):
        try:
            res = yt.search(q, filter=filt, limit=5)
        except Exception as e:
            print("  search failed:", e, file=sys.stderr)
            res = []
        for r in res[:5]:
            cands.append((r.get("videoId"), r.get("title", ""), [x.get("name", "") for x in r.get("artists") or []], bonus))
        pick = best(track, cands)
        if pick:
            return pick
    return None


class QuotaUsedUp(Exception):
    pass


def find_official(key, track):
    params = {"part": "snippet", "type": "video", "videoEmbeddable": "true", "videoCategoryId": "10",
              "maxResults": "5", "q": f'{track["a"]} {track["t"]}', "key": key}
    url = "https://www.googleapis.com/youtube/v3/search?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            items = json.load(r).get("items", [])
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        if e.code == 403 and "quota" in body.lower():
            raise QuotaUsedUp()
        raise
    cands = []
    for it in items:
        sn = it.get("snippet", {})
        ch = sn.get("channelTitle", "")
        topic = ch.endswith(" - Topic")   # YouTube Music's official audio uploads
        cands.append((it.get("id", {}).get("videoId"), html_unescape(sn.get("title", "")),
                      [ch.replace(" - Topic", "").replace("VEVO", "")], 0.15 if topic else 0.0))
    return best(track, cands)


def html_unescape(s):
    import html
    return html.unescape(s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["unofficial", "official"], required=True)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    tracks = {t["id"]: t for t in json.load(open(os.path.join(ROOT, "data", "tracks.json"), encoding="utf-8"))}
    playlist = json.load(open(os.path.join(ROOT, "data", "playlist.json"), encoding="utf-8"))["tracks"]
    found = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}

    def due(tid):
        e = found.get(tid)
        if not e:
            return True
        if e.get("v"):
            return False
        try:
            return (datetime.date.today() - datetime.date.fromisoformat(e.get("d", ""))).days >= RETRY_DAYS
        except ValueError:
            return True

    todo = [tracks[p["id"]] for p in playlist if p["id"] in tracks and due(p["id"])]
    if args.mode == "official":
        key = os.environ.get("YOUTUBE_API_KEY", "").strip()
        if not key:
            print("No YOUTUBE_API_KEY set, skipping YouTube lookups.")
            return
        todo = todo[:OFFICIAL_BUDGET]
    if args.limit:
        todo = todo[:args.limit]
    print(f"Looking up {len(todo)} tracks on YouTube ({args.mode})")

    yt = None
    if args.mode == "unofficial":
        from ytmusicapi import YTMusic
        yt = YTMusic()

    hits = 0
    for n, t in enumerate(todo, 1):
        try:
            vid = find_unofficial(yt, t) if yt else find_official(key, t)
        except QuotaUsedUp:
            print("Daily YouTube quota used up, the rest will be looked up tomorrow.")
            break
        except Exception as e:
            print(f"  {t['a']} - {t['t']}: error {e}", file=sys.stderr)
            continue
        found[t["id"]] = {"v": vid, "s": "ytm" if yt else "api", "d": TODAY}
        hits += bool(vid)
        if n % 50 == 0:
            print(f"  {n}/{len(todo)} done, {hits} matched")
            json.dump(found, open(OUT, "w", encoding="utf-8"), indent=0, sort_keys=True)
        if yt:
            time.sleep(0.4)

    json.dump(found, open(OUT, "w", encoding="utf-8"), indent=0, sort_keys=True)
    total = sum(1 for p in playlist if found.get(p["id"], {}).get("v"))
    print(f"Matched {hits} of {len(todo)} looked up. {total} of {len(playlist)} playlist songs now have a YouTube version.")


if __name__ == "__main__":
    main()
