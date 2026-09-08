# Flow

Documents how execution actually travels between files, functions, and modules
(request/event lifecycles, call chains, triggers → handlers → side effects).

Nothing is implemented yet. This currently documents the **planned**
execution path from `tasks/plan.md`, in build order; it will be corrected to
match reality as each task lands.

## Build-time flow (the order things get built, not a runtime path)

```
Phase 1 (Backend)              Phase 2 (Scraping)             Phase 3 (Frontend)
──────────────────              ───────────────────             ──────────────────
schema.sql, store.py
      │
      ▼
app.py (Flask factory)
      │
      ▼
routes/history.py  ─────────────────────────────────────────────────────────▶ real GET/DELETE,
      │                                                                        no scraping dependency
      ▼
scraper/__init__.py +
scoring/__init__.py
(interface + FIXTURE data)  ◄── checkpoint: confirm shapes
      │
      ├─▶ routes/search.py         ──▶ [replaced under the hood by] ──▶ fmhy_source_list.py (S1)
      │      (fixture-backed)                                          site_search.py (S2)
      │                                                                 playwright_fallback.py (S3)
      └─▶ routes/admin.py                                              evaluator.py + site_reliability.json (S4)
             (fixture-backed)
                                                                                      │
                                                                                      ▼
                                                                          frontend/src (F1-F5)
                                                                          SearchBar → ResultPlayer
                                                                          → HistorySidebar
```

Key point: `routes/search.py` and `routes/admin.py` are written once
(Phase 1) against the `scraper`/`scoring` interface, then Phase 2 swaps the
fixture implementation for the real one **without changing the route code**.
This is the contract-first slicing from `tasks/plan.md` (task B4).

## ACTUAL runtime flow — `POST /api/search` (implemented, task S1)

