import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import * as api from "./api/client";

const SEARCH_RESPONSE = {
  search: { id: 1, query: "matrix", matched_title: "The Matrix" },
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
  best_deep_link: null,
  history: [
    {
      id: 1,
      query: "matrix",
      matched_title: "The Matrix",
      source: "https://cinejoy.to/",
      score: 1.4,
      timestamp: "2026-09-07T16:39:12.000Z",
    },
  ],
};

beforeEach(() => {
  vi.spyOn(api, "fetchHistory").mockResolvedValue([]);
  vi.spyOn(api, "search").mockResolvedValue(SEARCH_RESPONSE);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("App", () => {
  it("loads existing history on mount", async () => {
    api.fetchHistory.mockResolvedValue(SEARCH_RESPONSE.history);

    render(<App />);

    expect(await screen.findByText("The Matrix")).toBeInTheDocument();
  });

  it("searches and shows the result", async () => {
    render(<App />);

    await userEvent.type(screen.getByRole("searchbox"), "matrix");
    await userEvent.click(screen.getByRole("button", { name: /^search$/i }));

    expect(api.search).toHaveBeenCalledWith("matrix");
    expect(await screen.findByRole("link", { name: /Cinejoy/ })).toBeInTheDocument();
  });

  it("refreshes the sidebar from the search response", async () => {
    render(<App />);

    await userEvent.type(screen.getByRole("searchbox"), "matrix");
    await userEvent.click(screen.getByRole("button", { name: /^search$/i }));

    await waitFor(() => {
      expect(screen.getAllByRole("listitem")).toHaveLength(1);
    });
  });

  it("surfaces a backend error to the user", async () => {
    api.search.mockRejectedValue(new Error("could not reach the FMHY directory"));

    render(<App />);
    await userEvent.type(screen.getByRole("searchbox"), "matrix");
    await userEvent.click(screen.getByRole("button", { name: /^search$/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/FMHY directory/);
  });

  it("re-runs a past search when its history entry is clicked", async () => {
    api.fetchHistory.mockResolvedValue(SEARCH_RESPONSE.history);

    render(<App />);
    await userEvent.click(await screen.findByRole("button", { name: /The Matrix/ }));

    await waitFor(() => {
      expect(api.search).toHaveBeenCalledWith("matrix");
    });
  });
});
