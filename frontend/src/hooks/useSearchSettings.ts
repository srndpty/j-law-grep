import { useEffect, useMemo, useState } from "react";

export const DEFAULT_QUERY = "民法 709条";
const STORAGE_KEY = "j-law-grep.settings.v1";

export interface SearchSettings {
  query: string;
  mode: string;
  yearFilter: string;
}

function loadInitialSettings(): SearchSettings {
  const params = new URLSearchParams(window.location.search);
  const saved = (() => {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}") as Record<string, string>;
    } catch {
      return {};
    }
  })();
  return {
    query: params.get("q") ?? saved.query ?? DEFAULT_QUERY,
    mode: params.get("mode") ?? saved.mode ?? "auto",
    yearFilter: params.get("year") ?? saved.yearFilter ?? "",
  };
}

export function useSearchSettings() {
  const initial = useMemo(() => loadInitialSettings(), []);
  const [query, setQuery] = useState(initial.query);
  const [mode, setMode] = useState<string>(initial.mode);
  const [yearFilter, setYearFilter] = useState(initial.yearFilter);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ query, mode, yearFilter }));
    const params = new URLSearchParams();
    if (query) params.set("q", query);
    if (mode !== "auto") params.set("mode", mode);
    if (yearFilter) params.set("year", yearFilter);
    const next = params.toString() ? `?${params.toString()}` : window.location.pathname;
    window.history.replaceState(null, "", next);
  }, [mode, query, yearFilter]);

  const requestBody = useMemo(
    () => ({
      q: query,
      mode,
      filters: {
        ...(yearFilter ? { year: yearFilter } : {}),
      },
      size: 20,
      page: 1,
    }),
    [mode, query, yearFilter]
  );

  return {
    query,
    setQuery,
    mode,
    setMode,
    yearFilter,
    setYearFilter,
    requestBody,
  };
}