```
POST /api/search { query: title }
  → backend/routes/search.py: search()
      ├─ reject with 400 if query is missing/blank
      ├─ scraper.get_candidates(query)
      │    ├─ scraper/fmhy_source_list.py: get_streaming_sites()
      │    │    ├─ cache hit (< 1h old)? return cached list  [~2ms]
      │    │    └─ else fetch_video_markdown()               [~80ms]
      │    │          → GET raw.githubusercontent.com/fmhy/edit/main/docs/video.md
      │    │          → parse_streaming_sites()  — walks "# ► Streaming Sites",
      │    │             skips Note bullets + reddit/github cross-refs,
      │    │             records name/url/rank/starred/section
      │    │          → rank_sites()  — starred first, then FMHY list position
      │    │    ← list[StreamingSite]
      │    ├─ scraper/title_lookup.py: resolve_title(query)
      │    │    → GET v2.sg.media-imdb.com/suggestion/<letter>/<query>.json
      │    │    → first entry with tt-id and a watchable `qid`
      │    │    ← ResolvedTitle(imdb_id, title, year, kind) | None
      │    │      (any RequestException → None; search continues on the raw
      │    │       query — IMDb is an enhancement, FMHY is required)
      │    ├─ scraper/tmdb_lookup.py: find_tmdb_id(imdb_id)
      │    │    → TMDB /find; needs TMDB_API_KEY, None without one
      │    └─ scraper/site_search.py: build_site_links(sites, title, tmdb)
      │         → per site, best first:
      │             _TITLE_ADAPTERS + a tmdb id → /watch/movie/{id}  (title)
      │             verified route in _SEARCH_ADAPTERS → /search?q=… (search)
      │             otherwise → the site's home page                (home)
      │         ← list[SiteLink]  (subtitle_status always "unknown")
      │    ← list[Candidate]
      ├─ scraper.annotate_availability(candidates)   [only when
      │    PROBE_AVAILABILITY is on — off by default; ~8s]
      │    → scraper/availability.py: probe_availability()
      │         → pick deep links whose domain has a verified detector
      │           (today: flixer.gd only), capped at DEFAULT_PROBE_LIMIT
      │         → _render_page_text(): headless Chromium, wait past
      │           DOM-ready for the client-rendered results
      │         → detect_availability(): read the *result count*, not the
      │           title text — the page echoes the query back even on a
      │           zero-result page
      │         ← {url: AvailabilityResult(status, result_count)}
      │      (missing Playwright, a blocked site, a timeout or a layout
      │       change → "unknown"; never raises into the request)
      │    → writes availability/result_count onto each Candidate
      ├─ scraper.annotate_playback(candidates)       [only when
      │    PROBE_PLAYBACK is on — off by default]
      │    → scraper/playback.py: probe_playback()
      │         → targets = confirmed-available + deep link + an *enabled*
      │           adapter, capped at DEFAULT_PLAYBACK_LIMIT (today: none,
      │           so no browser is launched at all)
      │         → _measure_playback(): open the player via the site adapter,
      │           find the <video> across frames, mute, play, watch for a
      │           fixed OBSERVATION_MS, read back the accumulated counters
      │         → parse_metrics(): validate the payload field by field;
      │           anything malformed ⇒ "unknown"
      │         ← {url: PlaybackMetrics(started, startup_ms, rebuffers…)}
      │      (no adapter, no player, timeout, crash, or missing Playwright
      │       all ⇒ unmeasured; never raises into the request)
      ├─ telemetry.annotate_reported_playback(db, candidates)  [always on -
      │    a cheap local read, and the only playback evidence we can collect]
      │    → db/store.py: playback_stats() over recent playback_reports
      │    → prefers reports for THIS title; falls back to site-wide and
      │      labels it scope="site"; below MIN_SAMPLE_SIZE claims nothing
      │    ← PlaybackMetrics(provenance="reported", sample_size, scope)
      ├─ scoring.pick_best(candidates)                    → top_source
      │    → availability: +0.5 available / -2.0 unavailable / 0 unknown
      │    → latency_score = measured playback: +0.4 base for playing, up to
      │      +0.3 for a fast start, -0.2 per rebuffer, -0.6 × the share of
      │      the window spent buffering; -1.5 if it never started; 0.0 when
      │      unmeasured. Together these are the only terms that depend on
      │      what was searched.
      │    → _score() per candidate: reliability = star tier + 0.4/rank
      │      + 0.1 if deep-linkable + availability, subtitle = 0 unless
      │      status == "available" (nothing sets that yet)
      │    ← ScoreResult (winner + component scores)
      ├─ scoring.pick_best([c for c in candidates if c.is_deep_link])
      │    → best_deep_link, or None when no candidate site is linkable
      ├─ on requests.RequestException → 502 "could not reach the FMHY directory"
      ├─ on ValueError (no sites parsed) → 502 "no streaming sources found"
      │    (neither path persists the query)
      ├─ db/store.py: add_search(query, matched_title, source=winner.url, score)
      └─ db/store.py: list_searches()
  ← 201 JSON { search, matched_title, year, imdb_id,
                top_source:     { url, site_name, is_deep_link, subtitle_status,
                                  availability, result_count,
                                  playback: {started, startup_ms,
                                             rebuffer_count, rebuffer_ms,
                                             observed_ms} | null,
                                  rank, starred, total_score,
                                  scores: {reliability, subtitle, latency} },
                best_deep_link: same shape, or null,
                history: [...] }
```

**Why two sources are returned:** FMHY's top-ranked sites mostly have no
verified search route, so `top_source` is usually a home-page link, while
`best_deep_link` opens the site directly on the searched title (typically a
lower-ranked site). Live example: "matrix" → top_source Cinejoy (rank 1,
home page), best_deep_link Rive (rank 4, `/search?query=The+Matrix`).

**Still not a direct video-page URL.** These are links into each site's
*search results* for the title, not to the video page itself. Task S3 (now
built) uses a rendering browser to confirm whether a site *has* the title,
but does not yet extract the video-page URL or real subtitle status from
the rendered page — that remains open.

## ACTUAL runtime flow — `GET /api/suggestions` (implemented, autocomplete)

```
GET /api/suggestions?q=<partial title>
  → backend/routes/suggestions.py: suggestions()
      ├─ len(q.strip()) < 2 → 200 { suggestions: [] }   (never touches IMDb)
      ├─ scraper.get_suggestions(query, limit=5)
      │    → scraper/title_lookup.py: resolve_suggestions(query, limit)
      │         → GET v2.sg.media-imdb.com/suggestion/<letter>/<query>.json
      │         → up to `limit` entries with a tt-id and a watchable `qid`,
      │           each carrying the poster IMDb already returns (`i.imageUrl`)
      │         ← list[Suggestion(imdb_id, title, year, kind, image_url)]
      │      (RequestException or a malformed/non-JSON body → [] — same
      │       "degrade, don't fail" contract as _resolve_quietly)
      └─ serialize each Suggestion to a plain dict
  ← 200 { suggestions: [ { imdb_id, title, year, kind, image_url }, ... ] }
```

