import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SearchHit, SearchRequest, SearchResponse } from "./api/search";

const mocks = vi.hoisted(() => ({
  search: vi.fn(),
  setQuery: vi.fn(),
  setMode: vi.fn(),
  setSource: vi.fn(),
  setFilter: vi.fn(),
  clearDietFilters: vi.fn(),
  openLawDocument: vi.fn(),
}));

vi.mock("./hooks/useSearchSettings", () => ({
  useSearchSettings: () => ({
    query: "民法",
    setQuery: mocks.setQuery,
    mode: "literal",
    setMode: mocks.setMode,
    source: "law",
    setSource: mocks.setSource,
    filters: {},
    setFilter: mocks.setFilter,
    clearDietFilters: mocks.clearDietFilters,
    requestBody: {
      q: "民法",
      mode: "literal",
      source: "law",
      filters: {},
      size: 20,
      page: 1,
    } satisfies SearchRequest,
  }),
}));

let searchState: {
  results: SearchResponse;
  isLoading: boolean;
  error: string | null;
  requestId: string | null;
};

vi.mock("./hooks/useSearch", () => ({
  useSearch: () => ({
    ...searchState,
    search: mocks.search,
  }),
}));

vi.mock("./search-hit-text", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./search-hit-text")>();
  return {
    ...actual,
    openLawDocument: mocks.openLawDocument,
  };
});

import App from "./App";

const hit: SearchHit = {
  file_id: "1",
  law_id: "minpo",
  law_name: "民法",
  article_no: "709",
  paragraph_no: "1",
  item_no: null,
  path: "民法/709",
  line: 1,
  snippet: "故意又は過失",
  snippet_text: "故意又は過失",
  highlights: [],
  url: "/laws/minpo?article=709",
  blocks: [],
};

const originalScrollIntoView = Object.getOwnPropertyDescriptor(Element.prototype, "scrollIntoView");

describe("App", () => {
  beforeEach(() => {
    mocks.search.mockReset();
    mocks.setQuery.mockReset();
    mocks.setMode.mockReset();
    mocks.setSource.mockReset();
    mocks.setFilter.mockReset();
    mocks.clearDietFilters.mockReset();
    mocks.openLawDocument.mockReset();
    Object.defineProperty(Element.prototype, "scrollIntoView", {
      configurable: true,
      value: vi.fn(),
    });
    searchState = {
      results: {
        hits: [hit, { ...hit, file_id: "2", article_no: "710" }],
        total: 2,
        took_ms: 8,
        query: {
          raw: "民法",
          mode: "auto",
          effective_mode: "literal",
          parsed: {},
        },
        index: { name: "laws" },
      },
      isLoading: false,
      error: null,
      requestId: null,
    };
  });

  afterEach(() => {
    if (originalScrollIntoView) {
      Object.defineProperty(Element.prototype, "scrollIntoView", originalScrollIntoView);
    } else {
      Reflect.deleteProperty(Element.prototype, "scrollIntoView");
    }
  });

  it("submits search, changes mode, and navigates results with keyboard", async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole("button", { name: "キーワード" }));
    expect(mocks.setMode).toHaveBeenCalledWith("keyword");

    await user.click(screen.getByRole("button", { name: "検索" }));
    expect(mocks.search).toHaveBeenCalled();

    fireEvent.keyDown(window, { key: "ArrowDown" });
    fireEvent.keyDown(window, { key: "Enter" });
    expect(mocks.openLawDocument).toHaveBeenCalledWith(expect.objectContaining({ file_id: "2" }));
  });

  it("shows loading and error request id", () => {
    searchState = {
      ...searchState,
      isLoading: true,
      error: "検索に失敗しました",
      requestId: "req-1",
    };

    render(<App />);

    expect(screen.getByText("検索に失敗しました")).toBeInTheDocument();
    expect(screen.getByText("(request_id: req-1)")).toBeInTheDocument();
    expect(screen.getByText(/mode auto -> literal/)).toBeInTheDocument();
  });
});
