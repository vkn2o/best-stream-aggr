import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchHistory, fetchSuggestions, search } from "./client";

function mockFetch(response, { ok = true, status = 200 } = {}) {
  const spy = vi.fn().mockResolvedValue({
    ok,
    status,
    json: async () => response,
  });
  global.fetch = spy;
  return spy;
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("search", () => {
  it("posts the query to the backend search endpoint", async () => {
    const spy = mockFetch({ matched_title: "The Matrix" });

    await search("matrix");

    const [url, options] = spy.mock.calls[0];
    expect(url).toBe("/api/search");
    expect(options.method).toBe("POST");
    expect(JSON.parse(options.body)).toEqual({ query: "matrix" });
  });

  it("returns the parsed response body", async () => {
    mockFetch({ matched_title: "The Matrix", year: 1999 });

    const result = await search("matrix");

    expect(result.matched_title).toBe("The Matrix");
  });

  it("throws the backend error message when the request fails", async () => {
    mockFetch(
      { error: "could not reach the FMHY directory" },
      { ok: false, status: 502 },
    );

    await expect(search("matrix")).rejects.toThrow(
      "could not reach the FMHY directory",
    );
  });

  it("throws a generic message when the error body has no message", async () => {
    mockFetch({}, { ok: false, status: 500 });

    await expect(search("matrix")).rejects.toThrow(/500/);
  });
});

describe("fetchHistory", () => {
  it("gets the history endpoint", async () => {
    const spy = mockFetch([]);

    await fetchHistory();

    expect(spy.mock.calls[0][0]).toBe("/api/history");
  });

  it("returns the list of past searches", async () => {
    mockFetch([{ id: 1, query: "matrix" }]);

    const history = await fetchHistory();

    expect(history).toHaveLength(1);
    expect(history[0].query).toBe("matrix");
  });
});

describe("fetchSuggestions", () => {
  it("gets the suggestions endpoint with the query URL-encoded", async () => {
    const spy = mockFetch({ suggestions: [] });

    await fetchSuggestions("the matrix");

    expect(spy.mock.calls[0][0]).toBe("/api/suggestions?q=the%20matrix");
  });

  it("returns the suggestion list from the response body", async () => {
    mockFetch({
      suggestions: [{ imdb_id: "tt0133093", title: "The Matrix" }],
    });

    const suggestions = await fetchSuggestions("matrix");

    expect(suggestions).toHaveLength(1);
    expect(suggestions[0].title).toBe("The Matrix");
  });

  it("returns an empty list when the response has no suggestions field", async () => {
    mockFetch({});

    expect(await fetchSuggestions("matrix")).toEqual([]);
  });

  it("returns an empty list when suggestions is not an array", async () => {
    mockFetch({ suggestions: "not-an-array" });

    expect(await fetchSuggestions("matrix")).toEqual([]);
  });

  it("throws the backend error message when the request fails", async () => {
    mockFetch({ error: "bad request" }, { ok: false, status: 400 });

    await expect(fetchSuggestions("matrix")).rejects.toThrow("bad request");
  });
});
