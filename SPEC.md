# Spec: Movie/TV Show Search Aggregator

## Objective

A web app where a user searches for a movie or TV show title and gets back a
single, pre-vetted streaming source chosen for the best available watching
experience (minimal buffering, correct subtitles), instead of having to
manually hunt through FMHY.net's video directory and try links one by one.

**User:** a single local/personal user (no auth, no multi-tenant concerns for v1).

**Success looks like:** user types a title, within a few seconds sees one
recommended source (embedded player or a link to it) plus the reasoning
signals that picked it, and can revisit past searches from a sidebar without
re-scraping.

**Out of scope for v1:** user accounts, multi-user history, mobile app,
downloading/caching video files, DRM circumvention of any kind, ad-blocking
beyond basic heuristics.

**Legal/ethical note (open, not a code concern but worth stating):** FMHY.net
is a curated directory of third-party sites; the sites it points to host
content whose licensing this app has no way to verify. This spec treats the
app as a personal aggregation/convenience tool over links that are already
public, and does not add scraping capability against sites that block
scraping via authentication — it does not attempt to bypass paywalls, DRM,
CAPTCHAs, or anti-bot protections. If a candidate site actively blocks
scraping, it is skipped, not defeated.

## Architecture Decisions (confirmed with user)

1. **Two-stage scrape.** FMHY's video directory page is a curated list of
   *site names/domains*, not per-title links. So:
   - Stage A (periodic, low-frequency): scrape FMHY.net/video once
     per refresh interval to build a cached, ranked list of candidate source
     sites (name, base URL, category tags FMHY assigns).
   - Stage B (per search): for a given title, query each cached candidate
     site's own search functionality, scrape its result list, and collect
     candidate watch-page/embed URLs for that title.
2. **Heuristic scoring**, no actual video playback during evaluation:
   - Static site-reliability weight from a maintained allowlist (sites known
     to be low-ad, low-redirect score higher; unknown sites score neutral;
     sites on a blocklist are excluded).
   - Subtitle signal: presence of subtitle-track markers in the scraped
     watch page (e.g. `<track>` tags, a "CC"/language selector, or a
     sub-download link) contributes a positive weight; absence is neutral,
     not disqualifying.
   - Latency signal: HTTP HEAD/GET-with-range probe to the resolved
     video/embed URL, timing time-to-first-byte; faster responses score
     higher, timeouts/errors are excluded.
   - Final score = weighted sum; highest-scoring candidate wins ties broken
     by site-reliability weight.
3. **Player behavior**: iframe-embed the winning source by default; if the
   response indicates framing is blocked (`X-Frame-Options`, restrictive
   `Content-Security-Policy: frame-ancestors`), fall back to a prominent
   "Open source in new tab" link/button instead of a broken iframe.
4. **History scope**: persist one row per search — query text, normalized
   title, timestamp, and the single chosen source (site name + URL + score
   at the time). Does not persist the full candidate list/every score;
   re-running a past search re-scrapes fresh.

## Tech Stack

- **Frontend:** React 18 + Vite 5, plain CSS or CSS modules (no heavy UI kit
  unless later requested), `fetch` for API calls.
- **Backend:** Flask 3, `requests` + `BeautifulSoup4` for static HTML scraping,
  `Playwright` (Python, Chromium) reserved for candidate sites that require
  JS rendering — used only when a BeautifulSoup pass yields no result for
  that site, to keep the common path fast.
- **Database:** SQLite via Flask's built-in `sqlite3` (or `SQLAlchemy` if the
  schema grows) — single file, no external DB server.
- **Scheduling:** the FMHY directory refresh (Stage A) runs on a simple
  interval via APScheduler inside the Flask process (or a manual
  `/api/admin/refresh-sources` endpoint) — no separate worker/queue for v1.

## Commands

```
# Frontend
cd frontend
npm install
npm run dev              # Vite dev server, default :5173
npm run build             # production build
npm run lint               # eslint

# Backend
cd backend
python -m venv .venv
.venv\Scripts\activate     # Windows
pip install -r requirements.txt
python app.py               # Flask dev server, default :5000
pytest                        # backend tests
```

## Project Structure

```
frontend/
  src/
    components/       → SearchBar, ResultPlayer, HistorySidebar, SourceBadge
    api/               → thin fetch wrapper for backend endpoints
    App.jsx
  index.html
  vite.config.js

backend/
  app.py                       → Flask app factory + route registration
  routes/
    search.py                  → POST /api/search
    history.py                 → GET /api/history, DELETE /api/history/<id>
    admin.py                   → POST /api/admin/refresh-sources
  scraper/
    fmhy_source_list.py        → Stage A: scrape FMHY video directory
    site_search.py             → Stage B: per-site title search/scrape
    playwright_fallback.py     → JS-rendered scrape fallback
  scoring/
    evaluator.py                → latency probe + subtitle signal + weighting
    site_reliability.json       → maintained allowlist/blocklist + weights
  db/
    schema.sql                  → sources, searches tables
    store.py                    → SQLite access layer
  requirements.txt
  app.db                         → SQLite file (gitignored)

docs/                            → Architecture.md, Decisions.md, Flow.md,
                                    Handover.md, Constraints.md (existing)
tasks/                            → plan.md, todo.md (created in Plan phase)
```

