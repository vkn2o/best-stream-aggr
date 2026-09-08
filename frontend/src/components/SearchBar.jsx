import { useEffect, useRef, useState } from "react";

import * as api from "../api/client";

const DEBOUNCE_MS = 300;
const MIN_QUERY_LENGTH = 2;

const KIND_LABELS = {
  movie: "Movie",
  tvSeries: "TV Series",
  tvMiniSeries: "TV Mini-Series",
  tvMovie: "TV Movie",
  tvSpecial: "TV Special",
  video: "Video",
  short: "Short",
};

export default function SearchBar({
  onSearch,
  isSearching = false,
  initialQuery = "",
  fetchSuggestions = api.fetchSuggestions,
}) {
  const [query, setQuery] = useState(initialQuery);
  const [suggestions, setSuggestions] = useState([]);
  const [isOpen, setIsOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [brokenImages, setBrokenImages] = useState(() => new Set());
  const containerRef = useRef(null);
  const latestRequestId = useRef(0);
  // Set right before a *programmatic* change to `query` (restoring a
  // history entry, or filling in a picked suggestion) — as opposed to the
  // user typing. Both of those already represent a finished, chosen title,
  // so re-running the debounce for them would pop the dropdown back open
  // right after it was closed.
  const suppressNextFetch = useRef(false);

  // Keeps the box in sync when a history entry is restored into it.
  useEffect(() => {
    suppressNextFetch.current = true;
    setQuery(initialQuery);
  }, [initialQuery]);

  // Fetches suggestions 300ms after the user stops typing, rather than on
  // every keystroke — a request per keystroke would hammer the backend (and
  // in turn IMDb) for no benefit, since only the final, settled value is
  // ever shown.
  useEffect(() => {
    if (suppressNextFetch.current) {
      suppressNextFetch.current = false;
      setSuggestions([]);
      setIsOpen(false);
      return undefined;
    }

    const trimmed = query.trim();
    if (trimmed.length < MIN_QUERY_LENGTH) {
      setSuggestions([]);
      setIsOpen(false);
      return undefined;
    }

    const requestId = ++latestRequestId.current;
    const timer = setTimeout(async () => {
      let results;
      try {
        results = await fetchSuggestions(trimmed);
      } catch {
        results = [];
      }
      // A slower, earlier request landing after a faster, later one would
      // otherwise flash a stale list back onto the screen.
      if (requestId !== latestRequestId.current) return;
      setSuggestions(Array.isArray(results) ? results : []);
      setIsOpen(Array.isArray(results) && results.length > 0);
      setActiveIndex(-1);
    }, DEBOUNCE_MS);

    return () => clearTimeout(timer);
  }, [query, fetchSuggestions]);

  useEffect(() => {
    function handlePointerDown(event) {
      if (!containerRef.current?.contains(event.target)) {
        setIsOpen(false);
      }
    }
    document.addEventListener("mousedown", handlePointerDown);
    return () => document.removeEventListener("mousedown", handlePointerDown);
  }, []);

  function runSearch(value) {
    const trimmed = value.trim();
    if (!trimmed) return;
    setIsOpen(false);
    onSearch(trimmed);
  }

  function handleSubmit(event) {
    event.preventDefault();
    runSearch(query);
  }

  function selectSuggestion(suggestion) {
    suppressNextFetch.current = true;
    setQuery(suggestion.title);
    setSuggestions([]);
    runSearch(suggestion.title);
  }

  function handleKeyDown(event) {
    if (event.key === "Escape") {
      if (isOpen) {
        event.preventDefault();
        setIsOpen(false);
      }
      return;
    }

    if (!isOpen || suggestions.length === 0) return;

    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((index) => (index + 1) % suggestions.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((index) =>
        index <= 0 ? suggestions.length - 1 : index - 1,
      );
    } else if (event.key === "Enter" && activeIndex >= 0) {
      event.preventDefault();
      selectSuggestion(suggestions[activeIndex]);
    }
  }

  const showDropdown = isOpen && suggestions.length > 0;

  return (
    <div className="tuner" ref={containerRef}>
      <div
        className={`tuner__readout ${query.trim() ? "" : "tuner__readout--empty"}`}
        aria-hidden="true"
      >
        {query.trim() ? query.toUpperCase() : "NO SIGNAL — ENTER A TITLE"}
      </div>

      <form className="search-bar" onSubmit={handleSubmit} role="search">
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Search a movie or TV show…"
          aria-label="Search a movie or TV show"
          aria-expanded={showDropdown}
          aria-controls="search-suggestions"
          aria-autocomplete="list"
          aria-activedescendant={
            activeIndex >= 0 ? `suggestion-${activeIndex}` : undefined
          }
          autoComplete="off"
        />
        <button type="submit" disabled={isSearching}>
          {isSearching ? "Searching…" : "Search"}
        </button>
      </form>

      {showDropdown && (
        <ul className="suggestions" id="search-suggestions" role="listbox">
          {suggestions.map((suggestion, index) => (
            <li
              key={suggestion.imdb_id}
              id={`suggestion-${index}`}
              role="option"
              aria-selected={index === activeIndex}
            >
              <button
                type="button"
                className={`suggestions__item ${
                  index === activeIndex ? "suggestions__item--active" : ""
                }`}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => selectSuggestion(suggestion)}
              >
                {suggestion.image_url && !brokenImages.has(suggestion.imdb_id) ? (
                  <img
                    className="suggestions__poster"
                    src={suggestion.image_url}
                    alt=""
                    onError={() =>
                      setBrokenImages((previous) =>
                        new Set(previous).add(suggestion.imdb_id),
                      )
                    }
                  />
                ) : (
                  <span
                    className="suggestions__poster suggestions__poster--empty"
                    aria-hidden="true"
                  />
                )}
                <span className="suggestions__body">
                  <span className="suggestions__title">
                    {suggestion.title}
                  </span>
                  <span className="suggestions__meta">
                    {[
                      suggestion.year,
                      KIND_LABELS[suggestion.kind] || suggestion.kind,
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
