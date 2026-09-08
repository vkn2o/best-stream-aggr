# Decisions

A log of every meaningful decision made while changing code, and the rationale
behind it (e.g. why a specific library, pattern, or tradeoff was chosen).

Newest entries at the top. Format:

```
## YYYY-MM-DD — <short decision title>
- Decision:
- Rationale:
- Alternatives considered:
```

## 2026-09-08 - Playback is measured from the play request, and unrequested sessions are not reported
- Decision: the userscript's tracker gained `attempt()` (wired to the video's
  `play` event in `attach`). Start-up and the observation window are now
  measured from the first play request instead of from page load, the 30s
  report window is scheduled from that request, and a new exported
  `shouldReport(snapshot)` drops any session where playback was never
  requested. `scraper/playback.py`'s probe already set `_t0` immediately
  before `video.play()`, so the two definitions still mean the same thing;
  a comment there now says so explicitly.
- Rationale: two faults with one cause - the tracker's clock started when the
  player mounted rather than when the viewer asked for playback. (1) A viewer
  who opened a player and never pressed play was reported as
  `started: false`, which `_playback_score` treats as `_PLAYBACK_FAILED`
  (-1.5): the site penalised for the viewer's hesitation. Five such rows
  accumulated in `app.db` during live testing. (2) `startup_ms` included
  however long the viewer spent before pressing play - the 8.3s "start-up"
  recorded in an earlier session was mostly deliberation, not the source.
  Measuring from intent fixes both, and makes sessions comparable to each
  other rather than to how quickly someone clicks.
- Alternatives considered: sending the session with an `attempted` flag and
  filtering server-side (stores rows that carry no information, and invites
  a future caller to average over them); treating `started: false` as
  neutral rather than a failure in scoring (would also discard genuine
  failures, which are the most useful signal there is); a grace period
  before reporting a non-start (arbitrary, and unnecessary once the window
  starts at the request).

## 2026-09-08 - A playback report names its title with a TMDB reference
- Decision: the userscript's `imdbIdFromPage()` became `titleRefFromPage()`,
  which falls back to parsing `/watch/(movie|tv)/(\d+)` out of the player URL
  and sends `tmdb_id` + `media_type`; `POST /api/playback-report` validates
  that pair and resolves it through a new
  `tmdb_lookup.find_imdb_id(tmdb_id, media_type)`
  (TMDB `/{media_type}/{id}/external_ids`). Season and episode are dropped.
- Rationale: found while testing the userscript live. Flixer's player page
  contains no `tt` id anywhere - verified against the rendered DOM, not
  assumed - so every reported session stored `imdb_id = NULL`, and the
  `scope="title"` branch of `telemetry.metrics_for` was unreachable in
  practice. The page does name the title, just in TMDB's namespace, which
  the app already speaks for deep links. Dropping season/episode is
  deliberate: playback quality is a property of the source, not of which
  episode was on.
