# Implementation Plan: Movie/TV Show Search Aggregator

Derived from `SPEC.md`. Applies `incremental-implementation`: each task is a
thin, independently testable/committable slice, but per explicit direction
this plan is **ordered by layer** (backend → scraping → frontend) rather
than by full vertical feature slices. To keep each backend task genuinely
testable before the scraping layer exists, Phase 1 uses **contract-first
sub-slicing** (see `incremental-implementation`'s "Contract-First Slicing"):
the search/refresh routes are built against a small scraper/scoring
*interface* backed by fixture data, then Phase 2 replaces the fixture
implementation with the real one without touching the route contract.

## Dependency graph

```
Phase 1: Backend                Phase 2: Scraping              Phase 3: Frontend
─────────────────                ─────────────────              ──────────────────
B1 DB schema + store  ──┐
B2 Flask app skeleton ──┤
B3 /api/history CRUD  ──┼─▶ B4 scraper/scoring       ──▶ S1 Stage A (FMHY)   ──┐
                         │    interface + fixtures         (real scrape)      │
                         │                              ──▶ S2 Stage B         ├─▶ S4 wire real
B5 /api/search route ───┘    (contract only)                (per-site search) │   impls into
   (uses B4's interface)                                                       │   B4's routes
B6 /api/admin/refresh-sources ─────────────────────────▶ S3 Playwright        │
   (uses B4's interface)                                     fallback ────────┘
                                                          S4 Scoring engine
                                                             (evaluator.py)
                                                                                    ▼
                                                                          F1 Vite+React scaffold
                                                                          F2 SearchBar + call /api/search
                                                                          F3 ResultPlayer (iframe+fallback)
                                                                          F4 HistorySidebar
                                                                          F5 End-to-end polish
```

Build order: **B1 → B2 → B3 → B4 → B5 → B6 → S1 → S2 → S3 → S4 → F1 → F2 → F3 → F4 → F5**

## Checkpoints (human review gates)

- **After B4** (interface + fixtures defined, before any route is built on
  top of it): confirm the `Candidate` / `ScoreResult` shapes are right — this
  is the contract everything downstream depends on.
- **After B6** (end of Phase 1): full backend runs against fixture data,
  all backend tests pass. Good point to confirm before real scraping work
  starts.
- **After S4** (end of Phase 2): `/api/admin/refresh-sources` and
  `/api/search` work against real FMHY + real candidate sites (or the sites
  used for fixtures), scoring returns real component scores. Confirm before
  frontend work starts — this is the riskiest phase (external sites can
  differ from what fixtures assumed).
- **After F5** (end of Phase 3): full spec's Success Criteria checked
  end-to-end.

## Phase 1 — Backend (SQLite schema + Flask API)

### B1. SQLite schema + `db/store.py`
- **Acceptance:** `sources` and `searches` tables created via `schema.sql`;
  `store.py` exposes `add_source`, `list_sources`, `add_search`,
  `list_searches`, `delete_search` — all pure functions over a passed-in
  connection (no hidden global state, so tests use `sqlite3.connect(":memory:")`).
- **Verify:** `pytest backend/tests/test_store.py` — CRUD round-trips for
  both tables.
- **Files:** `backend/db/schema.sql`, `backend/db/store.py`,
  `backend/tests/test_store.py`.

### B2. Flask app skeleton
- **Acceptance:** `python backend/app.py` starts a dev server; `GET
  /api/health` returns `{"status": "ok"}`; app factory pattern so tests can
  create an app with an in-memory DB.
- **Verify:** `pytest backend/tests/test_app.py::test_health`; manual
  `curl http://localhost:5000/api/health`.
- **Files:** `backend/app.py`, `backend/requirements.txt`,
  `backend/tests/test_app.py`.

### B3. `/api/history` GET + DELETE
- **Acceptance:** `GET /api/history` returns stored searches (newest
  first) from `store.py`; `DELETE /api/history/<id>` removes one row. No
  scraping involved — this is a real, complete vertical slice on its own
  since history is pure DB access.
- **Verify:** `pytest backend/tests/test_history_route.py` (empty list,
  populated list, delete removes row, delete of missing id returns 404).
- **Files:** `backend/routes/history.py`, `backend/tests/test_history_route.py`.

### B4. Scraper/scoring interface + fixture implementation
- **Acceptance:** Define the boundary the rest of the backend builds
  against: `scraper.get_candidates(title: str) -> list[Candidate]` and
  `scoring.pick_best(candidates: list[Candidate]) -> ScoreResult`. Ship a
  fixture-backed implementation (hardcoded 2-3 sample candidates with
  plausible scores) so routes B5/B6 have something real to call. This is
  the contract checkpoint — get sign-off on `Candidate`/`ScoreResult`
  shapes before building on them.
- **Verify:** `pytest backend/tests/test_scraper_interface.py` (fixture
  implementation returns expected shape).
- **Files:** `backend/scraper/__init__.py` (interface + fixture impl),
  `backend/scoring/__init__.py` (interface + fixture impl),
  `backend/tests/test_scraper_interface.py`.

### B5. `/api/search` POST route
- **Acceptance:** Accepts `{"query": str}`, calls `scraper.get_candidates`
  → `scoring.pick_best` (fixture-backed for now), writes one `searches` row
  via `store.py`, returns the winning candidate + component scores as JSON.
  Full request/response contract is real and final; only the scrape/score
  internals are fixtures.
- **Verify:** `pytest backend/tests/test_search_route.py` (valid query
  returns 200 + expected JSON shape + DB row written; empty query returns
  400).
- **Files:** `backend/routes/search.py`, `backend/tests/test_search_route.py`.

### B6. `/api/admin/refresh-sources` POST route
- **Acceptance:** Calls a `scraper.refresh_sources()` interface function
  (fixture-backed for now — writes 2-3 sample sources to the `sources`
  table via `store.py`), returns count refreshed.
- **Verify:** `pytest backend/tests/test_admin_route.py`.
- **Files:** `backend/routes/admin.py`, `backend/tests/test_admin_route.py`.

**Phase 1 exit state:** full Flask API works end-to-end against fixture
data. All backend tests pass. No real network scraping yet — that's
Phase 2, and it slots in *underneath* the same route contracts.

## Phase 2 — Scraping logic

### S1. Stage A: `scraper/fmhy_source_list.py` (real FMHY scrape)
- **Acceptance:** Scrapes FMHY.net/video directory HTML (parsed via
  BeautifulSoup) into a list of `(site_name, base_url, tags)`; replaces the
  fixture behind `scraper.refresh_sources()` from B6, writing real rows to
  `sources` via the same `store.py` functions — no changes to the B6 route.
- **Verify:** `pytest backend/tests/test_fmhy_source_list.py` against a
  **saved HTML fixture** of FMHY's page (not a live network call in CI);
  manual one-off run against the live site to confirm the parser matches
  reality.
- **Files:** `backend/scraper/fmhy_source_list.py`,
  `backend/tests/fixtures/fmhy_video_directory.html`,
  `backend/tests/test_fmhy_source_list.py`.

### S2. Stage B: `scraper/site_search.py` (per-site title search)
- **Acceptance:** For a given title and a candidate site (from `sources`),
  queries that site's own search page (BeautifulSoup) and extracts
  candidate watch/embed URLs + any subtitle-track signal found in the
  result markup. Replaces the fixture behind `scraper.get_candidates()`
  from B4 — no changes to the B5 route.
- **Verify:** `pytest backend/tests/test_site_search.py` against saved
  fixture HTML for 2-3 representative site shapes.
- **Files:** `backend/scraper/site_search.py`,
  `backend/tests/fixtures/site_*.html`, `backend/tests/test_site_search.py`.

### S3. Playwright fallback (`scraper/playwright_fallback.py`)
- **Acceptance:** For a site where the BeautifulSoup pass in S2 returns no
  candidates, retry with a headless Playwright fetch of the rendered page,
  then re-run the same extraction logic. Only invoked as a fallback — the
  hot path (S2 succeeding) never touches Playwright.
- **Verify:** `pytest backend/tests/test_playwright_fallback.py` (mocked
  Playwright call, asserts fallback only triggers on empty S2 result).
- **Files:** `backend/scraper/playwright_fallback.py`,
  `backend/tests/test_playwright_fallback.py`.

### S4. Scoring engine (`scoring/evaluator.py` + `site_reliability.json`)
- **Acceptance:** Replaces the fixture behind `scoring.pick_best()` from B4
  with the real weighted formula (site-reliability weight + subtitle signal
  + live latency probe to the winning-shortlist candidates), starting from
  an empty/neutral `site_reliability.json` (per SPEC.md's open question
  default). No changes to the B5 route.
- **Verify:** `pytest backend/tests/test_evaluator.py` — pure-function unit
  tests per signal (reliability lookup, subtitle bonus, latency-to-score)
  plus one combined-weighting test; latency probe tested against a mocked
  HTTP client, not real network calls.
- **Files:** `backend/scoring/evaluator.py`,
  `backend/scoring/site_reliability.json`, `backend/tests/test_evaluator.py`.

**Phase 2 exit state:** `/api/search` and `/api/admin/refresh-sources` work
against real external sites (or fail gracefully per-site without crashing
the request). All scraper/scoring tests pass against fixtures. This is the
riskiest phase — checkpoint with the user before Phase 3.

## Phase 3 — Frontend (Vite + React)

### F1. Vite + React scaffold
- **Acceptance:** `npm create vite@latest frontend -- --template react`
  equivalent scaffold; `npm run dev` serves a blank app; `npm run build`
  succeeds; a thin `src/api/client.js` wraps `fetch` against the backend
  base URL (env-configurable).
- **Verify:** `npm run build` succeeds; `npm run lint` passes.
- **Files:** `frontend/` (scaffold), `frontend/src/api/client.js`.

### F2. `SearchBar` + wire to `/api/search`
- **Acceptance:** Typing a title and submitting calls `POST /api/search`
  against the real backend (Phase 1+2 already done) and renders the raw
  JSON result (no styling/player yet — prove the wiring first).
- **Verify:** Vitest component test for `SearchBar` (submit calls the
  provided handler with trimmed query); manual check against the running
  backend.
- **Files:** `frontend/src/components/SearchBar.jsx`,
  `frontend/src/components/SearchBar.test.jsx`, `frontend/src/App.jsx`.

### F3. `ResultPlayer` (iframe with link fallback)
- **Acceptance:** Renders an iframe for the chosen source; detects a
  framing-blocked response (via a `frameBlocked` flag the backend can set,
  or a client-side `onerror`/timeout heuristic — resolve exact detection
  method here since SPEC.md doesn't lock it) and falls back to an "Open
  source" link/button. Also displays the component scores from the API
  response (reliability/subtitle/latency) per SPEC.md's "explainable
  scoring" success criterion.
- **Verify:** Vitest tests for both the embed-success and fallback-shown
  paths.
- **Files:** `frontend/src/components/ResultPlayer.jsx`,
  `frontend/src/components/ResultPlayer.test.jsx`.

### F4. `HistorySidebar`
- **Acceptance:** Lists past searches from `GET /api/history` newest
  first; clicking an entry re-displays that stored result (chosen source +
  score) without calling `/api/search` again; a delete control calls
  `DELETE /api/history/<id>`.
- **Verify:** Vitest tests (renders list, click re-displays stored result,
  delete removes item from the list).
- **Files:** `frontend/src/components/HistorySidebar.jsx`,
  `frontend/src/components/HistorySidebar.test.jsx`.

### F5. End-to-end polish
- **Acceptance:** Loading and error states wired for search/history calls;
  layout matches SPEC.md's "clean search interface + sidebar" requirement;
  manual run through every item in SPEC.md's Success Criteria.
- **Verify:** Manual full run (`npm run dev` + `python backend/app.py`)
  covering: search → result shown or fallback link → appears in sidebar →
  revisit from sidebar → refresh-sources trigger works.
- **Files:** `frontend/src/App.jsx`, `frontend/src/App.css` (or module
  CSS), no new backend files expected.

## Risks & mitigations

- **FMHY/site HTML structure drifts from fixtures** (Phase 2's biggest
  risk) — mitigated by testing against saved fixtures (deterministic) plus
  one manual live-site check per scraper module before marking it done.
- **A candidate site blocks scraping (anti-bot, CAPTCHA)** — per SPEC.md
  boundaries, skip that site rather than defeating the protection; S2/S3
  must treat a blocked site as "zero candidates from this site," not a
  hard failure of the whole search.
- **Iframe framing-block detection** (F3) has no single reliable
  client-side signal — flagged as an open question to resolve during F3,
  not before; worst case, ship a manual "having trouble? open externally"
  link alongside the iframe as an always-available safety net.

## What can run in parallel vs. must be sequential

Per explicit direction, phases are sequential (backend → scraping →
frontend) rather than parallelized, since B4's fixture contract is what
lets Phase 1 be fully built and tested before Phase 2 exists. Within
Phase 2, S1 and S2 are independent of each other (both only depend on B4's
contract) and could be done in either order; S3 depends on S2 (it's a
fallback for S2's extraction logic); S4 is independent of S1/S2 and could
be built in parallel with them, but is sequenced last here for simplicity.
Within Phase 3, F2 depends on F1; F3 and F4 both depend on F2's App shell
existing but are otherwise independent of each other.
