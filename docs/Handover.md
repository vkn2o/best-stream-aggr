# Handover

A living record of where things stand right now. Updated at the end of every
session. Full rationale for every decision mentioned here lives in
`docs/Decisions.md`; this file is the current snapshot, not the log.

## Done (as of 2026-09-08)

**Playback telemetry verified end-to-end in a real browser (today, newest work):**
- The Tampermonkey userscript was tested against a live flixer.gd player
  page: it ran, measured a session (`started`, 4.4s start-up, 1 rebuffer of
  627ms over 31s), posted it, and the search UI reflected it. The whole
  reported-playback chain works.
- **Two bugs found and fixed.** (1) A real stall was reported as "no
  rebuffering". `playback_stats` rounded the fractional per-session average
  (0.2) to 0 while `rebuffer_ms` stayed 125, and the UI gated its wording on
  the count alone. Count is now fractional and the UI checks both fields.
  (2) Every reported session stored no title at all, because Flixer's
  player page has no IMDb id in it; the userscript now sends the TMDB
  reference from the player URL and the backend maps it back. Both in
  `docs/Decisions.md`. **268 backend / 82 frontend tests pass.**
- **Reinstall the userscript after this change** - Tampermonkey holds a
  copy, so the running script is whatever was installed, not the file.
- **(3) "Opened but never pressed play" was scored as a failed stream.**
  Playback is now measured from the play request, not from page load, and
  a session where play was never requested is not reported at all. This
  also fixes `startup_ms`, which had been including the viewer's own
  deliberation time.
- **One known gap remains, not yet fixed** (see "In progress" below): the
  top card's pill and note can contradict each other.
- **Rows 4, 8, 11, 12 and 13 in `app.db` are artifacts of the old
  behaviour** (`started=0` sessions that were never played), and rows
  recorded before this change measured `startup_ms` from page load, so
  they are not comparable with new ones. Worth clearing the table before
  trusting the numbers.

**Direct player links + real playback telemetry (today, newest work):**
- **Results can now link straight to a title's player**, not just a search
  page - closing the gap open since S3. Routes came from Flixer's own
  published bundle and were verified live: `/watch/movie/603` loads a
  player, `/watch/tv/1396/1/1` loads "Breaking Bad S1 Episode 1". Boomflix
  publishes `/player/:id` but never reaches a video element, so it is
  deliberately **not** registered.
- Needs a **TMDB id** (`scraper/tmdb_lookup.py`) because those routes key on
  TMDB, not IMDb. Set `TMDB_API_KEY` to enable it. **Without a key
  everything still works** and links fall back to search URLs - verified in
  all three states (movie / tv / no key).
- **Playback is now measured in your own browser**, via
  `clients/streamfinder-qoe.user.js` (see `clients/README.md` to install -
  this is a manual step). It posts to `POST /api/playback-report`;
  `telemetry.py` aggregates stored reports into the same `PlaybackMetrics`
  the scorer already consumed, so `scoring._playback_score()` was reused
  unchanged.
