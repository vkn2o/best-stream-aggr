import { useCallback, useEffect, useState } from "react";

import * as api from "./api/client";
import HistorySidebar from "./components/HistorySidebar";
import ResultPanel from "./components/ResultPanel";
import SearchBar from "./components/SearchBar";

export default function App() {
  const [history, setHistory] = useState([]);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [isSearching, setIsSearching] = useState(false);
  const [query, setQuery] = useState("");

  useEffect(() => {
    api
      .fetchHistory()
      .then(setHistory)
      .catch((loadError) => setError(loadError.message));
  }, []);

  const runSearch = useCallback(async (nextQuery) => {
    setQuery(nextQuery);
    setIsSearching(true);
    setError(null);

    try {
      const response = await api.search(nextQuery);
      setResult(response);
      // The search response already carries the updated history, so there's
      // no second round-trip to /api/history here.
      setHistory(response.history);
    } catch (searchError) {
      setResult(null);
      setError(searchError.message);
    } finally {
      setIsSearching(false);
    }
  }, []);

  // Stable identity so HistorySidebar's onSelect prop doesn't change every
  // render — a plain inline arrow here would defeat React.memo if the
  // sidebar is ever memoized later.
  const handleHistorySelect = useCallback(
    (entry) => runSearch(entry.query),
    [runSearch],
  );

  return (
    <div className="layout">
      <HistorySidebar history={history} onSelect={handleHistorySelect} />

      <main className="main">
        <header className="masthead">
          <h1>
            Stream <span className="brand-mark">Finder</span>
          </h1>
          <span
            className={`status-light ${isSearching ? "status-light--live" : ""}`}
          >
            <span className="status-light__dot" aria-hidden="true" />
            {isSearching ? "Tuning in" : "Standing by"}
          </span>
        </header>
        <p className="tagline">
          Finds the best streaming sites for a title, ranked from FMHY&apos;s
          curated directory.
        </p>

        <SearchBar onSearch={runSearch} isSearching={isSearching} initialQuery={query} />

        <ResultPanel result={result} error={error} />
      </main>
    </div>
  );
}
