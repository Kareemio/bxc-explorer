"""Tag new playlist tracks with energy, mood, danceability and genre.

Uses GitHub Models (free with the workflow's own GITHUB_TOKEN, no API key or
billing). Only tracks not already in data/tracks.json are sent. Existing tags
are used as worked examples so new tags follow the same scale.

If the model can't be reached, new tracks are still added but marked pending:
they show up under "Everything" and in search, and the next run tries again.
"""
import json
import os
import random
import re
import sys
import time
import urllib.request

HERE = os.path.dirname(__file__)
DATA = os.path.join(HERE, "..", "data")
TRACKS = os.path.join(DATA, "tracks.json")
PLAYLIST = os.path.join(DATA, "playlist.json")
ENDPOINT = os.environ.get("MODELS_ENDPOINT", "https://models.github.ai/inference/chat/completions")
MODEL = os.environ.get("MODEL", "openai/gpt-4.1-mini")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
BATCH = 20

GENRES = {
    "so": "Soul, funk, R&B, gospel", "dh": "Disco, house, techno, club", "el": "Electronic: downtempo, IDM, trip-hop, DnB, dubstep",
    "hh": "Hip-hop, rap", "rg": "Reggae, ska, dub, dancehall", "rk": "Rock, classic rock, blues-rock", "pk": "Punk, post-punk, garage",
    "in": "Indie, alternative", "ps": "Psych, krautrock, prog, post-rock, stoner", "fo": "Folk, singer-songwriter, country",
    "jz": "Jazz", "bl": "Blues", "af": "African", "la": "Latin, Brazilian, Caribbean", "jp": "Japanese, city pop, Asian",
    "me": "Arabic, Turkish, Persian, South Asian", "eu": "French, Italian, German, Portuguese and other European-language pop or chanson",
    "sp": "Synth-pop, new wave, 80s/90s pop", "am": "Ambient, classical, spoken word, very calm",
}

SYSTEM = """You tag songs for a mood-based playlist browser. For each track return:
year: original release year of the recording (int, best estimate)
e: energy 1-5 (1 = still/ambient, 3 = mid-tempo, 5 = flat out)
v: valence 1-5 (1 = dark/sad, 3 = neutral, 5 = joyful/bright)
d: danceability 1-5 (1 = no beat, 5 = floor-filler)
ac: acoustic 1-5 (1 = fully electronic, 5 = fully acoustic)
i: 1 if instrumental (no lead vocal), else 0
g: 1-3 genre codes from this list, most fitting first:
%s
lc: true if you don't really know this track and are guessing from the artist or title, else false.
Answer with JSON only: {"tracks":[{"id":...,"year":...,"e":...,"v":...,"d":...,"ac":...,"i":...,"g":[...],"lc":...}]}""" % "\n".join(f"  {k} = {v}" for k, v in GENRES.items())

TITLE_JUNK = re.compile(
    r"\s+-\s+(\d{4}\s+)?(Remaster(ed)?|Digitally Remastered|Stereo|Mono|Single Version|Radio Edit|Remastered \d{4}|\d{4} Remaster(ed)?( Version)?|\d{4} Mix|Original)(\s*\d{4})?\s*$",
    re.I,
)


def clean_title(t):
    t = TITLE_JUNK.sub("", t)
    t = re.sub(r"\s*\((\d{4} )?- ?Remaster(ed)?\)\s*$", "", t, flags=re.I)
    t = re.sub(r"\s*\(\d{4} (Stereo )?Remaster\)\s*$", "", t, flags=re.I)
    return t.strip()


def ask(batch, examples):
    shots = [{"title": x["t"], "artist": x["a"], "id": x["id"], "year": x["y"], "e": x["e"], "v": x["v"],
              "d": x["d"], "ac": x["ac"], "i": x["i"], "g": x["g"], "lc": x["lc"]} for x in examples]
    user = ("Examples of correctly tagged tracks from this playlist:\n" + json.dumps(shots, ensure_ascii=False) +
            "\n\nTag these tracks the same way:\n" +
            json.dumps([{"id": t["id"], "title": t["title"], "artist": ", ".join(t["artists"]), "album": t["album"]} for t in batch], ensure_ascii=False))
    body = {"model": MODEL, "temperature": 0.2, "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]}
    req = urllib.request.Request(ENDPOINT, data=json.dumps(body).encode(), method="POST", headers={
        "Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        content = json.load(r)["choices"][0]["message"]["content"]
    m = re.search(r"\{.*\}", content, re.S)
    return json.loads(m.group(0))["tracks"]


def clamp(x, lo=1, hi=5):
    try:
        return max(lo, min(hi, int(round(float(x)))))
    except Exception:
        return 3


def main():
    tracks = json.load(open(TRACKS, encoding="utf-8"))
    playlist = json.load(open(PLAYLIST, encoding="utf-8"))["tracks"]
    by_id = {t["id"]: t for t in tracks}
    todo = [p for p in playlist if p["id"] not in by_id or by_id[p["id"]].get("pending")]
    print(f"{len(todo)} tracks need tagging")
    if not todo:
        return
    tagged_examples = [t for t in tracks if not t.get("pending") and not t["lc"]]
    random.seed(len(tracks))
    for start in range(0, len(todo), BATCH):
        batch = todo[start:start + BATCH]
        result = {}
        if TOKEN:
            for attempt in range(3):
                try:
                    out = ask(batch, random.sample(tagged_examples, min(24, len(tagged_examples))))
                    result = {o.get("id"): o for o in out if isinstance(o, dict)}
                    break
                except Exception as e:
                    print(f"Model call failed (attempt {attempt + 1}): {e}", file=sys.stderr)
                    time.sleep(10 * (attempt + 1))
        for p in batch:
            o = result.get(p["id"])
            entry = {"id": p["id"], "t": clean_title(p["title"]), "a": ", ".join(p["artists"])}
            if o:
                g = [x for x in (o.get("g") or []) if x in GENRES][:3] or ["in"]
                entry.update({"y": clamp(o.get("year"), 1900, 2100), "e": clamp(o.get("e")), "v": clamp(o.get("v")),
                              "d": clamp(o.get("d")), "ac": clamp(o.get("ac")), "i": 1 if o.get("i") in (1, True, "1") else 0,
                              "g": g, "lc": bool(o.get("lc"))})
            else:
                # Not tagged yet: matches only "Everything" and search until a later run succeeds.
                entry.update({"y": 0, "e": 0, "v": 0, "d": 0, "ac": 0, "i": 0, "g": [], "lc": True, "pending": True})
            by_id[p["id"]] = entry
        print(f"Tagged {sum(1 for p in batch if not by_id[p['id']].get('pending'))}/{len(batch)} in this batch")
        time.sleep(5)
    # Keep every tagged track ever seen (so tags survive a song being removed and re-added).
    ordered = list(by_id.values())
    json.dump(ordered, open(TRACKS, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":
    main()
