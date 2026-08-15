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
    expect(result.current.source).toBe("law");
    expect(result.current.requestBody).toEqual({
      q: DEFAULT_QUERY,
      mode: "auto",
      source: "law",
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
      source: "law",
      house: "",
      meeting: "",
      speaker: "",
      date_from: "",
      date_to: "",
      session: "",
      shuisho_kind: "",
    });
    expect(window.location.search).toBe("?q=%E5%88%91%E6%B3%95");
  });

  it("persists non-default source in the query string", () => {
    window.history.replaceState(null, "", "/?q=diet&source=diet");

    const { result } = renderHook(() => useSearchSettings());

    expect(result.current.source).toBe("diet");

    act(() => {
      result.current.setSource("all");
    });

    expect(result.current.requestBody.source).toBe("all");
    expect(window.location.search).toBe("?q=diet&source=all");
  });

  it("includes diet filters only for non-law sources", () => {
    window.history.replaceState(
      null,
      "",
      "/?q=diet&source=diet&house=%E8%A1%86%E8%AD%B0%E9%99%A2&speaker=%E5%B1%B1%E7%94%B0&date_from=2025-06-09"
    );

    const { result } = renderHook(() => useSearchSettings());

    expect(result.current.requestBody.filters).toEqual({
      house: "衆議院",
      speaker: "山田",
      date_from: "2025-06-09",
    });

    act(() => {
      result.current.setSource("law");
    });

    expect(result.current.requestBody.filters).toEqual({});
  });

  it("sends only the filters the selected source accepts", () => {
    window.history.replaceState(
      null,
      "",
      "/?q=%E9%96%A3%E8%AD%B0&source=shuisho&session=217&shuisho_kind=answer&meeting=%E4%BA%88%E7%AE%97"
    );

    const { result } = renderHook(() => useSearchSettings());

    expect(result.current.source).toBe("shuisho");
    // 会議名は国会だけのキーなので質問主意書検索には載せない (API が 400 を返す)。
    expect(result.current.requestBody.filters).toEqual({
      session: "217",
      shuisho_kind: "answer",
    });

    act(() => {
      result.current.setSource("diet");
    });

    expect(result.current.requestBody.filters).toEqual({ meeting: "予算" });
  });

  it("normalizes an invalid source from the query string to law", () => {
    window.history.replaceState(null, "", "/?q=diet&source=foo");

    const { result } = renderHook(() => useSearchSettings());

    expect(result.current.source).toBe("law");
    expect(result.current.requestBody.source).toBe("law");
  });

  it("normalizes an invalid mode from the query string to auto", () => {
    window.history.replaceState(null, "", "/?q=diet&mode=bogus");

    const { result } = renderHook(() => useSearchSettings());

    expect(result.current.mode).toBe("auto");
  });

  it("ignores invalid saved settings json", () => {
    localStorage.setItem("j-law-grep.settings.v1", "{");

    const { result } = renderHook(() => useSearchSettings());

    expect(result.current.query).toBe(DEFAULT_QUERY);
    expect(result.current.mode).toBe("auto");
  });
});
