# Playback quality reporter (userscript)

`streamfinder-qoe.user.js` measures how smoothly a stream actually plays and
reports it back to your local Stream Finder, so searches can recommend the
source that buffers least.

## Why this is a browser script and not part of the backend

Stream Finder cannot measure playback itself. The streaming sites gate their
stream sources against automated sessions, and working around that is out of
scope permanently (see `docs/Constraints.md` #5). Your own browser plays them
normally, so the measurement happens there instead — the same client-side
approach real streaming platforms use for quality-of-experience monitoring.

## Install

1. Install [Violentmonkey](https://violentmonkey.github.io/) or
   [Tampermonkey](https://www.tampermonkey.net/) in your browser.
2. Open `streamfinder-qoe.user.js` from this folder in the extension's
   "new script" editor, or drag the file onto the browser with the extension
   installed, and confirm the install.
3. Start the backend (`cd backend && python app.py`). The script posts to
   `http://localhost:5000` — if the app isn't running, it silently does
   nothing.
4. Watch something. Roughly 30 seconds after you press play it sends one
   report, and again when you leave the page.

Nothing is sent for a page you open and never play - that session measured
nothing about the source, and reporting it would score the site as a broken
stream.

### Naming the title you watched

Flixer's player pages carry no IMDb id — they identify a title by TMDB id in
the URL (`/watch/movie/603`). The script sends that reference instead, and the
backend maps it back to an IMDb id, which needs **`TMDB_API_KEY`** set (the
same key the direct player links use). Without a key nothing breaks: the
session is still stored and still counts, just as site-wide evidence rather
than evidence about that one title.

Nothing appears in the UI until a source has at least **3** reported sessions
(`telemetry.MIN_SAMPLE_SIZE`) — below that the app says "Playback not
measured" rather than ranking on a single noisy evening.

## What it sends

Only playback numbers, to your own machine:

| Field | Meaning |
| --- | --- |
| `site` | the hostname you were watching on |
| `imdb_id` | the title, when the page exposes one — otherwise `null` |
| `tmdb_id` / `media_type` | the title as the player URL names it, when there is no IMDb id |
| `started` | whether the video ever played |
| `startup_ms` | time from pressing play to the first frame |
| `rebuffer_count` / `rebuffer_ms` | how often, and how long, it stalled |
| `observed_ms` | how long the session was watched for |

No page content, no account details, no browsing history, and nothing leaves
`localhost`.

## Adding another site

Add the site's player URL to the `@match` list at the top of the script, and
add the same origin to `_PLAYER_ORIGINS` in `backend/app.py` so the browser is
allowed to post to the API from it. Keep the two in step.

## Note for maintainers

The metric definitions in `createTracker` deliberately mirror
`backend/scraper/playback.py`, so a reported session and a probed one mean the
same thing. This file is the single source of truth for that logic — the
Vitest suite (`frontend/src/qoe/tracker.test.js`) reads and evaluates it
rather than keeping a copy that could drift.
