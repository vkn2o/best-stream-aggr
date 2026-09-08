// ==UserScript==
// @name         Stream Finder — playback quality reporter
// @namespace    streamfinder.local
// @version      1.0.0
// @description  Reports how smoothly a stream actually played back to your local Stream Finder, so it can recommend the source that buffers least.
// @match        https://flixer.gd/*
// @run-at       document-idle
// @grant        none
// ==/UserScript==

/*
 * Why this exists
 * ---------------
 * Stream Finder cannot measure playback itself: the streaming sites gate
 * their streams against automated sessions (see docs/Decisions.md). Your
 * own browser plays them normally, so the measurement happens here instead
 * and is posted back to the local app. This is the same client-side
 * approach real streaming platforms use for quality-of-experience
 * monitoring.
 *
 * What it sends
 * -------------
 * Only playback numbers: whether the video started, how long it took, how
 * often and how long it stalled, and the page's site + IMDb id when the
 * page exposes one. No page content, no account data, no browsing history.
 * It posts to http://localhost:5000 — your own machine.
 *
 * Keeping the metrics comparable
 * ------------------------------
 * `createTracker` deliberately mirrors the definitions in
 * backend/scraper/playback.py, so a reported session and a probed one mean
 * the same thing. It is exported on `window.StreamFinderQoE` and tested
 * from the Vitest suite (frontend/src/qoe/tracker.test.js) by evaluating
 * this file — so this file is the single source of truth, not a copy.
 */
