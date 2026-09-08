// Thin wrapper over the Flask API. Paths are relative so the Vite dev
// server's /api proxy (see vite.config.js) forwards them to Flask on :5000
// — same origin in the browser, so no CORS setup is needed.

async function parseOrThrow(response) {
  const body = await response.json().catch(() => ({}));

  if (!response.ok) {
    throw new Error(body.error || `Request failed (${response.status})`);
  }

  return body;
}

export async function search(query) {
  const response = await fetch("/api/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query }),
  });

  return parseOrThrow(response);
}

export async function fetchHistory() {
  return parseOrThrow(await fetch("/api/history"));
}

export async function fetchSuggestions(query) {
  const body = await parseOrThrow(
    await fetch(`/api/suggestions?q=${encodeURIComponent(query)}`),
  );

  // Defensive on the shape here too, same as the backend: an autocomplete
  // dropdown should never crash the page over an unexpected response body.
  return Array.isArray(body.suggestions) ? body.suggestions : [];
}