- Alternatives considered: matching on the page's title text (fuzzy, and a
  wrong match silently attributes one title's buffering to another - worse
  than no title at all); tagging app-generated links with `#tt...` (works
  only for links this app built, which need a TMDB key anyway, so it solves
  nothing the key doesn't); storing the raw `tmdb_id` for later backfill
  (a schema change earning nothing until something backfills).
- Consequence to be honest about: **title-scoped evidence needs
  `TMDB_API_KEY`.** Without one, `find_imdb_id` returns None and reports
  stay site-wide - stored, counted, and labelled as site-wide, never
  presented as being about the searched title (Constraints #9).

## 2026-09-08 - Reported rebuffering is a fractional average, not a whole count
- Decision: `db/store.playback_stats` now returns `rebuffer_count` rounded to
  2 decimals instead of a whole number, `PlaybackMetrics.rebuffer_count` is
  typed `float`, and `ResultPanel.playbackEvidence` treats a stream as having
  stalled when *either* `rebuffer_count` or `rebuffer_ms` is non-zero.
- Rationale: found against live reported data, not in review. One real 627ms
  stall across five real sessions averaged to 0.2 rebuffers; `round()` turned
  that into 0, the UI gated its wording on the count alone, and the card read
  "PLAYED IN 6.4S - NO REBUFFERING" about a session set that demonstrably
  stalled - while `rebuffer_ms` sat at 125 in the same payload. That is
  exactly the overclaim `docs/Constraints.md` #9 exists to prevent, so the
  measurement is preserved rather than the rounding. A fractional count also
  scores more accurately: `_playback_score` multiplies by it, so rounding to
  zero had been discarding the penalty entirely.
- Alternatives considered: rounding up any non-zero average to 1 (invents a
  stall that most sessions did not have); fixing only the frontend gate (the
  number reaching the UI would still be a wrong 0); reporting a rebuffer
  *rate* per hour (clearer statistically, but a different metric from the
  probed path, and the two must stay comparable - see clients/README.md).

## 2026-09-08 — Player deep-links, and measuring playback where it is actually measurable
- Asked to find another way past S4's dead end (no measurable playback),
  including external tools and what comparable projects do. The answer split
  cleanly in two.
- **What is gated, and why we stop there.** The sites do not merely lack
  links - they gate their streams:
  - Flixer derives its server list from a WASM key step that fails for
    automated sessions (`[WASM] Error getting image key: E20` ->
    `[Sources] No servers derived from sources`), API on
    `plsdontscrapemelove.flixer.gd`.
  - Boomflix runs its own extractor against an upstream provider
    ("Extracting Stream... via Proxy", `[Netmirror]` -> `net52.cc/playlist.php`).
  Reaching a stream means defeating those, which docs/Constraints.md #5 and
  SPEC.md rule out and which stealth / anti-detection tooling exists to do.
  Not built here; no amount of tooling changes that. Recorded so it is not
  re-litigated.
- **What is not gated: the routes.** Reading a site's own published route
  manifest is ordinary engineering - it is how `_SEARCH_ADAPTERS` was built.
  Flixer's bundle publishes `/watch/movie/:tmdbId` and
  `/watch/tv/:tmdbId/:seasonId/:episodeId`, both verified live
  (`/watch/movie/603` -> a player with a `<video>`; `/watch/tv/1396/1/1` ->
  "Breaking Bad S1 Episode 1"). Results now link straight to the title's
  player, closing the "still not a direct video-page URL" gap open since S3.
  A real browser passes the WASM step normally; only ours does not.
  - Boomflix publishes `/player/:id` but never reaches a video element, so
    it is **not** registered - the S2 rule holds: an unverified route is
    worse than an honest search link.
  - Needs a TMDB id (`tmdb_lookup.py`, TMDB's documented `/find`), because
    the routes key on TMDB rather than IMDb. Optional by design: with no
    `TMDB_API_KEY` - the default - lookups return None and links fall back
    to search URLs. Verified live in all three states (movie, tv, no key).
  - Side effect: IMDb's `kind`, recorded in the S3 entry as
    resolved-then-discarded, is finally load-bearing - it picks movie vs tv.
- **Measuring playback: client-side, not scraped.** Real platforms measure
  quality-of-experience in the viewer's own session rather than by scraping
  (OpenQoE is this pattern). The gate only blocks *our* automated session,
  so measuring in the user's browser sidesteps it entirely and yields better
  data - their real network, their real viewing.
  `clients/streamfinder-qoe.user.js` records the same metrics
  `scraper/playback.py` defines and posts them to `POST /api/playback-report`;
  `telemetry.py` aggregates them into the `PlaybackMetrics` that
  `scoring._playback_score()` already consumed, so the scorer was reused
  **unchanged**.
- Two honesty rules, enforced in code rather than left to callers:
  - **Below `MIN_SAMPLE_SIZE` (3) nothing is claimed.** One unlucky evening
    on bad wifi is not evidence about a source.
  - **Site-wide data is never presented as title-specific.** With too few
    reports for this title we fall back to the site's record, but `scope`
    says so and the UI prints "(site-wide, N sessions)".
  `provenance` likewise separates a probed session from a reported one.
- The userscript is the single source of truth for its own logic: it is a
  classic script (Tampermonkey cannot load ES modules), so instead of
  keeping a copy the Vitest suite reads and evaluates the real file. A copy
  would drift, and these numbers must keep matching playback.py.
- Verified end to end: three reported sessions raised Flixer's score from
  1.68 to 2.38 with `provenance=reported, sample_size=3, scope=title`, and a
  malformed report was rejected with 400 and not stored.

## 2026-09-08 — Task S4: measured playback quality, and what it honestly cannot measure yet
- Goal: stop answering "which site does FMHY rank highest" and start
  answering "for this title, which source actually plays smoothly". S3 told
  us whether a site *has* a title; a site can have it and still stall.
- Decision: new `scraper/playback.py` — a site-agnostic measurement harness
  plus per-domain adapters (`_PLAYBACK_ADAPTERS`), mirroring
  `availability.py` so the two read the same way. Metrics: whether playback
  started, time to start, rebuffer count, total buffering, over a **fixed
  10s window applied identically to every site** — sites are only comparable
  if they were watched the same way.
- Scoring lives in the slot reserved for it: `latency_score` was already the
  documented placeholder for "task S4 replaces this with a real probe", so
  filling it kept `ScoreResult` and the API's `scores` keys unchanged.
  Weights: started +0.4 base, up to +0.3 for a fast start (full credit under
  2s, none by 8s), −0.2 per rebuffer event, −0.6 × the fraction of the window
  spent buffering, clamped to [−1.5, 1.0]; a stream that never started is a
  flat −1.5. Unmeasured is 0.0.
- Why "never started" (−1.5) ranks *below* an untested source (0.0): we have
  positive evidence it does not work, versus an open question. Verified by
  test: an FMHY rank-1 starred site whose playback failed loses to an
  untested rank-9 one, and a lower-ranked site with smooth playback beats
  FMHY's favourite. That was the point of the exercise.
- **What this does NOT do, stated plainly.** No streaming-site player is
  reachable today, so playback is "unknown" in practice:
  - Flixer is the only site with a verified availability detector, so the
    only playback candidate. Its search results are click-driven cards with
    **no title links at all** (no `/movie/`, `/watch`, `/title/` hrefs in the
    DOM). Clicking a card reveals inline detail but never navigates — across
    repeated attempts the URL stayed on the search page and no `<video>` or
    iframe ever appeared.
  - `FlixerPlaybackAdapter` therefore reports failure, and carries
    `enabled = False` so `probe_playback` skips it entirely instead of
    launching a browser and giving up on every single search. Measured: a
    search with playback enabled costs the same ~13s as availability alone.
  - Consequence: the app currently reports `playback: null` and scores it
    neutrally. It does not claim smooth playback for anything. Flipping
    `enabled` to True alongside a real `open_player` is the whole change
    needed when a route is found.
- **The harness itself is verified**, separately from any site: a
  `live_browser` test attaches the real instrumentation to a real `<video>`
  in real Chromium, dispatches genuine media events, and asserts the numbers
  (start time ~300ms, rebuffer count and buffering total) come back correct.
  Without it the injected script would have been entirely unexercised.
- Dead end worth recording so nobody repeats it: verification against public
  sample MP4s failed with `MEDIA_ERR_SRC_NOT_SUPPORTED`, which looks exactly
  like a missing-codec problem in Playwright's Chromium. It was not — the
  URLs return **403** in this environment. The videos never loaded. Check
  reachability before concluding anything about codecs.
- Performance, per the "don't open every streaming site" requirement: only
  sources that are *confirmed available*, deep-linked, and have an **enabled**
  adapter are opened, capped at `DEFAULT_PLAYBACK_LIMIT = 2`, with navigation
  and player-ready timeouts. Off by default (`STREAM_FINDER_PLAYBACK=1` to
  enable); enabling it implies availability probing, since it only measures
  sources already known to have the title.
- Boundaries unchanged (docs/Constraints.md #5): audio is muted because
  autoplay policy requires it of any page — we do not spoof fingerprints,
  solve challenges, or work around anti-bot/login/DRM. A site that blocks a
  headless browser is "unknown" and is left alone.
- Untrusted payloads (Constraints #2): the object read back from the browser
  is validated field by field — non-dict, missing keys, wrong types, `bool`
  masquerading as `int`, negative counters all degrade to "unknown". A
  half-parsed payload would become a confident wrong ranking.

## 2026-09-08 — Task S3: per-title availability, the first title-dependent ranking signal
- Reported as: "recommendations return the same two sites (Cinejoy + Rive)
  for every search". Investigated with debugging-and-error-recovery.
- **The reported cause was not the actual cause.** The searched title was
  never lost, hardcoded or reused: `matched_title`/`imdb_id` differ
  correctly per query (tt7817340 / tt0133093 / tt0903747 / tt0245429 for
  four test titles) and the title does reach the deep link
  (`?query=New+Amsterdam` vs `?query=The+Matrix`). Recorded here because
  "the title is being dropped somewhere" is the intuitive diagnosis and it
  is wrong — anyone re-investigating this should not go looking for it again.
- Actual root cause, in three parts:
  1. `scoring._score()` took **no title input at all** — score was
     f(`starred`, `rank`, `is_deep_link`), with `subtitle_score` always 0
     ("unknown" for every candidate) and `latency_score` a hardcoded 0.0.
     The argmax was therefore mathematically identical for every query.
  2. `ResolvedTitle.kind` was resolved and then discarded at
     `build_site_link()` — never carried onto `SiteLink`/`Candidate`.
  3. No differentiating data existed in what Stage A parses: all 203 sites
     come from `# ► Streaming Sites`, whose subsections are *architecture*
     categories (Stream Aggregators, Multi-Server, Free w/ Ads) and whose
     entries are described near-identically as "Movies / TV / Anime".
- Decision: implement task **S3** — render the strongest candidates in a
  headless browser and check whether each site actually has *this* title,
  then let that drive ranking (`scraper/availability.py`). Chosen over
  re-weighting the existing sites by IMDb `kind`, which would have produced
  variation without relevance: FMHY describes these sites identically, so
  any per-title ordering among them would have been an invented heuristic.
- Two findings from the feasibility spike that shaped the implementation,
  both of which would have produced a silently-wrong feature:
  - **"Is the title in the page text" is not a usable signal.** These sites
    echo the search term back ("Results for: <query>") even with zero
    matches, so a substring check reports every title as available on every
    site. The *result count* is the real signal: a nonsense query renders
    `0 results found`, a real one `59 results found`. There is a regression
    test pinning this exact case.
  - **Only 1 of the 3 deep-linkable sites can be probed at all.** Flixer
    renders its result count; Boomflix returns an identical shell for real
    and nonsense queries; Rive renders a completely empty body headlessly.
    So `_AVAILABILITY_DETECTORS` has one verified entry, and everything else
    stays "unknown" rather than guessing.
- Weights (`scoring._AVAILABILITY_SCORES`): `available` +0.5 outweighs the
  star/position gap without erasing curation; `unavailable` **-2.0** is a
  categorical demotion, deliberately larger than the entire reliability
  spread (max 1.5) so a site confirmed to lack the title is guaranteed to
  rank below every merely-unprobed one rather than incidentally doing so at
  today's rank values; `unknown` is neutral so an unprobeable site is never
  punished for being unprobeable. The first draft used -0.5, which a test
  caught as insufficient — the weight was fixed, not the test.
- Costs and limits, accepted deliberately: probing adds **~8s per search**
  (measured) and needs Playwright plus a ~88MB Chromium download, so it is
  **off by default** in `create_app()` and enabled only by the dev server
  (`STREAM_FINDER_PROBE=0` disables it). Tests never launch a browser —
  `conftest.py` blocks `_render_page_text` the same way it blocks
  `requests.get`. With one probeable site, two titles that Flixer both
  carries still yield the same winning site; what changed is that the answer
  is now *verified* rather than assumed, and a title Flixer lacks now
  produces a different winner. Broader differentiation needs more verified
  detectors, which is additive.
- Alternatives considered: parsing FMHY's content-keyed `Specialty
  Streaming` subsections (Anime / Cartoon / TV / Drama / Classics) and
  matching them to IMDb `kind` — genuinely data-grounded and still worth
  doing, but it renumbers `rank` across the whole document and so changes
  ranking for every existing site, a much wider blast radius than this bug
  warranted. Deferred rather than rejected.

## 2026-09-07 — Live autocomplete: reuse IMDb suggestions, no separate image system, fix a real reopen bug
- Decision: Added `GET /api/suggestions?q=` (up to 5 results, min 2 chars)
  backed by a new `resolve_suggestions()` in `scraper/title_lookup.py`,
  which `resolve_title()` is now implemented in terms of
  (`resolve_suggestions(query, limit=1)`) rather than duplicating the same
  untrusted-payload parsing twice. Each suggestion carries `imdb_id`,
  `title`, `year`, `kind`, and `image_url` — the poster is read straight
  off the same IMDb suggestion entry (`entry["i"]["imageUrl"]`), not fetched
  from anywhere else. On the frontend, `SearchBar` owns the whole feature
  (debounced fetch, dropdown, keyboard nav, click-outside-to-close) rather
  than a separate `Autocomplete` component, since the dropdown has no
  purpose independent of the one input it's anchored to and every closing
  interaction (Escape, outside click, submit, select) already has to route
  through `SearchBar`'s own state.
- Rationale: The backend endpoint must never fail the page — a failed
  dropdown fetch is a missing convenience, not a broken app — so
  `scraper.get_suggestions()` catches `(requests.RequestException,
  ValueError)` (the latter covers a non-JSON IMDb body) and returns `[]`,
  and the route itself never returns a non-2xx for a short/empty query.
  The frontend mirrors that: `fetchSuggestions` in `api/client.js` treats a
  non-array `suggestions` field as `[]` rather than throwing, and
  `SearchBar`'s debounce timer swallows any rejection the same way. A
  monotonically increasing request id discards a stale response that
  resolves after a newer one, so a slow first keystroke's result can't
  flash over what the user has since typed.
  Reusing IMDb's own poster field (rather than a second lookup, e.g. TMDb)
  keeps this a one-API-call feature and matches "use the existing
  data/source architecture where possible" — the tradeoff is IMDb's own
  image availability/quality, which is out of this app's control and
  already handled as an expected `None` case, not an error.
- Bug caught during live verification (not by the test suite — worth
  recording): selecting a suggestion (or restoring a query via a history
  click) sets `SearchBar`'s internal `query` state to the picked title.
  Since the debounce effect's dependency is that same `query`, this
  re-triggered a suggestion fetch a moment later and popped the dropdown
  back open right after `selectSuggestion` had just closed it — visible in
  the browser as the dropdown flashing back over the newly-shown search
  results. Fixed with a one-shot `suppressNextFetch` ref set immediately
  before any *programmatic* `query` change (a selection, or the existing
  `initialQuery`-sync effect for history restores); the debounce effect
  checks and clears it before deciding whether to schedule a fetch. Added
  two regression tests (`does not reopen the dropdown right after a
  suggestion is selected`, `does not open the dropdown when a history
  entry restores the query`) since this was invisible to a fetch-mock-only
  test that never re-renders with a changed `initialQuery` prop.
- Alternatives considered: a separate `/api/search`-style POST endpoint for
  suggestions — rejected, `GET` with a query string is the conventional
  shape for a read-only, cacheable, URL-shareable lookup like this, and
  matches `GET /api/history`. Fetching posters via a dedicated image
  endpoint or TMDb — rejected per "use the existing data/source
  architecture", and IMDb's suggestion payload already had the field.
  Using `AbortController` to cancel an in-flight fetch instead of a
  request-id guard — considered, but the request-id approach needed no
  extra plumbing through the injected `fetchSuggestions` prop used by
  tests, and produces the same outcome (stale results never render).

## 2026-09-07 — Backend setup slice: searches-only schema, no `/api` prefix, TDD-first
- Decision: Implemented a reduced first slice of Phase 1 (`tasks/plan.md`
  B1+B2, plus a simplified B3/B5): a `searches` table with just `id`,
  `query`, `timestamp` (no `matched_title`/`source`/`score` columns yet, no
  `sources` table yet); routes at `/search` (POST) and `/history` (GET)
  rather than the `/api/search` / `/api/history` paths named in
  `tasks/plan.md`; and `/search` currently just validates + persists the
  query (no scraper/scoring call — that's still Phase 2/B4).
- Rationale: the user's instruction for this session explicitly scoped the
  DB to `(id, query, timestamp)` and named the routes `/search`/`/history`
  without an `/api` prefix — followed literally rather than silently
  reconciling with the earlier plan, per Rule 0.5 (scope discipline: touch
  only what's asked). Each test was written first and confirmed failing
  (RED) before the corresponding code was written (GREEN), per
  test-driven-development, using a real in-memory `sqlite3` connection in
  tests rather than a mock/fake — full confidence in real SQL behavior at
  effectively zero cost.
- Alternatives considered: building the full `searches` schema (with
  `matched_title`/`source`/`score`) and `/api`-prefixed routes now to match
  `tasks/plan.md` exactly — rejected for this slice since it would require
  fabricating scoring fields the scraper/scoring layer (B4, not yet built)
  doesn't produce yet; extending the schema when B4 lands is a cheap,
  additive migration (new nullable columns), not a breaking one.
- Follow-up needed: reconcile the `/search`+`/history` route paths against
  `tasks/plan.md`'s `/api/`-prefixed paths before the frontend (Phase 3) is
  built against either — pick one and update whichever doc is wrong.
  **Resolved 2026-09-07 — see entry below.**

## 2026-09-07 — Reconciled backend with tasks/plan.md: `/api/` prefix + richer schema
- Decision: moved `/search` → `/api/search` and `/history` → `/api/history`
  (via `url_prefix="/api"` on each Blueprint, not a path string change per
  route — keeps the prefix in one place if it ever changes again); added
  `matched_title`, `source`, `score` as nullable columns to `searches` and
  as optional keyword arguments to `db.store.add_search` (defaulting to
  `None`), matching `tasks/plan.md`'s B1 acceptance criteria.
  `/health` was left at `/health`, not `/api/health` — the user's
  instruction named only the search/history paths to fix, so per Rule 0.5
  (scope discipline) I didn't also move a route nobody asked about; flagged
  here in case that's an oversight to fix later.
- Rationale: brings the backend back in line with `tasks/plan.md` before B4
  (scraper/scoring) starts building on top of it, per the user's explicit
  request. Each change was made TDD-first: tests updated/added to expect
  the new paths and fields (RED, confirmed failing), then the minimal
  implementation change made them pass (GREEN) — no behavior was changed
  without a test driving it. Columns are nullable rather than
  `NOT NULL` because `/search` still doesn't call any scraper (that's B4);
  a plain query-only search must keep working without fabricating those
  values.
- Alternatives considered: renaming the columns to match some other naming
  scheme — not considered, `matched_title`/`source`/`score` were the names
  `tasks/plan.md` already used, so reusing them keeps the plan and the code
  as one source of truth instead of two dialects of the same idea.

## 2026-09-07 — Visual identity: "cable tuner" design system (frontend-design)
- Decision: replaced the generic dark-mode-with-blue-accent styling with a
  distinct identity built around the app's actual function — FMHY's rank is
  a real sequence, so it's treated as a channel number; deep-link-vs-home-
  page is treated as signal status (a more honest metaphor than a generic
  badge, since a tuner genuinely either has a clean signal or doesn't).
  Palette: `--void`/`--panel` (near-black blue-black), `--paper` (warm
  off-white text), `--phosphor` amber `#FFB300` (primary/brand — a CRT
  amber-monitor color, not the generic acid-green/vermilion single-accent
  default), `--signal` cyan `#37E6C4` (means "direct link confirmed"),
  `--static` red-pink `#FF4D6D` (means "home page only / unconfirmed").
  Type: IBM Plex Sans (body/headings), IBM Plex Mono (labels/data), VT323 —
  an actual CRT-terminal bitmap face — reserved *exclusively* for rank
  badges and the live search "frequency readout," so it stays a signature
  rather than a gimmick used everywhere.
- Rationale: checked against the three generic AI-default looks (cream
  serif+terracotta; near-black+single neon accent; broadsheet hairlines) —
  this isn't any of them. It is dark, but the 3-color signal system is
  functionally tied to real states (confirmed/unconfirmed/neutral), not one
  decorative glow color. Button copy deliberately stayed plain ("Search" /
  "Searching…") rather than theming the controls themselves — per the
  writing guidance, plain/specific beats clever for anything a person has
  to act on; personality lives in type, color, and framing instead.
- Caught and fixed during the pass: an early draft put "SIGNAL LOST — " in
  a CSS `::before` on the error `role="alert"` — generated content isn't
  reliably read by screen readers. Moved to a real `<span>` in the DOM.
- Verification: no tested string was changed (all copy that existing tests
  assert on — "subtitles: unknown", "search there yourself", "couldn't
  identify", the FMHY-error passthrough — was left verbatim); 30/30
  frontend tests still pass unmodified, build is clean, verified live in
  browser with zero console errors.
- Alternatives considered: VHS-rental/cardboard-sleeve aesthetic (warm,
  tactile, also on-theme for "finding something to watch") — the tuner/
  signal direction was chosen because it maps onto the app's actual
  *data* (rank, deep-link status) rather than only its subject matter,
  making the metaphor load-bearing instead of decorative.

## 2026-09-07 — Code review: 3 real bugs found and fixed (code-review-and-quality audit)
Full five-axis review requested across SQL injection, scraping error
handling, and React rendering performance. Findings, each reproduced
before fixing per debugging-and-error-recovery:

- **SQL injection: clean, no finding.** Every query in `db/store.py` uses
  `?` placeholders (including the new `LIMIT ?` below) — confirmed by
  reading every query, not assumed.

- **Fixed — IMDb response-shape change crashed the whole search (500).**
  `title_lookup.resolve_title` assumed every entry in IMDb's `"d"` list was
  a dict with an `"id"` key. Reproduced: stubbing a single non-dict entry
  in the response raised `AttributeError: 'str' object has no attribute
  'get'`, uncaught by `_resolve_quietly`'s `except requests.RequestException`
  (an `AttributeError` isn't a `RequestException`), propagating to a bare
  Flask 500 — directly contradicting the documented design ("IMDb failure
  degrades silently", see the title-resolution decision above). Root-cause
  fix: `resolve_title` now validates the top-level payload is a dict, `"d"`
  is a list, and each entry is a dict before touching it, skipping
  malformed entries instead of crashing. Verified end-to-end: the same
  repro now returns 201 with `matched_title: null` instead of a 500. 4
  regression tests added.
- **Fixed — any FMHY hiccup at cache-expiry took down every search.**
  `get_streaming_sites` had no fallback: a fetch failure always raised,
  even with a valid (if expired) cache sitting right there. Reproduced:
  warmed the cache, expired it, then simulated a `ConnectionError` — every
  search fails despite FMHY's own directory changing "on the order of
  days," meaning the cached list is still almost certainly correct. Fix:
  on fetch failure, serve the cached list (however old) with a
  `logging.warning`, and raise only when there is no cache at all. Also
  added a `logging.warning` when a *successful* fetch parses zero sites —
  that's the signal for "FMHY changed its markdown structure," which
  previously surfaced only as an opaque 502 with nothing in the logs to
  explain why. 3 regression tests added.
- **Fixed — `/api/history` had no pagination; the frontend rendered every
  search ever made.** `list_searches` had no `LIMIT`; the row count only
  grows (no delete endpoint exists yet). Matches the review checklist's
  explicit "missing pagination on list endpoints" item. Fix: `list_searches`
  now defaults to the 50 most recent rows (`DEFAULT_HISTORY_LIMIT`),
  overridable via a `limit` parameter, still parameterized (`LIMIT ?`, not
  string-built). 3 regression tests added.
- **Minor (Consider) — frontend.** `App.jsx` passed a new inline arrow
  function to `HistorySidebar`'s `onSelect` prop on every render. Not a
  measured problem today (list is now capped at 50, `HistorySidebar` isn't
  memoized), but it would silently defeat a future `React.memo` on the
  sidebar. Wrapped in `useCallback` — cheap, and removes the trap.
- Verification: 88/88 backend tests, 30/30 frontend tests, frontend build
  clean.

## 2026-09-07 — Real CORS gap found and fixed via full-stack integration testing
- **Bug found:** a page fetching the API from any origin other than the one
  the Vite proxy hides behind (i.e. any direct cross-origin call) got
  `TypeError: Failed to fetch` in the browser console, with nothing
  identifying it as CORS. `curl -H "Origin: http://localhost:5173"` against
  the same endpoint returned 200 with no `Access-Control-Allow-Origin`
  header — proof the server-side response was identical either way; only
  the browser's CORS enforcement (which curl doesn't apply) caused the
  failure. This is exactly why the earlier "reconciled with plan" and "S2"
  verification passes (curl-only) never caught it.
- **Root cause:** Flask never set any CORS headers. The proxy entry below
  made the *common* dev path work by keeping every browser request
  same-origin, but any request that reached Flask directly — a different
  dev port, a built production frontend served separately, a teammate's
  slightly different setup — had no path to succeed.
- **Fix:** `flask_cors.CORS(app, origins=[...])` in `create_app`, allowlisting
  only `http://localhost:5173` / `127.0.0.1:5173` — never `origins="*"`,
  even though the app has no auth, because a wildcard would let any
  arbitrary page silently relay a visitor's requests through their browser.
  4 new tests (allowed origin reflected, unrecognized origin not reflected,
  preflight OPTIONS for POST /api/search, /health also covered).
  Regression-tested: re-ran the exact failing cross-origin `fetch` after the
  fix — it now succeeds; re-confirmed the unrecognized-origin case is still
  correctly rejected (no header reflected, not just "some header present").
- Alternatives considered: leaving it as proxy-only and documenting "always
  use the Vite proxy in dev" (rejected — the failure mode is silent and the
  fix is small; a wrong assumption about deployment topology is exactly
  what integration testing exists to catch, and the app already needs a
  real deployment story eventually).

## 2026-09-07 — Vite dev proxy instead of CORS on the backend
- Decision: `vite.config.js` proxies `/api` → `http://localhost:5000`; the
  frontend calls relative paths (`/api/search`) only.
- Rationale: the browser sees a single origin, so Flask needs no CORS
  configuration and no `flask-cors` dependency, and no environment-specific
  base URL has to be threaded through the client. Verified end-to-end:
  `POST http://localhost:5173/api/search` reached Flask and returned a real
  result.
- Alternatives considered: `flask-cors` with an allowlist for :5173
  (rejected — a backend dependency and a security surface added purely to
  serve a dev-time convenience the proxy handles for free).

## 2026-09-07 — Link out to sources; no iframe embed
- Decision: `ResultPanel` renders sources as `target="_blank"
  rel="noopener noreferrer"` links. No iframe, and no framing-blocked
  fallback logic.
- Rationale: SPEC.md's "iframe with link fallback" assumed we would have
  *video-page* URLs. We don't — the links are third-party home pages and
  search-results pages (see the S2 entries), which are useless embedded even
  if framing were permitted, and these sites set framing restrictions
  anyway. Building the fallback machinery now would be scaffolding around a
  capability that doesn't exist yet; it belongs with task S3, which is what
  would produce a real video-page URL worth embedding.
- Alternatives considered: implementing the iframe + fallback now to match
  SPEC.md literally (rejected — it would render a blank frame in the common
  case, i.e. shipping the exact failure mode SPEC.md's fallback existed to
  prevent).

## 2026-09-07 — History clicks re-run the search (deviates from SPEC.md)
- Decision: clicking a sidebar entry calls `/api/search` again with that
  entry's query, rather than re-displaying the stored row.
- Rationale: the `searches` row stores only `source` and `score` — not the
  `top_source`/`best_deep_link` structures with component scores that
  `ResultPanel` renders. Re-displaying from storage would show a
  strictly poorer result than the original search did, and the underlying
  FMHY list is cached for an hour anyway, so a repeat search is typically a
  ~2ms cache hit rather than a re-scrape.
- **Known deviation and side effect:** SPEC.md says a past entry should
  re-display "without re-scraping". It also means re-running a past search
  writes a *new* history row, so the sidebar accumulates duplicates —
  observed during browser verification (Dune appeared twice). Fixing it
  properly means either storing the full result JSON per search or
  de-duplicating on query; neither was in scope for this phase.

## 2026-09-07 — S2 abandoned as specified: per-site search scraping is not possible
- Decision: `site_search.py` does **not** scrape each site's search
  results. It links *into* each site's own search for the resolved title
  instead, using a table of routes verified per site.
- Rationale — measured, not assumed. Every top FMHY site renders search
  results client-side; a plain request returns an app shell with zero
  results in it:

  | Site | Static search HTML | Query hits |
  |---|---|---|
  | cinejoy.to | 5.9KB shell | 0 |
  | movy.sx | `__NEXT_DATA__` | 0 |
  | rivestream.app | `__NEXT_DATA__` | 0 |
  | boomflix.qzz.io | `id="root"` | 0 |
  | popcornmovies.ac / 67movies.st | shell | 1 (query echo only) |

  No amount of BeautifulSoup work extracts data that isn't in the
  response. None of the sites served a bot challenge, so nothing here was
  blocked — the data simply isn't server-rendered.
- Alternatives considered: promoting Playwright to the primary path
  (renders the SPA, gets real per-title links + subtitle tracks) — offered
  to the user, who chose the link-building approach; it stays available as
  task S3 for specific high-value sites. Costs that drove the choice:
  ~300MB browser, seconds per site per search, and per-site selectors that
  break on redesign.

## 2026-09-07 — Search routes are verified per site, never guessed
- Decision: `_SEARCH_ADAPTERS` in `site_search.py` contains only routes
  confirmed against the live site (`flixer.gd` → `/search?q=`,
  `boomflix.qzz.io` → `/search?q=`, `rivestream.app` → `/search?query=`).
  Every other site falls back to its home page with `is_deep_link=False`.
- Rationale: guessing is provably wrong. `movy.sx/search?q=` looked fine
  (HTTP 200) but its Next.js `__NEXT_DATA__` reported `page: /404`, and its
  build manifest confirmed the site has **no `/search` route at all** —
  it's id-driven (`/movie/[...params]`). SPAs return 200 for every path, so
  status codes prove nothing; routes were verified from Next.js build
  manifests and JS bundle route strings, and parameter names from
  `searchParams.get("…")` calls in the bundles. A wrong guess sends the
  user to a 404, which is worse than an honest home-page link.
- Follow-up: `cinejoy.to`, `popcornmovies.ac`, `67movies.st` showed no
  search route in the bundles checked — recorded as *unverified*, not
  *absent*; the grep only covered the first several script chunks.

## 2026-09-07 — Return both the top-ranked source and the best deep link
- Decision: `/api/search` returns `top_source` (FMHY's best site) *and*
  `best_deep_link` (the best site we can open directly on the searched
  title, or null).
- Rationale: found during live verification — the winner was *always*
  Cinejoy with `is_deep_link=false`, because FMHY's top-ranked sites aren't
  in the verified adapter table and the deep-link bonus (0.1) can't
  overcome the star tier. So the title-aware feature never actually
  surfaced in the result users would see. Rather than inflate the bonus
  until deep links win (which would let a mediocre site outrank FMHY's top
  pick), both are returned and the frontend can offer the choice. Live
  check: "matrix" → top_source Cinejoy (rank 1, home page),
  best_deep_link Rive (rank 4, `/search?query=The+Matrix`).
- Alternatives considered: raising `_DEEP_LINK_BONUS` above the star gap
  (rejected — silently discards FMHY's curation, which is the app's core
  ranking signal); returning only the deep link (rejected — would drop the
  best site entirely whenever it isn't linkable, which is most of the time).

## 2026-09-07 — Subtitle status is reported as "unknown", never guessed
- Decision: `SiteLink.subtitle_status` / `Candidate.subtitle_status` is
  the string `"unknown"` for every candidate, and scoring gives subtitle
  credit only for `"available"` — which nothing currently sets.
- Rationale: the user asked S2 to return subtitle status. It genuinely
  cannot be determined by this approach: subtitle tracks live inside each
  site's client-rendered player (often inside a nested iframe), so they're
  invisible without executing the page. Reporting a fabricated boolean —
  or defaulting to `False` and letting it read as "no subtitles" — would be
  worse than an explicit "unknown". A three-state field keeps the door open
  for a Playwright-based check (S3) to set a real value later.
- Alternatives considered: inferring subtitles from FMHY's description text
  (rejected — FMHY notes features like "Auto-Next" and "4K" but not
  subtitle availability, so there's nothing to read).

## 2026-09-07 — IMDb's keyless suggestion API for title resolution
- Decision: `title_lookup.py` resolves a raw query to a canonical title,
  year, kind and IMDb id via `v2.sg.media-imdb.com/suggestion/<letter>/<q>.json`.
  IMDb failures degrade to "unresolved" rather than failing the search.
- Rationale: this is what finally makes a search *title-aware* — it fills
  `matched_title` (NULL until now) and gives the deep links a canonical
  title to search for ("matrix" → "The Matrix"). It needs no API key, and
  filtering on `qid` drops IMDb's person/industry records. FMHY is required
  for a search to mean anything; IMDb only enriches it, so the two failure
  modes are deliberately different (502 vs. silent degradation).
- Alternatives considered: TMDB (rejected — needs an API key the user
  would have to obtain and store); OMDb (same); scraping IMDb's HTML
  (rejected — an official JSON endpoint exists).

## 2026-09-07 — S1: parse FMHY's markdown source, not the rendered site
- Decision: `scraper/fmhy_source_list.py` fetches
  `raw.githubusercontent.com/fmhy/edit/main/docs/video.md` and parses it
  with a small line-oriented regex parser — no BeautifulSoup, no Playwright.
- Rationale: FMHY's rendered wiki is a JS-driven SPA, so scraping the HTML
  would need Playwright for what is fundamentally a static document; the
  markdown source behind it is the same content in a far more stable form
  (headings, `* ⭐ **[Name](url)** - desc` bullets). Markdown lines are
  regular enough that a regex parser is simpler and less brittle than an
  HTML tree walk. This drops BeautifulSoup from the dependency list for
  Stage A entirely — it may still be needed for S2 (per-site title search),
  which does scrape real HTML.
- Alternatives considered: BeautifulSoup over the rendered fmhy.net/video
  page (rejected — SPA, needs a browser); Playwright for Stage A (rejected
  — heavyweight for static content, and SPEC.md keeps Playwright as an S2/S3
  fallback, not a default path).

## 2026-09-07 — Ranking uses FMHY's own curation (star + list position)
- Decision: `scoring.pick_best` ranks by `starred` first, then FMHY list
  position (`0.4 / rank`, deliberately smaller than the 0.5 starred/
  unstarred gap so position breaks ties *within* a tier rather than across
  tiers). `rank_sites()` in the scraper applies the same ordering to the
  site list itself.
- Rationale: per the user's instruction — top of FMHY's list means best
  watching experience. FMHY's editors have already done the evaluation this
  app would otherwise be guessing at, and a star is their explicit "this is
  a top pick" marker. Position alone would rank an unstarred aggregator
  above a starred dedicated-server site simply because aggregators are
  listed first, so star-tier has to dominate position.
- Alternatives considered: pure document order (rejected — ignores stars
  across sections); the full heuristic from SPEC.md (reliability allowlist
  + subtitle signal + latency probe) — still the plan for task S4, but not
  available yet, so `latency_score` is a constant 0.0 placeholder that
  cannot affect ordering, and `subtitle_score` only fires if something
  actually sets `has_subtitles`.
- **Honest limitation recorded:** FMHY lists *sites*, not per-title links,
  so `/api/search` returns the best *site to watch on*, not a deep link to
  the searched title, and `matched_title` stays NULL. Per-title resolution
  (and the subtitle signal that depends on reading a title's watch page) is
  task S2. The query string is currently used only as the persisted search
  term, not to filter candidates.

## 2026-09-07 — In-memory TTL cache for the FMHY list; `sources` table still unused
- Decision: `get_streaming_sites()` caches the parsed list in module memory
  for 1 hour (`CACHE_TTL_SECONDS`), with `force_refresh=True` bypassing it.
  No `sources` table was added.
- Rationale: FMHY's directory changes on the order of days, so an hour-long
  cache keeps per-search latency at ~2ms (measured) instead of ~80ms while
  staying fresh; a DB table would add schema and I/O for data that is cheap
  to re-fetch and useless across restarts anyway. Simplest thing that works
  (Rule 0) — the `sources` table from `tasks/plan.md` can be added if
  cross-process/restart persistence ever matters.
- Alternatives considered: persisting sources to SQLite per `tasks/plan.md`
  (deferred, not rejected); no cache at all (rejected — re-downloading a
  115KB document on every keystroke-driven search is wasteful and rude to
  FMHY's host).

## 2026-09-07 — Tests are hard-blocked from making live network calls
- Decision: `backend/conftest.py` has an autouse fixture that replaces
  `requests.get` with a failing stub for every test, opt-out-able via
  `@pytest.mark.allow_network`.
- Rationale: while wiring the route, `test_history_route.py` was silently
  making real requests to FMHY — it passed, but only because the network
  happened to be up, and the suite had quietly become dependent on a third
  party's uptime and markup (exactly what SPEC.md's testing strategy
  forbids). A guard makes that failure mode loud instead of invisible.
  Full-suite runtime dropped from 2.3s to 0.5s once the last live call was
  stubbed — a useful signal that the guard is working.
- Alternatives considered: relying on discipline/code review to keep tests
  offline (rejected — this exact mistake had already happened once,
  undetected, in the same session it was introduced).

## 2026-09-07 — B4: fixture-backed scraper/scoring interface, not real scraping yet
- Decision: added `scraper/__init__.py` (`Candidate` dataclass,
  `get_candidates(title)`, `refresh_sources()`) and `scoring/__init__.py`
  (`ScoreResult` dataclass, `pick_best(candidates)`), both fixture-backed —
  `get_candidates` returns two hardcoded sample candidates, `pick_best`
  scores with constant reliability/latency values plus a real subtitle-
  presence bonus, `refresh_sources` returns a fixed count without touching
  the database.
- Rationale: this is the checkpoint task from `tasks/plan.md` — the
  `Candidate`/`ScoreResult` shapes are the contract every later task
  (S1-S4 real scraping/scoring, B5/B6 route wiring) builds on, so it's
  reviewed now while it's cheap to change, before real network scraping
  exists to build against it. Confirmed with the user before starting
  (they explicitly picked "B4 as planned" over skipping ahead to real FMHY
  scraping). TDD-first as with the rest of the backend: interface tests
  written and confirmed failing (RED) before the implementation (GREEN).
- Alternatives considered: skipping straight to task S1 (real FMHY scrape)
  — rejected per the user's explicit choice, to keep the reviewed-contract
  checkpoint intact; wiring B4's interface into the B5/B6 routes as part of
  this same task — deliberately left out (routes B5/B6 still don't call
  `scraper`/`scoring` yet) to keep this increment to one thing, per
  incremental-implementation's Rule 1 — that wiring is the natural next
  slice.

## 2026-09-07 — History stores only the chosen result, not all candidates
- Decision: `searches` table persists query, matched title, timestamp, and
  the single chosen source (+ its score) — not every candidate found.
- Rationale: keeps the schema simple and history browsing fast; a past
  search shown in the sidebar is meant to be "here's what you watched
  before," not a re-analysis tool. Re-running a search re-scrapes fresh
  anyway, so stale full-candidate lists would add little value.
- Alternatives considered: storing every candidate + score per search, to
  allow re-ranking without re-scraping — rejected for v1 as unnecessary
  complexity; can be added later if history is ever used for analytics.

## 2026-09-07 — Iframe embed with link-fallback, not iframe-only or link-only
- Decision: default to embedding the winning source in an iframe; if the
  response signals framing is blocked (`X-Frame-Options` /
  `frame-ancestors` CSP), fall back to an "Open source" link/button.
- Rationale: many third-party streaming sites block framing, so an
  iframe-only approach would silently show a blank/broken player for a
  meaningful fraction of sources — bad experience with no visible failure
  mode. Link-only would give up the in-app watching experience the app
  exists to provide whenever embedding *is* possible.
- Alternatives considered: always link out (simpler, but throws away the
  core "watch in app" value prop); always iframe (rejected — breaks
  silently on framing-blocked sites).

## 2026-09-07 — Heuristic scoring instead of scoring-by-playback
- Decision: score candidates using a static site-reliability weight, a
  subtitle-presence signal scraped from the watch page, and an HTTP
  latency probe — never by actually loading/playing the video server-side.
- Rationale: playing every candidate to measure real buffering would be
  slow (multiple full-page loads per search) and fragile (headless
  playback of arbitrary third-party embeds is unreliable and heavy). A
  weighted heuristic gives a fast, explainable proxy — the API returns
  component scores so the frontend can show *why* a source won, which
  actual playback metrics wouldn't easily expose per-candidate.
- Alternatives considered: real playback benchmarking per candidate
  (rejected — too slow/fragile for a per-search operation); first-working-
  link with no scoring (rejected — user explicitly wants "best experience,"
  not just "any working link").

## 2026-09-07 — Two-stage scrape (cached FMHY source list, then per-site search)
- Decision: FMHY.net/video is scraped periodically/on-demand to build a
  cached list of candidate *sites* (not per-title links). Each user search
  then queries each cached site's own search page for the title.
- Rationale: FMHY's directory is a list of site names/domains, not a
  per-movie link index — there is no way to get a direct streaming link for
  an arbitrary title straight from FMHY's page. Splitting into "slow,
  infrequent directory refresh" + "fast, per-search site queries" keeps
  individual searches from having to re-scrape FMHY every time, which would
  be both slow and unnecessary load on FMHY.
- Alternatives considered: single-stage scrape (scrape FMHY fresh on every
  search) — rejected as based on a wrong model of what FMHY's page contains
  and unnecessarily slow even if it did.