(function () {
  "use strict";

  var ENDPOINT = "http://localhost:5000/api/playback-report";
  // A real viewing session, not a synthetic probe — report once the sample
  // is long enough to be meaningful, then again when the page goes away.
  var REPORT_AFTER_MS = 30000;
  var TICK_MS = 500;

  /**
   * Accumulates playback behaviour. Pure: no DOM, no clock of its own, so
   * it can be driven directly in tests.
   */
  function createTracker(now) {
    var t0 = now();
    // When the viewer asked for playback. Everything about the source's
    // speed is measured from here, not from page load: time spent reading
    // the synopsis before pressing play is the viewer's, not the site's.
    var attemptedAt = null;
    var started = false;
    var startupMs = null;
    var rebufferCount = 0;
    var rebufferMs = 0;
    var waitingSince = null;
    var lastTime = -1;

    function closeStall() {
      if (waitingSince !== null) {
        rebufferMs += Math.round(now() - waitingSince);
        waitingSince = null;
      }
    }

    function stall() {
      // Only count interruptions after playback has actually begun; time
      // before the first frame is start-up, not rebuffering.
      if (started && waitingSince === null) {
        rebufferCount += 1;
        waitingSince = now();
      }
    }

    /** The clock playback is measured against: the request, else load. */
    function origin() {
      return attemptedAt !== null ? attemptedAt : t0;
    }

    return {
      /** The viewer pressed play (or the page autoplayed). */
      attempt: function () {
        if (attemptedAt === null) {
          attemptedAt = now();
        }
      },
      playing: function () {
        if (!started) {
          started = true;
          startupMs = Math.round(now() - origin());
        } else {
          closeStall();
        }
      },
      stall: stall,
      /**
       * A video can sit in a "playing" state while currentTime never
       * advances; the events alone would call that flawless playback.
       */
      tick: function (currentTime, paused) {
        if (!started) return;
        if (currentTime === lastTime && !paused) {
          stall();
        } else if (currentTime !== lastTime) {
          closeStall();
        }
        lastTime = currentTime;
      },
      snapshot: function () {
        return {
          attempted: attemptedAt !== null,
          started: started,
          startupMs: startupMs,
          rebufferCount: rebufferCount,
          rebufferMs: rebufferMs,
          observedMs: Math.round(now() - origin())
        };
      }
    };
  }

  /** Shape a tracker snapshot into the API's report payload. */
  function buildReport(snapshot, site, titleRef) {
    var ref = titleRef || {};
    var report = {
      site: site,
      imdb_id: ref.imdb_id || null,
      started: snapshot.started,
      startup_ms: snapshot.startupMs,
      rebuffer_count: snapshot.rebufferCount,
      rebuffer_ms: snapshot.rebufferMs,
      observed_ms: snapshot.observedMs
    };
    // The API rejects half a reference, so send both fields or neither.
    if (!report.imdb_id && ref.tmdb_id && ref.media_type) {
      report.tmdb_id = ref.tmdb_id;
      report.media_type = ref.media_type;
    }
    return report;
  }

  function attach(video, tracker, setInterval_) {
    video.addEventListener("play", tracker.attempt);
    video.addEventListener("playing", tracker.playing);
    video.addEventListener("waiting", tracker.stall);
    video.addEventListener("stalled", tracker.stall);
    return setInterval_(function () {
      tracker.tick(video.currentTime, video.paused);
    }, TICK_MS);
  }

  function send(report) {
    // keepalive so the final report still goes out as the page unloads.
    fetch(ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(report),
      keepalive: true,
      mode: "cors"
    }).catch(function () {
      /* Stream Finder isn't running — nothing to do, and nothing to break. */
    });
  }

  function install() {
    var video = document.querySelector("video");
    if (!video) {
      // Players mount late; watch for one rather than giving up.
      var observer = new MutationObserver(function () {
        var found = document.querySelector("video");
        if (found) {
          observer.disconnect();
          start(found);
        }
      });
      observer.observe(document.documentElement, {
        childList: true,
        subtree: true
      });
      return;
    }
    start(video);
  }

  function start(video) {
    var tracker = createTracker(function () {
      return performance.now();
    });
    attach(video, tracker, setInterval);

    var reported = false;
    function report() {
      var snapshot = tracker.snapshot();
      if (!shouldReport(snapshot)) return;
      send(
        buildReport(
          snapshot,
          location.hostname,
          titleRefFromPage(location.pathname, document.documentElement.innerHTML)
        )
      );
      reported = true;
    }

    // The window runs from the play request, not from page load, so every
    // reported session covers the same thing: the first 30 seconds of
    // actually trying to watch.
    var scheduled = false;
    video.addEventListener("play", function () {
      if (!scheduled) {
        scheduled = true;
        setTimeout(report, REPORT_AFTER_MS);
      }
    });

    window.addEventListener("pagehide", function () {
      if (!reported) report();
    });
  }

  /**
   * Whether a session is worth reporting at all.
   *
   * A viewer who opened a player and never pressed play measured nothing
   * about the source. Sending that as `started: false` made the scorer
   * treat it as a broken stream (_PLAYBACK_FAILED) and penalised the site
   * for the viewer's own hesitation. A stream that *was* asked to play and
   * didn't is a genuine failure, and is still reported.
   */
  function shouldReport(snapshot) {
    return snapshot.attempted && snapshot.observedMs > 0;
  }

  /**
   * How this page identifies the title being watched.
   *
   * An IMDb id if the page exposes one, else the TMDB id out of a player
   * route — Flixer's `/watch/movie/603` and `/watch/tv/1396/1/1` carry no
   * `tt` id anywhere, so scanning the markup alone left every reported
   * session with no title at all. The backend maps a TMDB reference back
   * (routes/playback_report.py). Season and episode are deliberately
   * dropped: playback quality is a property of the source, not of which
   * episode you happened to be on.
   *
   * Takes its inputs as arguments so it can be tested without a browser.
   */
  function titleRefFromPage(pathname, html) {
    var match = html.match(/\btt\d{7,9}\b/);
    if (match) return { imdb_id: match[0] };

    var route = pathname.match(/\/watch\/(movie|tv)\/(\d+)/);
    if (route) return { tmdb_id: Number(route[2]), media_type: route[1] };

    return {};
  }

  window.StreamFinderQoE = {
    createTracker: createTracker,
    buildReport: buildReport,
    shouldReport: shouldReport,
    titleRefFromPage: titleRefFromPage,
    attach: attach
  };

  if (!window.__STREAMFINDER_QOE_NO_AUTOSTART__) {
    install();
  }
})();
