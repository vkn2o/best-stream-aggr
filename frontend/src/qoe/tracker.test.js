/**
 * Tests for the playback tracker inside clients/streamfinder-qoe.user.js.
 *
 * The userscript is a classic script (Tampermonkey can't load ES modules),
 * so rather than keeping a duplicate copy of the metric logic here, the
 * real file is read and evaluated with a fake `window`. That keeps the
 * userscript itself the single source of truth — a copy would drift, and
 * these numbers have to keep matching backend/scraper/playback.py for
 * reported and probed sessions to be comparable.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { beforeAll, describe, expect, it } from "vitest";

let StreamFinderQoE;

beforeAll(() => {
  // Vitest runs with the frontend/ directory as cwd.
  const path = resolve(process.cwd(), "../clients/streamfinder-qoe.user.js");
  const source = readFileSync(path, "utf8");
  const fakeWindow = { __STREAMFINDER_QOE_NO_AUTOSTART__: true };
  // eslint-disable-next-line no-new-func
  new Function("window", source)(fakeWindow);
  StreamFinderQoE = fakeWindow.StreamFinderQoE;
});

/** A tracker driven by a clock we control, so timings are exact. */
function trackerAt(clock) {
  return StreamFinderQoE.createTracker(() => clock.now);
}

describe("playback tracker", () => {
  it("is exported by the userscript", () => {
    expect(StreamFinderQoE.createTracker).toBeTypeOf("function");
  });

  it("measures start-up as the time to the first playing event", () => {
    const clock = { now: 0 };
    const tracker = trackerAt(clock);

    clock.now = 1400;
    tracker.playing();

    expect(tracker.snapshot().startupMs).toBe(1400);
    expect(tracker.snapshot().started).toBe(true);
  });

  it("reports nothing started before the first playing event", () => {
    const snapshot = trackerAt({ now: 0 }).snapshot();

    expect(snapshot.started).toBe(false);
    expect(snapshot.startupMs).toBeNull();
  });

  it("counts a stall and the time spent waiting", () => {
    const clock = { now: 0 };
    const tracker = trackerAt(clock);

    clock.now = 500;
    tracker.playing();
    clock.now = 2000;
    tracker.stall();
    clock.now = 3200;
    tracker.playing();

    const snapshot = tracker.snapshot();
    expect(snapshot.rebufferCount).toBe(1);
    expect(snapshot.rebufferMs).toBe(1200);
  });

  it("does not count waiting before playback ever began as rebuffering", () => {
    const clock = { now: 0 };
    const tracker = trackerAt(clock);

    tracker.stall();
    clock.now = 900;
    tracker.playing();

    // That was start-up, not an interruption.
    expect(tracker.snapshot().rebufferCount).toBe(0);
    expect(tracker.snapshot().startupMs).toBe(900);
  });

  it("does not double-count one continuous stall", () => {
    const clock = { now: 0 };
    const tracker = trackerAt(clock);

    tracker.playing();
    clock.now = 1000;
    tracker.stall();
    clock.now = 1200;
    tracker.stall();

    expect(tracker.snapshot().rebufferCount).toBe(1);
  });

  it("detects a silent stall where currentTime stops advancing", () => {
    const clock = { now: 0 };
    const tracker = trackerAt(clock);

    tracker.playing();
    clock.now = 500;
    tracker.tick(10, false);
    clock.now = 1000;
    tracker.tick(10, false); // same position, still not paused

    expect(tracker.snapshot().rebufferCount).toBe(1);
  });

  it("does not treat a paused video as buffering", () => {
    const clock = { now: 0 };
    const tracker = trackerAt(clock);

    tracker.playing();
    clock.now = 500;
    tracker.tick(10, true);
    clock.now = 1000;
    tracker.tick(10, true);

    expect(tracker.snapshot().rebufferCount).toBe(0);
  });

  it("closes a stall once playback advances again", () => {
    const clock = { now: 0 };
    const tracker = trackerAt(clock);

    tracker.playing();
    clock.now = 500;
    tracker.tick(10, false);
    clock.now = 1000;
    tracker.tick(10, false); // stalls here
    clock.now = 1800;
    tracker.tick(12, false); // moving again

    const snapshot = tracker.snapshot();
    expect(snapshot.rebufferCount).toBe(1);
    expect(snapshot.rebufferMs).toBe(800);
  });

  it("reports how long it observed", () => {
    const clock = { now: 0 };
    const tracker = trackerAt(clock);

    clock.now = 30000;

    expect(tracker.snapshot().observedMs).toBe(30000);
  });
});

describe("buildReport", () => {
  it("maps a snapshot onto the API's payload shape", () => {
    const snapshot = {
      started: true,
      startupMs: 1200,
      rebufferCount: 2,
      rebufferMs: 700,
      observedMs: 30000,
    };

    expect(
      StreamFinderQoE.buildReport(snapshot, "flixer.gd", { imdb_id: "tt0133093" }),
    ).toEqual({
      site: "flixer.gd",
      imdb_id: "tt0133093",
      started: true,
      startup_ms: 1200,
      rebuffer_count: 2,
      rebuffer_ms: 700,
      observed_ms: 30000,
    });
  });

  it("sends a null title rather than an empty string", () => {
    const snapshot = {
      started: false,
      startupMs: null,
      rebufferCount: 0,
      rebufferMs: 0,
      observedMs: 30000,
    };

    expect(StreamFinderQoE.buildReport(snapshot, "flixer.gd", {}).imdb_id).toBeNull();
  });
});

