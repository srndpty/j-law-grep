import { useEffect, useMemo, useState } from "react";

export const DEFAULT_QUERY = "民法 709条";
const STORAGE_KEY = "j-law-grep.settings.v1";

export interface SearchSettings {
  query: string;
  mode: string;
  source: string;
  filters: Record<string, string>;
}

const DIET_FILTER_KEYS = ["house", "meeting", "speaker", "date_from", "date_to"] as const;

const SOURCES = ["law", "diet", "all"] as const;
const MODES = ["auto", "literal", "keyword", "boolean", "citation", "regex"] as const;

export type SearchSource = (typeof SOURCES)[number];

// URL query and localStorage are user-controllable, so normalize unknown values
// to safe defaults instead of forwarding e.g. `?source=foo` to the API (which
// would 400) or leaving every source/mode tab inactive in the UI.
function normalizeSource(value: string | null | undefined): SearchSource {
  return SOURCES.includes(value as SearchSource) ? (value as SearchSource) : "law";
}

function normalizeMode(value: string | null | undefined): string {
  return MODES.includes(value as (typeof MODES)[number]) ? (value as string) : "auto";
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
    mode: normalizeMode(params.get("mode") ?? saved.mode),
    source: normalizeSource(params.get("source") ?? saved.source),
    filters: Object.fromEntries(
      DIET_FILTER_KEYS.map((key) => [key, params.get(key) ?? saved[key] ?? ""])
    ),
  };
}

export function useSearchSettings() {
  const initial = useMemo(() => loadInitialSettings(), []);
  const [query, setQuery] = useState(initial.query);
  const [mode, setMode] = useState<string>(initial.mode);
  const [source, setSource] = useState<string>(initial.source);
  const [filters, setFilters] = useState<Record<string, string>>(initial.filters);

  function setFilter(key: string, value: string) {
    setFilters((current) => ({ ...current, [key]: value }));
  }

  function clearDietFilters() {
    setFilters(Object.fromEntries(DIET_FILTER_KEYS.map((key) => [key, ""])));
  }

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ query, mode, source, ...filters }));
    const params = new URLSearchParams();
    if (query) params.set("q", query);
    if (mode !== "auto") params.set("mode", mode);
    if (source !== "law") params.set("source", source);
    if (source !== "law") {
      for (const key of DIET_FILTER_KEYS) {
        const value = filters[key];
        if (value) params.set(key, value);
      }
    }
    const next = params.toString() ? `?${params.toString()}` : window.location.pathname;
    window.history.replaceState(null, "", next);
  }, [filters, mode, query, source]);

  const requestBody = useMemo(
    () => ({
      q: query,
      mode,
      source,
      filters:
        source === "law"
          ? {}
          : Object.fromEntries(Object.entries(filters).filter(([, value]) => value)),
      size: 20,
      page: 1,
    }),
    [filters, mode, query, source]
  );

  return {
    query,
    setQuery,
    mode,
    setMode,
    source,
    setSource,
    filters,
    setFilter,
    clearDietFilters,
    requestBody,
  };
}