- Why client-side: the sites gate their streams against automated sessions,
  and defeating that is permanently out of scope (`docs/Constraints.md` #5).
  Your browser passes the gate normally. See `docs/Decisions.md` for the
  full evidence, so this is not re-investigated.
- Two honesty rules are enforced in code: nothing is claimed below
  **3 reported sessions**, and site-wide evidence is labelled `scope="site"`
  and rendered as "(site-wide, N sessions)" rather than passed off as being
  about the searched title.
- **Verified end to end:** three reported sessions moved Flixer from 1.68 to
  2.38 with `provenance=reported, sample_size=3, scope=title`; a malformed
  report was rejected 400 and not stored.
- **238 backend tests + 3 live browser tests, 74 frontend tests**, build
  clean.


**Task S4 — measured playback quality (today, newest work):**
- `scraper/playback.py` measures how a stream actually behaves: whether it
  started, time to start, rebuffer count, total buffering — over a **fixed
  10s window applied identically to every site**, so sites are comparable.
  Per-site navigation lives in pluggable adapters; measurement is shared.
- Scoring fills the slot reserved for it: `latency_score` (was the
  `_UNMEASURED_LATENCY_SCORE` placeholder). +0.4 for playing, up to +0.3 for
  a fast start, −0.2/rebuffer, −0.6 × share of window buffering, −1.5 if it
  never started, **0.0 when unmeasured**. A lower-ranked source with smooth
  playback now beats FMHY's favourite; a top-ranked one that fails loses to
  an untested source. Both are covered by tests.
- **Honest status: no streaming-site player is reachable, so playback is
  `unknown` in practice.** Flixer (the only probeable site) has click-driven
  search cards with no title links; clicking never navigates and no `<video>`
  or iframe ever appears. `FlixerPlaybackAdapter` reports that, and carries
  `enabled = False` so no browser is launched for it at all — a search with
  playback enabled costs the same ~13s as availability alone. The API returns
  `playback: null` and the UI says "Playback not measured".
- **The harness itself is verified** by a `live_browser` test that attaches
  the real instrumentation to a real `<video>` in real Chromium and asserts
  the measured numbers. So the machinery is proven; only site coverage is not.
- Frontend `ResultPanel` now shows an evidence line per source: availability
  ("Has the title · 59 results" / "Not on this site") and playback ("Played
  in 1.2s · no rebuffering" / "3 rebuffers · 2.1s buffering" / "Playback not
  measured").
- **167 backend tests + 2 live browser tests, 56 frontend tests, all
  passing**; build clean. `pytest.ini` now excludes `live_browser` by
  default (`pytest -m live_browser` to run them); `conftest.py` blocks the
  playback browser boundary like the other two.
- Enable with `STREAM_FINDER_PLAYBACK=1` (off by default); it implies
  availability probing, since it only measures sources known to have the title.


**Task S3 — per-title availability:** fixes the
"same two sites for every search" bug.
- **The title was never being lost** — that was the reported diagnosis and
  it was wrong. Resolution and the deep-link URL were always correct per
  query. The real cause: `scoring._score()` had *no title input at all*, so
  the winner was mathematically identical for every search. Full evidence
  in `docs/Decisions.md` — read it before re-investigating this.
- `scraper/availability.py`: renders the strongest candidate search pages
  in headless Chromium and reads whether the site actually has this title.
  Scoring now applies +0.5 available / −2.0 unavailable / 0 unknown, which
  makes ranking title-dependent for the first time.
- **Verified live:** "The Matrix" → Flixer `available`, 59 results (wins at
  1.68, over Cinejoy's 1.40); a title Flixer lacks → `unavailable`, 0
  results, demoted, and a different site wins.
- **Off by default** (`create_app(probe_availability=False)`); the dev
  server enables it, `STREAM_FINDER_PROBE=0` disables it. Costs **~8s per
  search** and needs `playwright` + `python -m playwright install chromium`.
  Missing Playwright degrades to "unknown" — search still works.
- No test launches a browser (`conftest.py` blocks the render boundary like
  it blocks `requests.get`).

## Done (earlier, as of 2026-09-07)

**Live autocomplete:**
- `GET /api/suggestions?q=` — up to 5 IMDb matches (title, year, kind,
  imdb_id, poster `image_url`), reusing the existing IMDb suggestion
  lookup (`title_lookup.resolve_suggestions`, `resolve_title` is now just
  its 1-result case). Queries under 2 chars and any IMDb/shape failure
  both degrade to `{"suggestions": []}` with a 200 — never an error.
- `SearchBar` fetches suggestions 300ms after the user stops typing,
  renders them in a keyboard-navigable dropdown (Up/Down/Enter/Escape,
  click, click-outside-to-close) with the poster on the left, and
  selecting one fills the input, runs the normal search, and closes the
  dropdown — the existing plain-text search still works unchanged if
  suggestions are unavailable.
- **Real bug found and fixed via live browser testing, not the test
  suite:** selecting a suggestion (or restoring a query from history)
  re-triggered a suggestion fetch and popped the dropdown back open right
  after it had just closed. Fixed with a one-shot suppress flag; two
  regression tests added. Full detail in `docs/Decisions.md`.
- **105 backend tests, 49 frontend tests, all passing** (backend: 88 → 105
  from adding `resolve_suggestions` + the new route's tests; frontend:
  30 → 49). `npm run build` clean. Verified live end-to-end against real
  IMDb data (not just fixtures) with the dev server running.

**Spec & planning:** `SPEC.md`, `tasks/plan.md`/`todo.md` (layer-ordered:
backend → scraping → frontend, per explicit direction), `docs/Architecture.md`,
`docs/Flow.md`, `docs/Constraints.md` all written and kept current.

**Backend — fully working, real data, no fixtures left in the hot path:**
- `db/store.py` + `schema.sql`: `searches` table (`id`, `query`,
  `matched_title`, `source`, `score`, `timestamp`). `list_searches` caps at
  50 rows by default (`DEFAULT_HISTORY_LIMIT`) — added today after finding
  it was unbounded.
- `app.py`: Flask factory, `/health`, CORS via `flask_cors` allowlisting
  only known dev origins (added today — see CORS finding below).
- `POST /api/search`: resolves a title via IMDb's keyless suggestion API
  (`scraper/title_lookup.py`), gets FMHY's ranked site list
  (`scraper/fmhy_source_list.py`, parses FMHY's markdown source, 1h cache,
  **now falls back to stale cache on fetch failure** — added today), builds
  a link per site (`scraper/site_search.py` — a verified-route deep link
  where possible, else an honest home-page link), scores candidates
  (`scoring/`, ranks by FMHY star tier + list position), persists the
  query + chosen source, and returns `{search, matched_title, year,
  imdb_id, top_source, best_deep_link, history}`.
- `GET /api/history`: the 50 most recent searches, newest first.
- `GET /api/suggestions?q=`: live autocomplete, added today — see above.
- **105/105 backend tests pass**, fully offline (network hard-blocked in
  `conftest.py` outside `@pytest.mark.allow_network`).

**Visual identity (frontend-design, today):** replaced generic dark-mode
styling with a "cable tuner" system — FMHY rank shown as a channel number
(VT323), deep-link-vs-home-page shown as a signal-status pill (cyan
"direct" / red "home page only"), amber phosphor accent, scanline texture.
See `docs/Decisions.md` for the full rationale and self-check against
generic AI-design defaults. No tested copy changed; 30/30 frontend tests
pass unmodified (at the time — autocomplete has since added 19 more, see
above).

**Frontend — fully working, browser-verified:**
- Hand-written Vite + React 18 (`npm create vite` is interactive, so files
  were written directly). `SearchBar` (now also owns the autocomplete
  dropdown), `ResultPanel`, `HistorySidebar`, `api/client.js`. Vite
  dev-proxies `/api` → Flask :5000.
- **49/49 Vitest tests pass**, `npm run build` clean.
- Verified live in a real browser multiple times today: search → real
  title/year/source, sidebar updates, history-click restores, live
  autocomplete against real IMDb data, no console errors.

**Today's code review (code-review-and-quality, 3 real bugs found & fixed):**
1. SQL injection — audited, clean (all queries parameterized). No fix needed.
2. IMDb response-shape change crashed the whole search with a bare 500
   (`AttributeError` inside `title_lookup.resolve_title`, not caught by the
   narrower `except requests.RequestException`). Fixed: validates payload
   shape, skips malformed entries instead of crashing.
3. Any FMHY hiccup at the moment the hourly cache expired took down every
   search, even with a perfectly good stale cache sitting there. Fixed:
   serves stale cache on fetch failure (logged), raises only when there's
   no cache at all; also logs a warning when a fetch succeeds but parses
   zero sites (signals FMHY changed its markdown structure).
4. `/api/history` had no pagination — fixed (see `DEFAULT_HISTORY_LIMIT`
   above). Minor: memoized a callback passed to `HistorySidebar` to avoid
   defeating a future `React.memo`.
   Every fix was reproduced first, then TDD'd, then re-verified against the
   original repro. See `docs/Decisions.md` for full detail per finding.

**Earlier full-stack integration pass** (debugging-and-error-recovery) also
found and fixed a real CORS gap: Flask sent no CORS headers at all, so any
direct cross-origin request (bypassing the Vite proxy) failed with an
opaque `TypeError: Failed to fetch`. Fixed with an explicit origin
allowlist (never `"*"`).

## In progress / known gaps

- **Search results, not video pages.** FMHY gives ranked *sites*; links
  open a site's search (where a verified route exists) or its home page —
  never the video page itself. Only 3 of ~203 sites have a verified search
  route (`flixer.gd`, `boomflix.qzz.io`, `rivestream.app`). S3 now renders
  those pages to confirm *whether* a site has the title, but still doesn't
  extract the video-page URL from the rendered result — that part is open.
- **Only 1 site is actually probeable.** Of the 3 deep-linkable sites, only
  `flixer.gd` exposes a usable signal; Boomflix renders an identical shell
  for real and nonsense queries, and Rive renders an empty body headlessly.
  So per-title differentiation currently rests on one site's catalog.
  Adding more verified detectors to `_AVAILABILITY_DETECTORS` is additive
  and is the highest-value next step for this feature.
- **`subtitle_status` is always `"unknown"`** — would need reading the
  player's tracks on the rendered page, which S3 doesn't do yet. Scoring
  only credits a positively-known `"available"`, so it never contaminates
  ranking.
- **Playback data starts empty.** Reported sessions accumulate only as you
  watch things with the userscript installed, so playback reads "not
  measured" until a source reaches 3 sessions. Correct, but it means the
  feature is quiet at first.
- **Title-scoped playback evidence needs `TMDB_API_KEY`.** Reports now
  carry the player URL's TMDB reference and the backend maps it to an IMDb
  id, so `scope="title"` works - but only with a key set. Without one,
  sessions are still stored and counted, as site-wide evidence.
- **A source card's pill and note can contradict each other.** The pill
  reads `link_kind` while the note below reads `isDirect`, so the top card
  can show "DIRECT LINK" above "This is the site's home page - search there
  yourself". Observed live.
- **The userscript's `@match` list needs maintenance** as sites change
  domains, and must stay in step with `_PLAYER_ORIGINS` in `backend/app.py`.
- **No iframe embed** — sources are `target="_blank"` links, a deliberate
  deviation from SPEC.md (embedding a search-results/home-page link would
  render blank). Revisit once S3 produces real video-page URLs.
- **History-click re-runs the search** rather than replaying the stored
  row, because the stored row lacks the score breakdown `ResultPanel`
  needs. Side effect: **re-running a past search appends a duplicate row**
  (observed live) — not yet fixed.
- **`/api/admin/refresh-sources` (task B6) route doesn't exist** — the
  `scraper.refresh_sources()` function behind it works and is tested, just
  unreachable over HTTP.
- Not yet built: task **S4** (real latency probe + a maintained reliability
  allowlist to replace the star/position heuristic).
- Three `SPEC.md` open questions (refresh cadence, allowlist seeding,
  fuzzy-title-matching UI) are answered with defaults, not yet confirmed.
- **`/api/suggestions` has no caching**, unlike the FMHY list — every
  debounced keystroke that clears the 2-char minimum is a live IMDb call.
  Fine at personal-app volume; would need a short-TTL cache (same pattern
  as `fmhy_source_list`) before this app is used by more than one person
  at a time or IMDb rate-limits it.

## Broken

_(nothing — 238/238 backend tests (+3 live), 74/74 frontend tests, all passing)_

## Avoid

- Don't scrape live FMHY/third-party sites in automated tests — use saved
  HTML/JSON fixtures; the network is hard-blocked in backend tests by
  default (`conftest.py`).
- Don't promote Playwright to the default scraper path — S3 is a fallback
  for rendering-dependent extraction, not the hot path.
- Don't attempt to bypass CAPTCHAs/paywalls/anti-bot protection on any
  candidate site — skip the site instead (SPEC.md Boundaries).
- Don't add an unbounded list endpoint, string-build SQL, use `origins="*"`
  for CORS, or trust an external response's shape without validating it —
  see `docs/Constraints.md` for the full list, each backed by a real bug
  found this session.
- Don't fix the history-duplication or B6-route gaps by guessing — they're
  scoped above; ask before choosing an approach (store full result JSON vs.
  de-duplicate on query, for the former).
