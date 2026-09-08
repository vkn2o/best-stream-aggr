import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import HistorySidebar from "./HistorySidebar";

const HISTORY = [
  {
    id: 2,
    query: "breaking bad",
    matched_title: "Breaking Bad",
    source: "https://cinejoy.to/",
    score: 1.4,
    timestamp: "2026-09-07T16:40:46.101Z",
  },
  {
    id: 1,
    query: "matrix",
    matched_title: "The Matrix",
    source: "https://cinejoy.to/",
    score: 1.4,
    timestamp: "2026-09-07T16:39:12.000Z",
  },
];

describe("HistorySidebar", () => {
  it("lists past searches in the order the backend returned them", () => {
    render(<HistorySidebar history={HISTORY} onSelect={vi.fn()} />);

    const items = screen.getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("Breaking Bad");
    expect(items[1]).toHaveTextContent("The Matrix");
  });

  it("falls back to the raw query when no title was matched", () => {
    render(
      <HistorySidebar
        history={[{ ...HISTORY[0], matched_title: null }]}
        onSelect={vi.fn()}
      />,
    );

    expect(screen.getByRole("listitem")).toHaveTextContent("breaking bad");
  });

  it("hands the selected entry back when clicked", async () => {
    const onSelect = vi.fn();
    render(<HistorySidebar history={HISTORY} onSelect={onSelect} />);

    await userEvent.click(screen.getByRole("button", { name: /Breaking Bad/ }));

    expect(onSelect).toHaveBeenCalledWith(HISTORY[0]);
  });

  it("shows an empty state when there are no past searches", () => {
    render(<HistorySidebar history={[]} onSelect={vi.fn()} />);

    expect(screen.getByText(/no searches yet/i)).toBeInTheDocument();
  });
});
