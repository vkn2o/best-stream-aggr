# Constraints

Short, explicit list of what must never be done in this codebase.

- Never string-build SQL. Every query goes through `sqlite3`'s `?`
  placeholders (see `db/store.py`) — no f-strings/`.format()`/concatenation
  into SQL, including for things like `LIMIT`.
- Never treat an external response (FMHY's markdown, IMDb's suggestion
  JSON, any future scraped site) as trustworthy in shape. Validate type
  before indexing/`.get()`-ing into it, and degrade gracefully (skip the
  bad item, return `None`/empty) rather than letting a malformed field
  crash the request. Found the hard way: an IMDb response with one
  non-dict entry crashed the whole search with a 500 before this was
  enforced — see docs/Decisions.md, 2026-09-07 code review entry.
- Never let a single external-service hiccup take down a feature that has
  a perfectly good cached fallback. Prefer serving stale data (with a
  logged warning) over a hard failure when the cost of staleness is low —
  see the FMHY stale-cache-fallback decision in docs/Decisions.md.
- Never add an unbounded list endpoint. `/api/history` and anything like it
  must cap rows returned (see `DEFAULT_HISTORY_LIMIT` in `db/store.py`).
- Never bypass CAPTCHAs, paywalls, login walls, or anti-bot protections on
  any candidate streaming site (see SPEC.md Boundaries) — skip the site
  instead.
- Never commit `app.db`, `.venv/`, `node_modules/`, or any scraped-content
  fixture containing third-party copyrighted material.
- Never use `origins="*"` for CORS, even though this app has no auth — keep
  the explicit allowlist in `app.py` (see docs/Decisions.md CORS entry).

8. **Never report a quality signal the app did not actually measure.**
   Availability and playback are either measured or `unknown`/`null` — never
   inferred from each other, from a site's FMHY rank, or from a partially
   parsed payload. A site having a title is not evidence its stream plays;
   an unprobeable site is not evidence of anything. The UI must say "not
   measured" rather than let an untested source read like a good one. Added
   with task S4 — see docs/Decisions.md.

9. **Never present site-wide evidence as if it were about the searched
   title, and never rank on a sample too small to mean anything.**
   `telemetry.py` enforces both: `MIN_SAMPLE_SIZE` before any claim, and a
   `scope` field ("title" vs "site") that the UI surfaces. Reported and
   probed measurements are distinguished by `provenance`. Added with the
   client-side telemetry work - see docs/Decisions.md.
