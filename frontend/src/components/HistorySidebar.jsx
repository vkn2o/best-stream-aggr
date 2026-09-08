function formatTimestamp(timestamp) {
  const parsed = new Date(timestamp);
  return Number.isNaN(parsed.getTime()) ? "" : parsed.toLocaleString();
}

export default function HistorySidebar({ history, onSelect }) {
  return (
    <aside className="history">
      <h2 className="history__heading">Channel log</h2>
      <p className="history__subheading">Previously tuned searches</p>

      {history.length === 0 ? (
        <p className="history__empty">No searches yet.</p>
      ) : (
        <ul className="history__list">
          {history.map((entry, index) => (
            <li key={entry.id}>
              <button
                type="button"
                className="history__item"
                onClick={() => onSelect(entry)}
              >
                <span className="history__rec" aria-hidden="true">
                  {String(history.length - index).padStart(2, "0")}
                </span>
                <span className="history__body">
                  <span className="history__title">
                    {entry.matched_title || entry.query}
                  </span>
                  <span className="history__time">
                    {formatTimestamp(entry.timestamp)}
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
}
