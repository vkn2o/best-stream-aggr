# Architecture

High-level map of the system: modules, services, and how data moves between them.
Keep this at the shape level — no deep implementation detail.

## System shape

```
┌────────────┐      HTTP (fetch)      ┌───────────────────┐
│  Frontend   │ ─────────────────────▶ │      Backend       │
│ React+Vite  │ ◀───────────────────── │       Flask         │
└────────────┘        JSON             └───────────┬─────────┘
                                                     │
                          ┌──────────────────────────┼───────────────────────────┐
                          ▼                          ▼                            ▼
                 ┌────────────────┐        ┌──────────────────┐        ┌──────────────────┐
                 │ Scraper: Stage A│        │ Scraper: Stage B  │        │  Scoring engine   │
                 │ FMHY directory  │───────▶│ per-site title    │───────▶│  (evaluator.py)    │
                 │ → source list   │ cached │ search → candidate│        │  ranks candidates  │
                 └────────────────┘  list   │ watch/embed URLs  │        └─────────┬──────────┘
                                             └──────────────────┘                  │
                                                                                    ▼
                                                                          ┌──────────────────┐
                                                                          │  SQLite (app.db)   │
                                                                          │  sources, searches │
                                                                          └──────────────────┘
```

## Modules

- **Frontend (React + Vite)** *(implemented)* — `SearchBar`, `ResultPanel`,
  `HistorySidebar`, over a thin `api/client.js`. Holds no scraping or
  scoring logic; renders what the API returns, including the honest
  "subtitles: unknown" and the home-page-vs-direct-link distinction. Sources
  are **links, not iframes** (see docs/Decisions.md). The Vite dev server
  proxies `/api` to Flask on :5000 for the normal dev path; Flask also sets
  CORS headers (`flask_cors`, allowlisting only known dev origins) so a
  direct cross-origin request — bypassing the proxy — works too, rather
  than failing with an opaque browser-only error. Found and fixed via
  full-stack integration testing; see docs/Decisions.md.
  `SearchBar` also owns a debounced (300ms) autocomplete dropdown against
  `/api/suggestions` — see docs/Decisions.md for why this lives in
  `SearchBar` rather than a separate component.

- **Backend API (Flask)** — routes for `search`, `history`, and an admin
  trigger to refresh the cached source list. Orchestrates the two scrape
  stages and the scoring engine per request; the only component that talks
  to third-party sites or the database.

- **Scraper — Stage A (`fmhy_source_list.py`)** *(implemented)* — fetches
  FMHY's video directory in **markdown** form (the source the wiki renders
  from) and parses it into a ranked list of sites: name, url, list
  position, starred flag, section. Cached in process for an hour, so only
  the first search in that window pays the download. FMHY's own ordering is
  the ranking signal — see docs/Decisions.md.

- **Title resolution (`title_lookup.py`)** *(implemented)* — resolves the
  raw query to a canonical title/year/kind/IMDb id via IMDb's keyless
  suggestion endpoint. Optional: a failure here degrades the search rather
  than failing it. `resolve_suggestions()` is the same endpoint's raw match
  list, capped and shaped for the autocomplete dropdown (title, year, kind,
  IMDb id, poster `image_url` straight from IMDb's own response — no
  separate image lookup); `resolve_title()` is now just
  `resolve_suggestions(query, limit=1)`'s first result.

- **Autocomplete (`GET /api/suggestions`)** *(implemented)* — a thin route
  over `scraper.get_suggestions()`, which wraps `resolve_suggestions()` the
  same way `_resolve_quietly()` wraps `resolve_title()`: any failure (IMDb
  down, a malformed response body) degrades to an empty suggestion list
  with a 200, never an error surfaced to the dropdown. Queries under 2
  characters short-circuit the same way, before touching IMDb at all.

