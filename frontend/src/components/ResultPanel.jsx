const SECONDS = (ms) => `${(ms / 1000).toFixed(1)}s`;

// Describes what was actually checked on a site. Every branch below is
// either a measurement or an explicit admission that there wasn't one —
// nothing here may make an unmeasured source read like a good one.
function availabilityEvidence(source) {
  if (source.availability === "available") {
    const count = source.result_count;
    return {
      tone: "good",
      text:
        typeof count === "number"
          ? `Has the title · ${count} results`
          : "Has the title",
    };
  }
  if (source.availability === "unavailable") {
    return { tone: "bad", text: "Not on this site" };
  }
  return { tone: "muted", text: "Availability not measured" };
}

// How precisely this link points at the searched title. Falls back to the
// old top-vs-direct distinction for responses that predate `link_kind`.
function linkLabel(source, isDirect) {
  if (source.link_kind === "title") {
    return { text: "Opens the player", modifier: "signal-pill--player" };
  }
  if (source.link_kind === "search") {
    return { text: "Direct link", modifier: "signal-pill--direct" };
  }
  if (source.link_kind === "home") {
    return { text: "Home page only", modifier: "" };
  }
  return isDirect
    ? { text: "Direct link", modifier: "signal-pill--direct" }
    : { text: "Home page only", modifier: "" };
}

// Says who measured this and what it describes. Site-wide evidence is
// labelled as such: it is useful, but it is not about this title, and
// showing it as if it were would be exactly the overclaim this app avoids.
function playbackSource(playback) {
  if (playback.provenance !== "reported") return "";
  const n = playback.sample_size;
  if (typeof n !== "number") return "";
  return playback.scope === "site"
    ? ` (site-wide, ${n} ${n === 1 ? "session" : "sessions"})`
    : ` (${n} of your sessions)`;
}

function playbackEvidence(playback) {
  if (!playback || playback.status !== "measured") {
    return { tone: "muted", text: "Playback not measured" };
  }
  if (!playback.started) {
    return { tone: "bad", text: "Playback did not start" };
  }

  const start =
    typeof playback.startup_ms === "number"
      ? `Played in ${SECONDS(playback.startup_ms)}`
      : "Played";
  // Either field being non-zero means the stream stalled. Gating on the
  // count alone let a reported average round to 0 while the buffering time
  // stayed non-zero, and the card then claimed "no rebuffering".
  const stalled = playback.rebuffer_count > 0 || playback.rebuffer_ms > 0;
  const buffering = stalled
    ? `${playback.rebuffer_count} rebuffer${
        playback.rebuffer_count === 1 ? "" : "s"
      } · ${SECONDS(playback.rebuffer_ms)} buffering`
    : "no rebuffering";

  return {
    tone: stalled ? "warn" : "good",
    text: `${start} · ${buffering}${playbackSource(playback)}`,
  };
}

function SourceCard({ source, kind }) {
  const isDirect = kind === "direct";
  const availability = availabilityEvidence(source);
  const playback = playbackEvidence(source.playback);
  const link = linkLabel(source, isDirect);

  return (
    <div className={`source-card ${isDirect ? "source-card--direct" : ""}`}>
      <div className="source-card__channel" aria-hidden="true">
        {String(source.rank).padStart(2, "0")}
      </div>

      <div className="source-card__body">
        <div className="source-card__top-row">
          <span className="source-card__label">
            {isDirect ? "Opens on this title" : "Top ranked source"}
          </span>
          <span className={`signal-pill ${link.modifier}`}>{link.text}</span>
        </div>

        <a
          className="source-card__link"
          href={source.url}
          target="_blank"
          rel="noopener noreferrer"
        >
          {source.site_name}
          {source.starred ? " ★" : ""}
        </a>

        <div className="source-card__meta">
          FMHY rank {source.rank} · score {source.total_score.toFixed(2)} ·{" "}
          <span title="Subtitle tracks live inside each site's player, which we can't read without a browser.">
            subtitles: {source.subtitle_status}
          </span>
        </div>

        {/* Deliberately not a <ul>: these are status labels, not a list.
            Using list markup added stray listitem roles to the page. */}
        <div className="evidence">
          <span className={`evidence__item evidence__item--${availability.tone}`}>
            {availability.text}
          </span>
          <span className={`evidence__item evidence__item--${playback.tone}`}>
            {playback.text}
          </span>
        </div>

        <p className="source-card__note">
          {source.link_kind === "title"
            ? "This link opens the title's player on the site."
            : isDirect
              ? "This link opens the site's search results for the title."
              : "This is the site's home page — search there yourself once it loads."}
        </p>
      </div>
    </div>
  );
}

export default function ResultPanel({ result, error }) {
  if (error) {
    return (
      <section className="result-panel">
        <p className="error" role="alert">
          <span className="error__label">Signal lost</span>
          {error}
        </p>
      </section>
    );
  }

  if (!result) {
    return null;
  }

  const { matched_title: matchedTitle, year, top_source: top, best_deep_link: direct } =
    result;

  return (
    <section className="result-panel">
      <header className="result-panel__header">
        {matchedTitle ? (
          <h2>
            {matchedTitle} {year ? <span className="year">({year})</span> : null}
          </h2>
        ) : (
          <h2 className="unmatched">
            We couldn&apos;t identify that title — showing sources anyway
          </h2>
        )}
      </header>

      <div className="source-list">
        <SourceCard source={top} kind="top" />

        {direct ? (
          <SourceCard source={direct} kind="direct" />
        ) : (
          <p className="source-card__note">
            No site could be opened directly on this title — only home-page
            links are available.
          </p>
        )}
      </div>
    </section>
  );
}
