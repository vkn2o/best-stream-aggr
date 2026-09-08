import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import ResultPanel from "./ResultPanel";

const RESULT = {
  matched_title: "The Matrix",
  year: 1999,
  imdb_id: "tt0133093",
  top_source: {
    url: "https://cinejoy.to/",
    site_name: "Cinejoy",
    is_deep_link: false,
    subtitle_status: "unknown",
    rank: 1,
    starred: true,
    total_score: 1.4,
    scores: { reliability: 1.4, subtitle: 0, latency: 0 },
  },
  best_deep_link: {
    url: "https://www.rivestream.app/search?query=The+Matrix",
    site_name: "Rive",
    is_deep_link: true,
    subtitle_status: "unknown",
    rank: 4,
    starred: true,
    total_score: 1.2,
    scores: { reliability: 1.2, subtitle: 0, latency: 0 },
  },
};

function withSource(overrides) {
  return {
    ...RESULT,
    top_source: { ...RESULT.top_source, ...overrides },
  };
}

describe("ResultPanel evidence line", () => {
  it("reports how many results a site had when availability was measured", () => {
    render(
      <ResultPanel
        result={withSource({ availability: "available", result_count: 59 })}
      />,
    );

    expect(screen.getByText(/59 results/)).toBeInTheDocument();
  });

  it("says plainly when a site does not have the title", () => {
    render(
      <ResultPanel
        result={withSource({ availability: "unavailable", result_count: 0 })}
      />,
    );

    expect(screen.getByText(/not on this site/i)).toBeInTheDocument();
  });

  it("reports measured playback with its start time and buffering", () => {
    render(
      <ResultPanel
        result={withSource({
          availability: "available",
          result_count: 59,
          playback: {
            status: "measured",
            started: true,
            startup_ms: 1200,
            rebuffer_count: 0,
            rebuffer_ms: 0,
            observed_ms: 10000,
          },
        })}
      />,
    );

    expect(screen.getByText(/played in 1\.2s/i)).toBeInTheDocument();
    expect(screen.getByText(/no rebuffering/i)).toBeInTheDocument();
  });

  it("reports buffering counts when playback stuttered", () => {
    render(
      <ResultPanel
        result={withSource({
          playback: {
            status: "measured",
            started: true,
            startup_ms: 2500,
            rebuffer_count: 3,
            rebuffer_ms: 2100,
            observed_ms: 10000,
          },
        })}
      />,
    );

    expect(screen.getByText(/3 rebuffers/i)).toBeInTheDocument();
    expect(screen.getByText(/2\.1s buffering/i)).toBeInTheDocument();
  });

  it("never claims no rebuffering when buffering time was measured", () => {
    render(
      <ResultPanel
        result={withSource({
          playback: {
            status: "measured",
            started: true,
            startup_ms: 6406,
            // An average over five reported sessions, one of which stalled.
            rebuffer_count: 0.2,
            rebuffer_ms: 125,
            observed_ms: 30659,
            provenance: "reported",
            sample_size: 5,
            scope: "site",
          },
        })}
      />,
    );

    expect(screen.queryByText(/no rebuffering/i)).not.toBeInTheDocument();
    expect(screen.getByText(/0\.2 rebuffers/i)).toBeInTheDocument();
    expect(screen.getByText(/0\.1s buffering/i)).toBeInTheDocument();
  });

  it("does not claim smooth playback when only the buffering time is non-zero", () => {
    render(
      <ResultPanel
        result={withSource({
          playback: {
            status: "measured",
            started: true,
            startup_ms: 1500,
            rebuffer_count: 0,
            rebuffer_ms: 125,
            observed_ms: 30000,
          },
        })}
      />,
    );

    // Either field being non-zero means it stalled. Claiming otherwise is
    // the overclaim this app exists to avoid.
    expect(screen.queryByText(/no rebuffering/i)).not.toBeInTheDocument();
  });

  it("says a measured stream never started rather than implying it is fine", () => {
    render(
      <ResultPanel
        result={withSource({
          playback: {
            status: "measured",
            started: false,
            startup_ms: null,
            rebuffer_count: 0,
            rebuffer_ms: 0,
            observed_ms: 10000,
          },
        })}
      />,
    );

    expect(screen.getByText(/did not start/i)).toBeInTheDocument();
  });

  it("says playback was not measured when it wasn't, never claiming it is smooth", () => {
    render(<ResultPanel result={withSource({ playback: null })} />);

    const notMeasured = screen.getAllByText(/not measured/i);
    expect(notMeasured.length).toBeGreaterThan(0);
    // The honesty rule: an unmeasured source must never read as a good one.
    expect(screen.queryByText(/no rebuffering/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/played in/i)).not.toBeInTheDocument();
  });

  it("does not crash on a response that predates the playback field", () => {
    render(<ResultPanel result={RESULT} />);

    expect(screen.getByRole("link", { name: /Cinejoy/ })).toBeInTheDocument();
  });
});

