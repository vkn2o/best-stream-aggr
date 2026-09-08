import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import SearchBar from "./SearchBar";

describe("SearchBar", () => {
  it("submits the typed query", async () => {
    const onSearch = vi.fn();
    render(<SearchBar onSearch={onSearch} />);

    await userEvent.type(screen.getByRole("searchbox"), "the matrix");
    await userEvent.click(screen.getByRole("button", { name: /search/i }));

    expect(onSearch).toHaveBeenCalledWith("the matrix");
  });

  it("trims surrounding whitespace from the query", async () => {
    const onSearch = vi.fn();
    render(<SearchBar onSearch={onSearch} />);

    await userEvent.type(screen.getByRole("searchbox"), "  dune  ");
    await userEvent.click(screen.getByRole("button", { name: /search/i }));

    expect(onSearch).toHaveBeenCalledWith("dune");
  });

  it("does not submit an empty query", async () => {
    const onSearch = vi.fn();
    render(<SearchBar onSearch={onSearch} />);

    await userEvent.click(screen.getByRole("button", { name: /search/i }));

    expect(onSearch).not.toHaveBeenCalled();
  });

  it("disables the button while a search is in flight", () => {
    render(<SearchBar onSearch={vi.fn()} isSearching />);

    expect(screen.getByRole("button", { name: /searching/i })).toBeDisabled();
  });

  it("shows the query passed in from a restored history entry", () => {
    render(<SearchBar onSearch={vi.fn()} initialQuery="breaking bad" />);

    expect(screen.getByRole("searchbox")).toHaveValue("breaking bad");
  });
});

// The debounce is 300ms, so these wait past it with a real timer rather
// than faking timers — simpler to keep in sync with user-event's own
// internal delays than juggling two timer sources.
const PAST_DEBOUNCE_MS = 400;

function waitPastDebounce() {
  return act(
    () => new Promise((resolve) => setTimeout(resolve, PAST_DEBOUNCE_MS)),
  );
}

const MATRIX_SUGGESTIONS = [
  {
    imdb_id: "tt0133093",
    title: "The Matrix",
    year: 1999,
    kind: "movie",
    image_url: "https://example.test/matrix.jpg",
  },
  {
    imdb_id: "tt10838180",
    title: "The Matrix Resurrections",
    year: 2021,
    kind: "movie",
    image_url: null,
  },
];