## Code Style

**Backend (Flask, PEP8, type hints on public functions):**
```python
def score_candidate(candidate: Candidate, weights: ScoreWeights) -> float:
    """Return a 0-1 weighted score for a scraped candidate source."""
    reliability = site_reliability_lookup(candidate.domain)
    if reliability is None:
        reliability = weights.neutral_reliability
    subtitle_bonus = weights.subtitle_bonus if candidate.has_subtitles else 0.0
    latency_score = latency_to_score(candidate.latency_ms, weights)
    return (
        reliability * weights.reliability_weight
        + subtitle_bonus
        + latency_score * weights.latency_weight
    )
```

**Frontend (React function components, hooks, no class components):**
```jsx
function SearchBar({ onSearch }) {
  const [query, setQuery] = useState("");

  function handleSubmit(e) {
    e.preventDefault();
    if (query.trim()) onSearch(query.trim());
  }

  return (
    <form onSubmit={handleSubmit} className="search-bar">
      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search a movie or show..."
      />
      <button type="submit">Search</button>
    </form>
  );
}
```

Naming: `camelCase` for JS/JSX, `snake_case` for Python. Components are
one-per-file, named after their export. API route files are named after the
resource they serve.

## Testing Strategy

- **Backend:** `pytest`. Unit tests for `scoring/evaluator.py` (pure
  functions, easy to test with fixture candidates) and `db/store.py`
  (in-memory SQLite). Scraper modules (`fmhy_source_list.py`,
  `site_search.py`) tested against saved HTML fixtures, not live network
  calls, so tests stay deterministic and don't hit real sites in CI.
- **Frontend:** Vitest + React Testing Library for components
  (`SearchBar`, `HistorySidebar`, `ResultPlayer` fallback behavior).
- **Coverage expectation:** scoring and DB layers should be well covered
  (they're pure logic); scraper HTML parsing covered via fixtures for the
  known site shapes; no strict global coverage percentage gate for v1.
- **No end-to-end tests against live FMHY/third-party sites in CI** — those
  sites change layout without notice and are out of this project's control;
  a manual `/api/admin/refresh-sources` run is the way to validate scraping
  still works against the real site.

## Boundaries

- **Always:** validate/sanitize the search query before using it to build
  any scrape URL; run backend tests before committing scraper or scoring
  changes; keep `site_reliability.json` (the allow/blocklist) as a reviewable
  diff, not silently auto-updated by the scraper.
- **Ask first:** adding a new third-party site to the candidate list beyond
  what FMHY lists; changing the SQLite schema; adding Playwright as a
  first-pass scraper (it should stay a fallback, not the default, for
  latency reasons) — ask first if a task considers promoting it to default.
- **Never:** attempt to bypass CAPTCHAs, paywalls, login walls, or anti-bot
  protections on any candidate site; store or log credentials/cookies for
  third-party sites; commit `app.db` or any scraped-content fixtures that
  contain third-party copyrighted material; embed a source via iframe
  without the framing-blocked fallback (never ship a silently-broken iframe).

## Success Criteria

- Typing a title in the search bar and submitting returns one recommended
  source within a reasonable time budget (target: under ~8s for a title
  whose candidate sites are already cached from Stage A).
- The returned source is embedded via iframe, or — when framing is blocked —
  a working "Open source" link is shown instead; no dead/blank iframe is
  ever the only option shown to the user.
- The sidebar lists past searches (query + chosen source + timestamp) newest
  first, and clicking a past entry re-displays that stored result without
  re-scraping.
- Stage A (FMHY directory scrape) can be triggered manually via
  `/api/admin/refresh-sources` and populates/updates the cached source list
  without manual DB edits.
- Scoring is explainable: the API response for a search includes the winning
  candidate's component scores (reliability, subtitle signal, latency), not
  just a bare winner, so the frontend can show *why* a source was picked.
- Backend and frontend test suites pass (`pytest`, `npm run lint` +
  Vitest suite).

## Open Questions

1. **Refresh cadence for Stage A** — how often should FMHY's directory be
   re-scraped (hourly? daily? only on manual trigger)? Defaulting to
   "manual trigger only for v1" unless you want a scheduled interval.
2. **Site allowlist seeding** — should `site_reliability.json` start empty
   (everything neutral until observed) or should I seed it with an initial
   guess at commonly-known reliable/unreliable domains? Defaulting to
   "start empty, neutral scoring" to avoid asserting reputational claims
   about specific sites without your input.
3. **Title matching** — FMHY-listed sites will return fuzzy/multiple
   results for a query (e.g. remakes, same title different year). Defaulting
   to: show the top-scored candidate for the best fuzzy-matched title, and
   surface the matched title/year back to the user so they can tell if it
   picked the wrong one; no year/type (movie vs TV) filter in the search bar
   for v1.