This is a read of the *same* IMDb endpoint `resolve_title` already calls for
`/api/search` — `resolve_title` is now defined in terms of
`resolve_suggestions(query, limit=1)`. No second image system: the poster
shown in the dropdown is whatever IMDb's suggestion payload already
included for that entry, which is `None` for a meaningful fraction of
entries (industry/franchise-style records without a poster) — the frontend
renders a placeholder for those and for any URL that fails to load.

## Planned runtime flow — `POST /api/admin/refresh-sources` (once S1 is complete)

```
(manual trigger, e.g. curl or an admin action)
  → backend/routes/admin.py: refresh_sources()
    → scraper/fmhy_source_list.py: scrape_fmhy_video_directory()
        → GET https://fmhy.net/video (or equivalent) → BeautifulSoup parse
        → list of (site_name, base_url, tags)
    → db/store.py: add_source(...) per parsed entry (upsert by base_url)
    ← JSON { refreshed_count }
```

## ACTUAL frontend flow (implemented, Phase 3)

```
App mounts
  → api/client.js: fetchHistory()  → GET /api/history  (via Vite proxy → :5000)
  → HistorySidebar renders past searches (newest first)

SearchBar: user types (autocomplete)
  → local `query` state updates on every keystroke (no network call here)
  → 300ms after the *last* keystroke (debounce timer reset on every change):
      → api/client.js: fetchSuggestions(trimmed) → GET /api/suggestions?q=...
      → on success: render up to 5 options (poster left, title/year/kind
        right) in a `role="listbox"` under the input
      → on failure/empty/too-short: dropdown stays closed, input still works
        as a plain text box — autocomplete is additive, never load-bearing
  → a request that resolves after a newer one is dropped (via a
    monotonically increasing request id), so a slow stale response can't
    flash outdated suggestions over the current list
  → ArrowDown/ArrowUp move the highlighted option; Enter on a highlighted
    option, or a click on any option, selects it: fills the input with its
    title, closes the dropdown, and runs the search below — Escape or a
    click outside the search bar just closes the dropdown
  → selecting a suggestion (or restoring a history entry, below) sets a
    one-shot "suppress" flag so that the resulting `query` change doesn't
    itself reopen the dropdown — see docs/Decisions.md, this was a real
    bug caught in live browser testing

SearchBar submit (trimmed, non-empty)
  → App.runSearch(query): isSearching=true, error=null
    → api/client.js: search(query) → POST /api/search
    → on success: setResult(response); setHistory(response.history)
        (the search response already carries the updated history —
         no second /api/history round-trip)
    → on failure: setResult(null); setError(message)
  → ResultPanel renders either:
      • error (role="alert"), or
      • matched title/year + two SourceCards:
          "Top ranked source"  → FMHY rank 1 (usually a home-page link)
          "Opens on this title" → best_deep_link, or a note when null
        each with FMHY rank, score, and "subtitles: unknown"

HistorySidebar entry clicked
  → App.runSearch(entry.query)  — re-runs the search rather than
    re-displaying the stored row (see docs/Decisions.md; deviates from
    SPEC.md and appends a duplicate history row)
```

## Planned runtime flow — history sidebar (Phase 1, works before scraping exists)

```
Frontend HistorySidebar mount
  → api/client.js: GET /api/history
    → backend/routes/history.py: list_history()
      → db/store.py: list_searches()  [newest first]
      ← JSON [ { id, query, matched_title, source, scores, timestamp }, ... ]
  ← HistorySidebar renders list

User clicks a past entry
  → no network call — the stored source + scores from that row are
    rendered directly into ResultPlayer (per SPEC.md: revisiting history
    does not re-scrape)

User clicks delete on an entry
  → api/client.js: DELETE /api/history/<id>
    → backend/routes/history.py: delete_history(id)
      → db/store.py: delete_search(id)
      ← 204
  ← HistorySidebar removes the item from its list
```

See `docs/Architecture.md` for the module map this flow moves through,
`tasks/plan.md` for the task-by-task build order and acceptance criteria,
and `SPEC.md` for the full specification.