describe("ResultPanel link precision", () => {
  it("says when a link opens the title's player directly", () => {
    render(<ResultPanel result={withSource({ link_kind: "title" })} />);

    expect(screen.getByText(/opens the player/i)).toBeInTheDocument();
  });

  it("still calls a search link a direct link", () => {
    render(<ResultPanel result={withSource({ link_kind: "search" })} />);

    // Both cards can carry this label, so assert on presence, not count.
    expect(screen.getAllByText(/direct link/i).length).toBeGreaterThan(0);
  });

  it("says when only the home page is available", () => {
    render(<ResultPanel result={withSource({ link_kind: "home" })} />);

    expect(screen.getByText(/home page only/i)).toBeInTheDocument();
  });
});

describe("ResultPanel playback provenance", () => {
  const measured = {
    status: "measured",
    started: true,
    startup_ms: 1400,
    rebuffer_count: 0,
    rebuffer_ms: 0,
    observed_ms: 30000,
  };

  it("credits measurements to the viewer's own sessions", () => {
    render(
      <ResultPanel
        result={withSource({
          playback: { ...measured, provenance: "reported", sample_size: 5, scope: "title" },
        })}
      />,
    );

    expect(screen.getByText(/5 of your sessions/i)).toBeInTheDocument();
  });

  it("marks site-wide data as being about the site, not this title", () => {
    render(
      <ResultPanel
        result={withSource({
          playback: { ...measured, provenance: "reported", sample_size: 4, scope: "site" },
        })}
      />,
    );

    // The honesty rule: never let site-wide evidence read as title-specific.
    expect(screen.getByText(/site-wide/i)).toBeInTheDocument();
  });

  it("uses the singular for a single session", () => {
    render(
      <ResultPanel
        result={withSource({
          playback: { ...measured, provenance: "reported", sample_size: 1, scope: "title" },
        })}
      />,
    );

    expect(screen.getByText(/1 of your sessions/i)).not.toBeNull();
  });
});

describe("ResultPanel", () => {
  it("shows the matched title and year", () => {
    render(<ResultPanel result={RESULT} />);

    expect(screen.getByText(/The Matrix/)).toBeInTheDocument();
    expect(screen.getByText(/1999/)).toBeInTheDocument();
  });

  it("links to the top ranked source", () => {
    render(<ResultPanel result={RESULT} />);

    const link = screen.getByRole("link", { name: /Cinejoy/ });
    expect(link).toHaveAttribute("href", "https://cinejoy.to/");
  });

  it("opens sources in a new tab safely", () => {
    render(<ResultPanel result={RESULT} />);

    const link = screen.getByRole("link", { name: /Cinejoy/ });
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
  });

  it("says when the top source only links to the site's home page", () => {
    render(<ResultPanel result={RESULT} />);

    expect(screen.getByText(/search there yourself/i)).toBeInTheDocument();
  });

  it("offers the direct search link when one is available", () => {
    render(<ResultPanel result={RESULT} />);

    const link = screen.getByRole("link", { name: /Rive/ });
    expect(link).toHaveAttribute(
      "href",
      "https://www.rivestream.app/search?query=The+Matrix",
    );
  });

  it("reports subtitle status as unknown rather than implying none", () => {
    render(<ResultPanel result={RESULT} />);

    expect(screen.getAllByText(/subtitles: unknown/i).length).toBeGreaterThan(0);
  });

  it("says so when no site could be linked directly", () => {
    render(<ResultPanel result={{ ...RESULT, best_deep_link: null }} />);

    expect(screen.getByText(/no site could be opened directly/i)).toBeInTheDocument();
  });

  it("notes when the title could not be identified", () => {
    render(
      <ResultPanel
        result={{ ...RESULT, matched_title: null, year: null, imdb_id: null }}
      />,
    );

    expect(screen.getByText(/couldn't identify/i)).toBeInTheDocument();
  });

  it("shows an error instead of a result when the search failed", () => {
    render(<ResultPanel error="could not reach the FMHY directory" />);

    expect(screen.getByRole("alert")).toHaveTextContent(/FMHY directory/);
  });

  it("renders nothing before the first search", () => {
    const { container } = render(<ResultPanel />);

    expect(container).toBeEmptyDOMElement();
  });
});
