CREATE TABLE IF NOT EXISTS searches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT NOT NULL,
    matched_title TEXT,
    source TEXT,
    score REAL,
    timestamp TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Real playback measurements reported by the viewer's own browser (the
-- userscript in clients/). This is the app's only source of genuine
-- playback evidence: the streaming sites gate their streams against
-- automated sessions, so nothing here can be collected server-side.
CREATE TABLE IF NOT EXISTS playback_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site TEXT NOT NULL,
    imdb_id TEXT,
    started INTEGER NOT NULL,
    startup_ms INTEGER,
    rebuffer_count INTEGER NOT NULL,
    rebuffer_ms INTEGER NOT NULL,
    observed_ms INTEGER NOT NULL,
    timestamp TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_playback_reports_site
    ON playback_reports (site, imdb_id, id DESC);