describe("buildReport title reference", () => {
  const snapshot = {
    started: true,
    startupMs: 1200,
    rebufferCount: 0,
    rebufferMs: 0,
    observedMs: 30000,
  };

  it("sends a TMDB reference when the page has no IMDb id", () => {
    const report = StreamFinderQoE.buildReport(snapshot, "flixer.gd", {
      tmdb_id: 603,
      media_type: "movie",
    });

    expect(report.imdb_id).toBeNull();
    expect(report.tmdb_id).toBe(603);
    expect(report.media_type).toBe("movie");
  });

  it("omits the TMDB fields entirely when there is an IMDb id", () => {
    const report = StreamFinderQoE.buildReport(snapshot, "flixer.gd", {
      imdb_id: "tt0133093",
    });

    // The API rejects half a reference, so absent must mean absent.
    expect("tmdb_id" in report).toBe(false);
    expect("media_type" in report).toBe(false);
  });
});

describe("titleRefFromPage", () => {
  /** Drives the real parser against a URL, without a browser. */
  function refFor(pathname, html) {
    return StreamFinderQoE.titleRefFromPage(pathname, html || "<html></html>");
  }

  it("reads a movie's TMDB id out of the player URL", () => {
    // The bug this fixes: flixer.gd/watch/movie/603 has no tt id anywhere,
    // so every session was stored with no title at all.
    expect(refFor("/watch/movie/603")).toEqual({
      tmdb_id: 603,
      media_type: "movie",
    });
  });

  it("reads a series' TMDB id, ignoring the season and episode", () => {
    expect(refFor("/watch/tv/1396/1/1")).toEqual({
      tmdb_id: 1396,
      media_type: "tv",
    });
  });

  it("prefers an IMDb id when the page exposes one", () => {
    expect(refFor("/watch/movie/603", "<p>tt0133093</p>")).toEqual({
      imdb_id: "tt0133093",
    });
  });

  it("returns no reference for a page that identifies nothing", () => {
    expect(refFor("/search?q=matrix")).toEqual({});
  });
});

describe("playback that was never requested", () => {
  /*
   * A viewer who opens a player and doesn't press play has measured
   * nothing about the source. Reporting that as started=false scored it as
   * a failed stream (_PLAYBACK_FAILED, -1.5) - the site penalised for the
   * viewer's own hesitation. Observed twice against live sessions.
   */
  it("knows playback was never requested", () => {
    expect(trackerAt({ now: 0 }).snapshot().attempted).toBe(false);
  });

  it("knows playback was requested once play is pressed", () => {
    const tracker = trackerAt({ now: 0 });
    tracker.attempt();

    expect(tracker.snapshot().attempted).toBe(true);
  });

  it("is not worth reporting when playback was never requested", () => {
    const clock = { now: 0 };
    const tracker = trackerAt(clock);
    clock.now = 30000;

    expect(StreamFinderQoE.shouldReport(tracker.snapshot())).toBe(false);
  });

  it("is worth reporting a requested stream that never played", () => {
    const clock = { now: 0 };
    const tracker = trackerAt(clock);
    tracker.attempt();
    clock.now = 30000;

    // This one is a real failure: it was asked to play and didn't.
    const snapshot = tracker.snapshot();
    expect(snapshot.started).toBe(false);
    expect(StreamFinderQoE.shouldReport(snapshot)).toBe(true);
  });

  it("only counts the first request", () => {
    const clock = { now: 0 };
    const tracker = trackerAt(clock);
    tracker.attempt();
    clock.now = 5000;
    tracker.attempt(); // pause, then play again
    clock.now = 9000;
    tracker.playing();

    // Start-up is still measured from the original request.
    expect(tracker.snapshot().startupMs).toBe(9000);
  });

  it("attaches to the play event so a request is noticed", () => {
    const listeners = {};
    const video = {
      currentTime: 0,
      paused: true,
      addEventListener: (name, fn) => {
        listeners[name] = fn;
      },
    };
    const tracker = trackerAt({ now: 0 });
    StreamFinderQoE.attach(video, tracker, () => 0);

    listeners.play();

    expect(tracker.snapshot().attempted).toBe(true);
  });
});

describe("start-up timing", () => {
  it("measures start-up from the play request, not from page load", () => {
    const clock = { now: 0 };
    const tracker = trackerAt(clock);

    clock.now = 20000; // the viewer read the synopsis for 20 seconds
    tracker.attempt();
    clock.now = 21200;
    tracker.playing();

    // 1.2s is how fast the source is. 21.2s is how slow the viewer is.
    expect(tracker.snapshot().startupMs).toBe(1200);
  });

  it("counts the observation window from the play request", () => {
    const clock = { now: 0 };
    const tracker = trackerAt(clock);

    clock.now = 5000;
    tracker.attempt();
    clock.now = 35000;

    expect(tracker.snapshot().observedMs).toBe(30000);
  });
});
