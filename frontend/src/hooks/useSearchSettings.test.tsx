import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { DEFAULT_QUERY, useSearchSettings } from "./useSearchSettings";

describe("useSearchSettings", () => {
  beforeEach(() => {
    localStorage.clear();
    window.history.replaceState(null, "", "/");
  });

  it("uses defaults and builds a request body", () => {
    const { result } = renderHook(() => useSearchSettings());

    expect(result.current.query).toBe(DEFAULT_QUERY);
    expect(result.current.mode).toBe("auto");
    expect(result.current.requestBody).toEqual({
      q: DEFAULT_QUERY,
      mode: "auto",
      filters: {},
      size: 20,
      page: 1,
    });
  });

  it("prefers query string over saved settings and persists changes", () => {
    localStorage.setItem(
      "j-law-grep.settings.v1",
      JSON.stringify({ query: "保存済み", mode: "keyword" })
    );
    window.history.replaceState(null, "", "/?q=%E6%B0%91%E6%B3%95&mode=literal");

    const { result } = renderHook(() => useSearchSettings());

    expect(result.current.query).toBe("民法");
    expect(result.current.mode).toBe("literal");

    act(() => {
      result.current.setQuery("刑法");
      result.current.setMode("auto");
    });

    expect(JSON.parse(localStorage.getItem("j-law-grep.settings.v1") ?? "{}")).toEqual({
      query: "刑法",
      mode: "auto",
    });
    expect(window.location.search).toBe("?q=%E5%88%91%E6%B3%95");
  });

  it("ignores invalid saved settings json", () => {
    localStorage.setItem("j-law-grep.settings.v1", "{");

    const { result } = renderHook(() => useSearchSettings());

    expect(result.current.query).toBe(DEFAULT_QUERY);
    expect(result.current.mode).toBe("auto");
  });
});
