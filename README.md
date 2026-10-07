# Bangers Xchange Club explorer

A mood-based browser for the club's Spotify playlist. Every other day GitHub reads the playlist, tags any new songs, and republishes the page. No server, no Spotify key, no paid API.

## How it works

| Step | Script | What it does |
|---|---|---|
| Read | `scripts/scrape.py` | Opens the public playlist page in a headless browser and scrolls through it. Stops without changing anything if it reads fewer than 97% of the rows. |
| Tag | `scripts/tag.py` | Sends only new songs to GitHub Models (free with the workflow's own token). Existing tags are used as examples so new ones match. If tagging fails, new songs still appear under "Everything" and "Just added", and the next run tries again. |
| Build | `scripts/build.py` | Fills `site/template.html` with the tracks and writes `_site/index.html`. |
| Publish | `.github/workflows/refresh.yml` | Runs the three steps daily at 4:07am UK time, saves the data back to the repo, and deploys to GitHub Pages. |

`data/tracks.json` is the tag library (every song ever tagged). `data/playlist.json` is the playlist as last read.

## One-time setup

1. Put these files in a new public repository (for example `bxc-explorer`).
2. **Settings → Pages → Build and deployment → Source:** choose **GitHub Actions**.
3. **Actions** tab: if GitHub asks, click to enable workflows. Open **Refresh playlist explorer** and click **Run workflow**.
4. When it finishes (about 3 minutes), the page is at `https://<your-username>.github.io/bxc-explorer/`.

## Fixing a tag by hand

Find the song in `data/tracks.json` and edit its numbers (all 1-5): `e` energy, `v` brightness, `d` danceability, `ac` acoustic. `i` is 1 for instrumentals. `g` holds genre codes, listed in `scripts/tag.py`. Committing the change republishes the page.

## If a run fails

GitHub emails you. The live page keeps the last good version.

- **"Only read N of M rows"** or a timeout in *Read the playlist*: Spotify was slow or changed its page. Run it again; if it keeps failing, the selectors in `scrape.py` need updating.
- **Model call failed** in *Tag new tracks*: GitHub Models was busy or the model name changed. Songs are added untagged and retried next run. To switch model, set a `MODEL` environment variable on that step (see github.com/marketplace/models).
- **Permission denied on push**: Settings → Actions → General → Workflow permissions → **Read and write**.