describe("SearchBar autocomplete", () => {
  it("does not fetch suggestions for a query shorter than two characters", async () => {
    const fetchSuggestions = vi.fn().mockResolvedValue([]);
    render(<SearchBar onSearch={vi.fn()} fetchSuggestions={fetchSuggestions} />);

    await userEvent.type(screen.getByRole("searchbox"), "m");
    await waitPastDebounce();

    expect(fetchSuggestions).not.toHaveBeenCalled();
  });

  it("fetches and shows suggestions once past the debounce window", async () => {
    const fetchSuggestions = vi.fn().mockResolvedValue(MATRIX_SUGGESTIONS);
    render(<SearchBar onSearch={vi.fn()} fetchSuggestions={fetchSuggestions} />);

    await userEvent.type(screen.getByRole("searchbox"), "matrix");
    await waitPastDebounce();

    expect(fetchSuggestions).toHaveBeenCalledWith("matrix");
    expect(await screen.findByRole("listbox")).toBeInTheDocument();
    expect(screen.getByText("The Matrix Resurrections")).toBeInTheDocument();
  });

  it("debounces so a fast typist only triggers one request", async () => {
    const fetchSuggestions = vi.fn().mockResolvedValue(MATRIX_SUGGESTIONS);
    render(<SearchBar onSearch={vi.fn()} fetchSuggestions={fetchSuggestions} />);

    await userEvent.type(screen.getByRole("searchbox"), "matrix");
    await waitPastDebounce();

    expect(fetchSuggestions).toHaveBeenCalledTimes(1);
  });

  it("shows metadata (year and type) beside each suggestion", async () => {
    const fetchSuggestions = vi.fn().mockResolvedValue(MATRIX_SUGGESTIONS);
    render(<SearchBar onSearch={vi.fn()} fetchSuggestions={fetchSuggestions} />);

    await userEvent.type(screen.getByRole("searchbox"), "matrix");
    await waitPastDebounce();

    expect(await screen.findByText(/1999/)).toBeInTheDocument();
    expect(screen.getAllByText(/Movie/).length).toBeGreaterThan(0);
  });

  it("shows a poster image on the left of each suggestion when available", async () => {
    const fetchSuggestions = vi.fn().mockResolvedValue(MATRIX_SUGGESTIONS);
    render(<SearchBar onSearch={vi.fn()} fetchSuggestions={fetchSuggestions} />);

    await userEvent.type(screen.getByRole("searchbox"), "matrix");
    await waitPastDebounce();

    const options = await screen.findAllByRole("option");
    const image = options[0].querySelector("img.suggestions__poster");
    expect(image).toHaveAttribute("src", "https://example.test/matrix.jpg");
  });

  it("falls back to a placeholder, not a broken image, when there is no poster", async () => {
    const fetchSuggestions = vi.fn().mockResolvedValue(MATRIX_SUGGESTIONS);
    render(<SearchBar onSearch={vi.fn()} fetchSuggestions={fetchSuggestions} />);

    await userEvent.type(screen.getByRole("searchbox"), "matrix");
    await waitPastDebounce();

    const options = await screen.findAllByRole("option");
    expect(options[1].querySelector("img")).not.toBeInTheDocument();
    expect(
      options[1].querySelector(".suggestions__poster--empty"),
    ).toBeInTheDocument();
  });

  it("hides a poster and falls back to the placeholder if it fails to load", async () => {
    const fetchSuggestions = vi.fn().mockResolvedValue(MATRIX_SUGGESTIONS);
    render(<SearchBar onSearch={vi.fn()} fetchSuggestions={fetchSuggestions} />);

    await userEvent.type(screen.getByRole("searchbox"), "matrix");
    await waitPastDebounce();

    const options = await screen.findAllByRole("option");
    const image = options[0].querySelector("img");
    fireEvent.error(image);

    expect(
      options[0].querySelector(".suggestions__poster--empty"),
    ).toBeInTheDocument();
  });

  it("selects a suggestion on click: fills the input, searches, and closes the dropdown", async () => {
    const onSearch = vi.fn();
    const fetchSuggestions = vi.fn().mockResolvedValue(MATRIX_SUGGESTIONS);
    render(<SearchBar onSearch={onSearch} fetchSuggestions={fetchSuggestions} />);

    await userEvent.type(screen.getByRole("searchbox"), "matrix");
    await waitPastDebounce();

    await userEvent.click(screen.getByText("The Matrix Resurrections"));

    expect(onSearch).toHaveBeenCalledWith("The Matrix Resurrections");
    expect(screen.getByRole("searchbox")).toHaveValue("The Matrix Resurrections");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("navigates suggestions with the arrow keys and selects with Enter", async () => {
    const onSearch = vi.fn();
    const fetchSuggestions = vi.fn().mockResolvedValue(MATRIX_SUGGESTIONS);
    render(<SearchBar onSearch={onSearch} fetchSuggestions={fetchSuggestions} />);

    const input = screen.getByRole("searchbox");
    await userEvent.type(input, "matrix");
    await waitPastDebounce();

    await userEvent.keyboard("{ArrowDown}{ArrowDown}{Enter}");

    expect(onSearch).toHaveBeenCalledWith("The Matrix Resurrections");
  });

  it("closes the dropdown on Escape without submitting", async () => {
    const onSearch = vi.fn();
    const fetchSuggestions = vi.fn().mockResolvedValue(MATRIX_SUGGESTIONS);
    render(<SearchBar onSearch={onSearch} fetchSuggestions={fetchSuggestions} />);

    await userEvent.type(screen.getByRole("searchbox"), "matrix");
    await waitPastDebounce();
    expect(await screen.findByRole("listbox")).toBeInTheDocument();

    await userEvent.keyboard("{Escape}");

    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(onSearch).not.toHaveBeenCalled();
  });

  it("closes the dropdown when the user clicks outside the search bar", async () => {
    const fetchSuggestions = vi.fn().mockResolvedValue(MATRIX_SUGGESTIONS);
    render(
      <div>
        <SearchBar onSearch={vi.fn()} fetchSuggestions={fetchSuggestions} />
        <p>Outside content</p>
      </div>,
    );

    await userEvent.type(screen.getByRole("searchbox"), "matrix");
    await waitPastDebounce();
    expect(await screen.findByRole("listbox")).toBeInTheDocument();

    await userEvent.click(screen.getByText("Outside content"));

    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("does not reopen the dropdown right after a suggestion is selected", async () => {
    const fetchSuggestions = vi.fn().mockResolvedValue(MATRIX_SUGGESTIONS);
    render(<SearchBar onSearch={vi.fn()} fetchSuggestions={fetchSuggestions} />);

    await userEvent.type(screen.getByRole("searchbox"), "matrix");
    await waitPastDebounce();
    await userEvent.click(screen.getByText("The Matrix Resurrections"));

    // Selecting sets the input to a longer, still-qualifying query — give
    // a second debounce window a chance to fire before asserting it didn't.
    await waitPastDebounce();

    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(fetchSuggestions).toHaveBeenCalledTimes(1);
  });

  it("does not open the dropdown when a history entry restores the query", async () => {
    const fetchSuggestions = vi.fn().mockResolvedValue(MATRIX_SUGGESTIONS);
    const { rerender } = render(
      <SearchBar
        onSearch={vi.fn()}
        fetchSuggestions={fetchSuggestions}
        initialQuery=""
      />,
    );

    rerender(
      <SearchBar
        onSearch={vi.fn()}
        fetchSuggestions={fetchSuggestions}
        initialQuery="Breaking Bad"
      />,
    );
    await waitPastDebounce();

    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(fetchSuggestions).not.toHaveBeenCalled();
  });

  it("still supports a normal, non-autocomplete search when suggestions fail", async () => {
    const onSearch = vi.fn();
    const fetchSuggestions = vi.fn().mockRejectedValue(new Error("imdb down"));
    render(<SearchBar onSearch={onSearch} fetchSuggestions={fetchSuggestions} />);

    await userEvent.type(screen.getByRole("searchbox"), "the matrix");
    await waitPastDebounce();
    await userEvent.click(screen.getByRole("button", { name: /search/i }));

    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(onSearch).toHaveBeenCalledWith("the matrix");
  });
});
