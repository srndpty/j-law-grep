import { useEffect, useMemo, useState } from "react";

export const DEFAULT_QUERY = "民法 709条";
const STORAGE_KEY = "j-law-grep.settings.v1";

export interface SearchSettings {
  query: string;
  mode: string;
  source: string;
  filters: Record<string, string>;
}

// 法令以外のソースが使うフィルタキーの和集合。API 側は source ごとに許可キーを
// 検証するので、送信前に source に応じて絞り込む (requestBody を参照)。
const DIET_FILTER_KEYS = ["house", "meeting", "speaker", "date_from", "date_to"] as const;
const SHUISHO_FILTER_KEYS = [
  "house",
  "session",
  "speaker",
  "date_from",
  "date_to",
  "shuisho_kind",
] as const;
const FILTER_KEYS = [...new Set<string>([...DIET_FILTER_KEYS, ...SHUISHO_FILTER_KEYS])];

const SOURCES = ["law", "diet", "shuisho", "all"] as const;
const MODES = ["auto", "literal", "keyword", "boolean", "citation", "regex"] as const;

export type SearchSource = (typeof SOURCES)[number];

// URL query and localStorage are user-controllable, so normalize unknown values
// to safe defaults instead of forwarding e.g. `?source=foo` to the API (which
// would 400) or leaving every source/mode tab inactive in the UI.
function normalizeSource(value: string | null | undefined): SearchSource {
  return SOURCES.includes(value as SearchSource) ? (value as SearchSource) : "law";
}

// The API rejects filter keys that do not belong to the selected source, so a
// leftover `session` from the 質問主意書 tab must not ride along on a 国会 search.
function allowedFilterKeys(source: string): readonly string[] {
  if (source === "law") return [];
  if (source === "diet") return DIET_FILTER_KEYS;
  if (source === "shuisho") return SHUISHO_FILTER_KEYS;
  return FILTER_KEYS;
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
      FILTER_KEYS.map((key) => [key, params.get(key) ?? saved[key] ?? ""])
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
    setFilters(Object.fromEntries(FILTER_KEYS.map((key) => [key, ""])));
  }

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ query, mode, source, ...filters }));
    const params = new URLSearchParams();
    if (query) params.set("q", query);
    if (mode !== "auto") params.set("mode", mode);
    if (source !== "law") params.set("source", source);
    for (const key of allowedFilterKeys(source)) {
      const value = filters[key];
      if (value) params.set(key, value);
    }
    const next = params.toString() ? `?${params.toString()}` : window.location.pathname;
    window.history.replaceState(null, "", next);
  }, [filters, mode, query, source]);

  const requestBody = useMemo(
    () => ({
      q: query,
      mode,
      source,
      filters: Object.fromEntries(
        allowedFilterKeys(source)
          .filter((key) => filters[key])
          .map((key) => [key, filters[key]])
      ),
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
