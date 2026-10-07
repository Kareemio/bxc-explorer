"""Read every track in the public Spotify playlist by scrolling its web page.

No Spotify developer key is needed. Writes data/playlist.json (ids in playlist
order, plus title/artist for each). Exits with an error, and leaves the old file
untouched, if it can't read close to the full playlist.
"""
import json
import os
import sys
import time

from playwright.sync_api import sync_playwright

PLAYLIST_ID = os.environ.get("PLAYLIST_ID", "2YOQqyCK4VP8Owz1TF7sNB")
URL = f"https://open.spotify.com/playlist/{PLAYLIST_ID}"
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "playlist.json")

# Runs inside the page. Only reads rows inside the playlist's own tracklist,
# so Spotify's "Recommended songs" block underneath is ignored.
COLLECT_JS = r"""
async () => {
  const pl = document.querySelector('[data-testid="playlist-tracklist"]');
  if (!pl) return {error: 'no playlist tracklist on page'};
  const grid = pl.querySelector('[aria-rowcount]') || pl;
  const expected = parseInt(grid.getAttribute('aria-rowcount') || '0', 10) - 1; // minus header row
  const found = {};
  const grab = () => {
    pl.querySelectorAll('[data-testid="tracklist-row"]').forEach(r => {
      const row = r.closest('[aria-rowindex]');
      const idx = row ? +row.getAttribute('aria-rowindex') : null;
      const links = [...r.querySelectorAll('a')];
      const t = links.find(a => (a.getAttribute('href') || '').startsWith('/track/'));
      if (!t || idx == null) return;
      const id = t.getAttribute('href').split('/')[2].split('?')[0];
      const artists = links.filter(a => (a.getAttribute('href') || '').startsWith('/artist/')).map(a => a.textContent.trim());
      const alb = links.find(a => (a.getAttribute('href') || '').startsWith('/album/'));
      found[idx] = {idx, id, title: t.textContent.trim(), artists, album: alb ? alb.textContent.trim() : ''};
    });
  };
  let sc = pl.querySelector('[data-testid="tracklist-row"]');
  while (sc && !(sc.scrollHeight > sc.clientHeight + 50 && /(auto|scroll)/.test(getComputedStyle(sc).overflowY))) sc = sc.parentElement;
  if (!sc) sc = document.scrollingElement;
  let last = -1, stable = 0;
  for (let i = 0; i < 600 && stable < 8; i++) {
    grab();
    sc.scrollTop += 600;
    await new Promise(r => setTimeout(r, 400));
    const n = Object.keys(found).length;
    if (n === last) stable++; else { stable = 0; last = n; }
  }
  grab();
  return {expected, rows: Object.values(found).sort((a, b) => a.idx - b.idx)};
}
"""


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            viewport={"width": 1280, "height": 1000},
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"),
            locale="en-US",
        )
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        # Decline the cookie banner if one appears.
        try:
            page.locator("#onetrust-reject-all-handler").click(timeout=5000)
        except Exception:
            pass
        page.wait_for_selector('[data-testid="playlist-tracklist"] [data-testid="tracklist-row"]', timeout=60000)
        time.sleep(2)
        result = page.evaluate(COLLECT_JS)
        browser.close()

    if "error" in result:
        sys.exit("Scrape failed: " + result["error"])
    rows, expected = result["rows"], result["expected"]
    # Same track can sit in a playlist twice; keep the first appearance.
    seen, tracks = set(), []
    for r in rows:
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        tracks.append({"id": r["id"], "title": r["title"], "artists": r["artists"], "album": r["album"]})
    print(f"Read {len(rows)} rows ({len(tracks)} unique) of {expected} expected")
    if expected <= 0 or len(rows) < expected * 0.97:
        sys.exit(f"Only read {len(rows)} of {expected} rows; keeping the previous data.")
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"playlist_id": PLAYLIST_ID, "count": len(rows), "tracks": tracks}, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
