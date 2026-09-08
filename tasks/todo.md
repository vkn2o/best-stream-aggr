# Task List: Movie/TV Show Search Aggregator

See `tasks/plan.md` for full context, acceptance criteria, and verify steps.
Ordered by layer per explicit direction: backend → scraping → frontend.

## Phase 1 — Backend

- [x] B1: SQLite schema + `db/store.py` — `(id, query, matched_title, source, score, timestamp)`; `matched_title`/`source`/`score` are nullable until B4 populates them; `sources` table still deferred (needed for S1, not B1)
- [x] B2: Flask app skeleton — `/health` (not moved to `/api/health` — out of scope of the reconciliation request; flagged in docs/Decisions.md)
- [x] B3: `/api/history` GET — done (no DELETE yet)
- [x] B4: Scraper/scoring interface + fixture implementation — `scraper.Candidate`/`get_candidates`/`refresh_sources`, `scoring.ScoreResult`/`pick_best`, all fixture-backed. **Checkpoint: `Candidate`/`ScoreResult` shapes need your review before S1 starts building real scraping against them.**
- [x] **Follow-up:** wire B4's interface into `/api/search` (B5) — done; `/api/admin/refresh-sources` (B6) route still not built (the `scraper.refresh_sources()` function behind it exists and works)
- [x] B5 (partial): `/api/search` POST route — validates + persists query only, no scraper/scoring call yet (that's B4)
- [ ] B6: `/api/admin/refresh-sources` POST route (fixture-backed)
- [x] Route naming reconciled with plan (`/api/search`, `/api/history`) — 2026-09-07

**Checkpoint: Phase 1 exit — full backend works against fixtures, all backend tests pass. Confirm before Phase 2.**

## Phase 2 — Scraping logic

- [x] S1: Stage A real scrape — `scraper/fmhy_source_list.py` parses FMHY's markdown source (203 sites, 37 starred against the live doc), 1h in-memory cache, wired through `/api/search`; verified live end-to-end
- [x] S2: **re-scoped** — per-site search scraping proved impossible (all top sites are client-rendered SPAs; measured, see docs/Decisions.md). Delivered instead: `title_lookup.py` (IMDb keyless resolution → `matched_title` now populated) + `site_search.py` (deep links into verified site search routes, home-page fallback otherwise) + `best_deep_link` in the API
- [x] S3: **re-scoped and built** as `scraper/availability.py` (not `playwright_fallback.py` — the "fallback for S2's extraction" framing stopped applying once S2 was re-scoped away from scraping results). Renders candidate search pages in headless Chromium to answer **"does this site actually have this title?"**, which is the app's first title-dependent ranking signal and the fix for the "same two sites for every search" bug. Still **not** done from the original S3 scope: (a) extracting actual video-page URLs rather than search-results links, and (b) real subtitle status (still always `"unknown"`). Only `flixer.gd` has a verified detector — see `docs/Decisions.md`.
- [x] **Direct player links:** `_TITLE_ADAPTERS` in `site_search.py` links straight to a title's player where the route is verified (`flixer.gd` movie + tv). Needs `TMDB_API_KEY`; degrades to search links without one.
- [x] **Client-side playback telemetry:** `clients/streamfinder-qoe.user.js` + `POST /api/playback-report` + `telemetry.py` - real measured playback from your own viewing sessions now drives ranking. Min 3 sessions before anything is claimed.
- [ ] Verify player routes for more sites and add them to `_TITLE_ADAPTERS` (only `flixer.gd` verified; `boomflix.qzz.io` publishes `/player/:id` but never reaches a video element)
- [ ] Expand `_SEARCH_ADAPTERS`: only 3 of ~203 sites have verified search routes (`flixer.gd`, `boomflix.qzz.io`, `rivestream.app`). `cinejoy.to`, `popcornmovies.ac`, `67movies.st` are unverified, not confirmed absent
- [x] S4: **built** as `scraper/playback.py` — measured playback quality (start time, rebuffer count/duration) now fills the reserved `latency_score`. Harness verified in a real browser; **no streaming-site player is reachable yet**, so playback reports `unknown` in practice. Remaining: a working `open_player` for any site, plus the real latency probe / reliability allowlist originally scoped here. See docs/Decisions.md.
- [ ] ~~S4 (original scope):~~ Scoring engine — `scoring/evaluator.py` + `site_reliability.json`

**Checkpoint: Phase 2 exit — real scraping/scoring works end-to-end. Confirm before Phase 3 (riskiest phase — external site drift).**

## Phase 3 — Frontend

- [x] F1: Vite + React scaffold (written manually — `npm create vite` is interactive) + `/api` dev proxy to Flask :5000
- [x] F2: `SearchBar` + `api/client.js` wired to `/api/search`
- [x] F3: `ResultPanel` — **link-out, not iframe** (see docs/Decisions.md); shows top_source + best_deep_link, component scores, and honest "subtitles: unknown"
- [x] F4: `HistorySidebar` — lists past searches, click restores; no delete control (no DELETE endpoint exists)
- [x] F5: Styling, loading/error states, verified in a real browser (30/30 frontend tests, clean build, no console errors)
- [ ] **Fix history duplication:** re-running a past search writes a new row, so the sidebar accumulates duplicates (store full result JSON, or de-duplicate on query)
- [ ] Optional: move `/health` to `/api/health` for consistency (only un-prefixed route left)

## Full-stack integration verification (debugging-and-error-recovery)

- [x] Frontend → backend: confirmed via browser network panel (POST /api/search → 201 through Vite proxy)
- [x] FMHY parse + link returned: confirmed live for 3 titles ("the matrix", "inception", "arrival")
- [x] Query saved to SQLite: confirmed by querying `app.db` directly
- [x] Frontend history list updates: confirmed live in browser after each search
- [x] **CORS bug found and fixed:** Flask sent no CORS headers; direct cross-origin fetch failed with opaque "Failed to fetch". Fixed with `flask_cors` allowlist (never `"*"`). 4 regression tests in `tests/test_cors.py`. 78/78 backend + 30/30 frontend tests passing.

## Code review audit (code-review-and-quality) — 2026-09-07

- [x] SQL injection audit: clean, no fix needed (all queries parameterized)
- [x] **Fixed:** IMDb response-shape change crashed `/api/search` with a 500 (`title_lookup.resolve_title` now validates payload shape before use)
- [x] **Fixed:** FMHY outage at cache-expiry took down every search (`get_streaming_sites` now serves stale cache on fetch failure, logs a warning; raises only with no cache at all; also logs when a fetch parses 0 sites)
- [x] **Fixed:** `/api/history` had no pagination (`list_searches` now caps at `DEFAULT_HISTORY_LIMIT`=50)
- [x] **Fixed (minor):** memoized `HistorySidebar`'s `onSelect` callback in `App.jsx`
- [x] `docs/Constraints.md` written with durable rules from these findings
- Final: 88/88 backend tests, 30/30 frontend tests, frontend build clean

**Checkpoint: Phase 3 exit — all of SPEC.md's Success Criteria verified manually.**