- **Stage B (`site_search.py`)** *(implemented, re-scoped)* — builds a link
  per site for the resolved title. It does **not** scrape site search
  results: those sites render results client-side, so there is nothing to
  parse in the response. Sites with a verified search route get a deep link
  into their own search; everything else gets a home-page link, flagged as
  such. A Playwright path (`playwright_fallback.py`, task S3) is what would
  reach actual video pages and real subtitle status.

- **Availability probe (`scraper/availability.py`)** *(implemented, task
  S3)* — the app's **only title-dependent ranking signal**. Renders the
  strongest few candidate search pages in headless Chromium and reads
  whether that site actually has *this* title. Detection is per-domain and
  only for domains verified against the live site (today: one), because the
  sites echo the search term back even on a zero-result page — the result
  *count*, not the title text, is the signal. Anything unverified, blocked,
  empty or changed degrades to "unknown", never to a wrong confident answer
  or a failed search. Costly (~8s/search) and needs Playwright, so it is
  **off by default** and enabled explicitly by the dev server.

- **Playback probe (`scraper/playback.py`)** *(implemented, task S4)* —
  answers the question availability can't: does the stream actually *play*
  well here? Opens the playback page for sources already confirmed to have
  the title, watches the `<video>` for a fixed 10s window, and reports time
  to start, rebuffer count and total buffering. Site-specific navigation
  lives in small pluggable adapters (`_PLAYBACK_ADAPTERS`); measurement is
  shared so every site is judged identically. **No site adapter can reach a
  player today** (see docs/Decisions.md), so this reports "unknown" in
  practice and is scored neutrally — the harness is real and verified, the
  site coverage is not there yet. Off by default; the most expensive thing
  the app does.

- **TMDB id mapping (`scraper/tmdb_lookup.py`)** *(implemented)* - the
  sites' player routes key on TMDB ids while the app resolves IMDb ids.
  Bridges the two via TMDB's `/find` endpoint. Entirely optional: with no
  `TMDB_API_KEY` it returns None and links fall back to search URLs.

- **Playback telemetry (`telemetry.py`, `clients/`, `POST /api/playback-report`)**
  *(implemented)* - the app's only working source of real playback data.
  The sites gate streams against automated sessions, so measurement happens
  in the **viewer's own browser** (a userscript) and is posted back, stored
  in `playback_reports`, and aggregated into the same `PlaybackMetrics` the
  scorer already consumes. Enforces a minimum sample size and separates
  title-specific from site-wide evidence.

- **Scoring engine (`scoring/`)** *(partly implemented)* — pure logic, no
  network calls. Ranks on FMHY's curation (starred entries first, then list
  position) plus, when known, the per-title availability above — which is
  what stops every search from returning the same winner. The `ScoreResult`
  contract carries reliability/subtitle/latency components so the frontend
  can show *why* a source won; availability is folded into reliability to
  keep that contract stable, with the raw status exposed on the candidate.
  `latency_score` now carries **measured playback quality** (task S4) —
  0.0 whenever playback wasn't measured. Subtitles remain a placeholder.

- **Database (SQLite)** — one table today: `searches` (id, query,
  matched_title, source, score, timestamp) — one row per user search,
  winner only, no per-candidate history. The `sources` table originally
  planned for Stage A was not needed: the FMHY list is cached in memory
  instead (see docs/Decisions.md).

## Data flow (one search)

1. Frontend posts a query to `POST /api/search`.
2. Backend loads cached `sources` from SQLite (Stage A output — not
   re-scraped per search).
3. Backend runs Stage B against each cached source for the title, collecting
   candidate watch/embed URLs.
4. Scoring engine ranks candidates; the backend probes the winning
   candidate's latency as part of scoring.
5. Backend writes one `searches` row (query, chosen source, score) and
   returns the winner + component scores as JSON.
6. Frontend renders `ResultPlayer` (iframe, or link fallback if framing is
   blocked) and prepends the entry to `HistorySidebar`.

See `docs/Flow.md` for finer-grained call chains once implementation starts,
and `SPEC.md` at the repo root for the full specification this map is
derived from.
