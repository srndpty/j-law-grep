import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useSearch } from "./useSearch";
import type { SearchRequest } from "../api/search";

vi.mock("../api/search", () => ({
  postSearch: vi.fn(),
}));

import { postSearch } from "../api/search";

const mockedPostSearch = vi.mocked(postSearch);

const requestBody: SearchRequest = {
  q: "民法",
  mode: "literal",
  filters: {},
  size: 20,
  page: 1,
};

describe("useSearch", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mockedPostSearch.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("auto searches after debounce and stores results", async () => {
    mockedPostSearch.mockResolvedValue({
      data: {
        hits: [],
        total: 1,
        took_ms: 4,
        query: { raw: "民法", mode: "literal", effective_mode: "literal", parsed: {} },
      },
      requestId: "req-1",
    });
    const { result } = renderHook(() =>
      useSearch({ requestBody, query: "民法", mode: "literal", isComposing: false })
    );

    act(() => {
      vi.advanceTimersByTime(250);
    });
    await act(async () => {
      await Promise.resolve();
    });

    expect(result.current.results.total).toBe(1);
    expect(result.current.requestId).toBe("req-1");
    expect(result.current.isLoading).toBe(false);
  });

  it("manual search clears results for blank query", async () => {
    const { result } = renderHook(() =>
      useSearch({
        requestBody: { ...requestBody, q: " " },
        query: " ",
        mode: "literal",
        isComposing: false,
      })
    );

    await act(async () => {
      await result.current.search();
    });

    expect(mockedPostSearch).not.toHaveBeenCalled();
    expect(result.current.results.total).toBe(0);
    expect(result.current.error).toBeNull();
  });

  it("surfaces request id from failed search", async () => {
    const error = Object.assign(new Error("bad request"), { requestId: "req-error" });
    mockedPostSearch.mockRejectedValue(error);
    const { result } = renderHook(() =>
      useSearch({ requestBody, query: "", mode: "literal", isComposing: false })
    );

    await act(async () => {
      await result.current.search();
    });

    expect(result.current.error).toBe("bad request");
    expect(result.current.requestId).toBe("req-error");
    expect(result.current.isLoading).toBe(false);
  });

  it("does not set error for abort exceptions", async () => {
    mockedPostSearch.mockRejectedValue(new DOMException("aborted", "AbortError"));
    const { result } = renderHook(() =>
      useSearch({ requestBody, query: "", mode: "literal", isComposing: false })
    );

    await act(async () => {
      await result.current.search();
    });

    expect(result.current.error).toBeNull();
  });

  it("does not auto search while composing", () => {
    renderHook(() => useSearch({ requestBody, query: "民法", mode: "literal", isComposing: true }));

    act(() => {
      vi.advanceTimersByTime(300);
    });

    expect(mockedPostSearch).not.toHaveBeenCalled();
  });
});
