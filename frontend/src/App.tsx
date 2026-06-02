import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { ExternalLink, Loader2, Search as SearchIcon } from "lucide-react";
import { clsx } from "clsx";
import { Button } from "./components/ui/button";

interface SearchHit {
  file_id: string;
  law_name: string;
  article_no: string;
  paragraph_no: number | string | null;
  item_no: number | string | null;
  path: string;
  line: number;
  snippet: string;
  snippet_text?: string;
  highlights?: HighlightRange[];
  url: string;
  blocks: Array<Record<string, unknown>>;
}

interface HighlightRange {
  start: number;
  end: number;
}

interface SearchResponse {
  hits: SearchHit[];
  total: number;
  took_ms: number;
  query?: {
    raw: string;
    mode: string;
    effective_mode: string;
    parsed: Record<string, string | number | null>;
  };
  index?: {
    name: string;
  };
}

const MODES = [
  { value: "auto", label: "自動" },
  { value: "literal", label: "リテラル" },
  { value: "boolean", label: "Boolean" },
  { value: "citation", label: "引用" },
  { value: "regex", label: "正規表現" },
];

const DEFAULT_QUERY = "民法 709条";
const STORAGE_KEY = "j-law-grep.settings.v1";

function loadInitialSettings() {
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
    lawFilter: params.get("law") ?? saved.lawFilter ?? "",
    yearFilter: params.get("year") ?? saved.yearFilter ?? "",
  };
}

export default function App() {
  const initialSettings = useMemo(() => loadInitialSettings(), []);
  const [query, setQuery] = useState(initialSettings.query);
  const [mode, setMode] = useState<string>(initialSettings.mode);
  const [lawFilter, setLawFilter] = useState(initialSettings.lawFilter);
  const [yearFilter, setYearFilter] = useState(initialSettings.yearFilter);
  const [isLoading, setIsLoading] = useState(false);
  const [isComposing, setIsComposing] = useState(false);
  const [results, setResults] = useState<SearchResponse>({ hits: [], total: 0, took_ms: 0 });
  const [error, setError] = useState<string | null>(null);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [showDebug, setShowDebug] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const requestSeqRef = useRef(0);
  const resultRefs = useRef<Array<HTMLElement | null>>([]);

  const deriveArticleNo = (hit: SearchHit) => {
    if (hit.article_no) return hit.article_no;
    const urlMatch = hit.url.match(/\/a\/([^/]+)/);
    if (urlMatch) return urlMatch[1];
    const parts = hit.path.split("/");
    if (parts.length >= 2 && parts[1]) return parts[1];
    return "";
  };

  const deriveParagraphNo = (hit: SearchHit) => {
    if (hit.paragraph_no !== null && hit.paragraph_no !== undefined) return hit.paragraph_no;
    const match = hit.url.match(/\/a\/[^/]+\/(\d+)/);
    if (match) {
      const value = Number(match[1]);
      return Number.isNaN(value) ? null : value;
    }
    return null;
  };

  const formatArticlePosition = (hit: SearchHit) => {
    const segments: string[] = [];
    const articleNo = deriveArticleNo(hit);
    const paragraphNo = deriveParagraphNo(hit);
    if (articleNo) {
      const articleLabel = articleNo.includes("条") ? articleNo : `第${articleNo}条`;
      segments.push(articleLabel);
    }
    if (paragraphNo) {
      segments.push(`${paragraphNo}項`);
    }
    if (hit.item_no) {
      segments.push(`${hit.item_no}号`);
    }
    return segments.join(" ");
  };

  const formatLocation = (hit: SearchHit) => {
    const base = hit.law_name || hit.path;
    const position = formatArticlePosition(hit);
    if (base && position) return `${base} / ${position}`;
    return base || position || hit.path;
  };

  const requestBody = useMemo(
    () => ({
      q: query,
      mode,
      filters: {
        ...(lawFilter ? { law: lawFilter } : {}),
        ...(yearFilter ? { year: yearFilter } : {}),
      },
      size: 20,
      page: 1,
    }),
    [lawFilter, mode, query, yearFilter]
  );

  useEffect(() => {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ query, mode, lawFilter, yearFilter })
    );
    const params = new URLSearchParams();
    if (query) params.set("q", query);
    if (mode !== "auto") params.set("mode", mode);
    if (lawFilter) params.set("law", lawFilter);
    if (yearFilter) params.set("year", yearFilter);
    const next = params.toString() ? `?${params.toString()}` : window.location.pathname;
    window.history.replaceState(null, "", next);
  }, [lawFilter, mode, query, yearFilter]);

  async function performSearch(body = requestBody) {
    if (!body.q.trim()) {
      abortRef.current?.abort();
      setResults({ hits: [], total: 0, took_ms: 0 });
      setError(null);
      setIsLoading(false);
      return;
    }
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const requestSeq = requestSeqRef.current + 1;
    requestSeqRef.current = requestSeq;
    setIsLoading(true);
    setError(null);
    try {
      const response = await fetch("/api/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: controller.signal,
      });
      if (!response.ok) {
        throw new Error(`検索に失敗しました (${response.status})`);
      }
      const data = (await response.json()) as SearchResponse;
      if (requestSeqRef.current === requestSeq) {
        setResults(data);
        setSelectedIndex(0);
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        return;
      }
      setError(err instanceof Error ? err.message : "検索に失敗しました");
    } finally {
      if (requestSeqRef.current === requestSeq) {
        setIsLoading(false);
      }
    }
  }

  useEffect(() => {
    if (isComposing || mode === "regex") {
      return;
    }
    if (query.trim().length < 2) {
      abortRef.current?.abort();
      setResults({ hits: [], total: 0, took_ms: 0 });
      setIsLoading(false);
      return;
    }
    const handle = setTimeout(() => {
      void performSearch(requestBody);
    }, 250);
    return () => clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isComposing, mode, query, requestBody]);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setSelectedIndex((current) => Math.min(current + 1, Math.max(results.hits.length - 1, 0)));
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        setSelectedIndex((current) => Math.max(current - 1, 0));
      }
      if (event.key === "Enter" && document.activeElement?.tagName !== "INPUT") {
        const selected = results.hits[selectedIndex];
        if (selected?.url) {
          window.location.href = selected.url;
        }
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [results.hits, selectedIndex]);

  useEffect(() => {
    resultRefs.current[selectedIndex]?.scrollIntoView({ block: "nearest" });
  }, [selectedIndex]);

  function renderSnippet(hit: SearchHit) {
    const text = hit.snippet_text ?? hit.snippet;
    const highlights = (hit.highlights ?? [])
      .filter((range) => range.start >= 0 && range.end > range.start && range.end <= text.length)
      .sort((a, b) => a.start - b.start);
    if (!highlights.length) return text;

    const nodes: JSX.Element[] = [];
    let cursor = 0;
    highlights.forEach((range, index) => {
      if (range.start > cursor) {
        nodes.push(<Fragment key={`text-${index}`}>{text.slice(cursor, range.start)}</Fragment>);
      }
      nodes.push(<mark key={`mark-${index}`}>{text.slice(range.start, range.end)}</mark>);
      cursor = range.end;
    });
    if (cursor < text.length) {
      nodes.push(<Fragment key="tail">{text.slice(cursor)}</Fragment>);
    }
    return nodes;
  }

  return (
    <div className="min-h-screen bg-muted text-foreground">
      <header className="border-b border-gray-800 bg-[#111418]">
        <div className="mx-auto flex max-w-7xl items-center gap-4 px-6 py-3">
          <span className="text-xl font-semibold text-white">j-law-grep</span>
          <div className="flex flex-1 items-center gap-2">
            <form
              className="flex w-full items-center gap-2"
              onSubmit={(event) => {
                event.preventDefault();
                void performSearch();
              }}
            >
              <div className="relative flex-1">
                <SearchIcon className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-500" />
                <input
                  className="w-full rounded-md border border-gray-700 bg-[#151a20] py-2 pl-9 pr-3 text-sm text-white shadow-sm focus:border-blue-500 focus:outline-none"
                  placeholder="キーワードや法令条番号を入力"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  onCompositionStart={() => setIsComposing(true)}
                  onCompositionEnd={(event) => {
                    setIsComposing(false);
                    setQuery(event.currentTarget.value);
                  }}
                />
              </div>
              <select
                className="rounded-md border border-gray-700 bg-[#151a20] px-3 py-2 text-sm text-white shadow-sm"
                value={lawFilter}
                onChange={(event) => setLawFilter(event.target.value)}
              >
                <option value="">すべての法令</option>
                <option value="民法">民法</option>
              </select>
              <input
                className="w-24 rounded-md border border-gray-700 bg-[#151a20] px-2 py-2 text-sm text-white shadow-sm"
                placeholder="施行年"
                value={yearFilter}
                onChange={(event) => setYearFilter(event.target.value)}
              />
              <div className="flex rounded-md border border-gray-700 bg-[#151a20] p-0.5 shadow-sm">
                {MODES.map((item) => (
                  <button
                    key={item.value}
                    type="button"
                    onClick={() => setMode(item.value)}
                    className={clsx(
                      "rounded px-2.5 py-1 text-sm font-medium transition",
                      mode === item.value
                        ? "bg-blue-600 text-white"
                        : "text-gray-300 hover:bg-gray-800"
                    )}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
              <Button type="submit">検索</Button>
            </form>
          </div>
        </div>
      </header>

      <main className="mx-auto grid max-w-7xl grid-cols-1 gap-6 px-6 py-6 md:grid-cols-[260px_1fr]">
        <aside className="space-y-4">
          <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
            <h2 className="text-sm font-semibold text-gray-700">検索設定</h2>
            <dl className="mt-3 space-y-2 text-xs text-gray-600">
              <div className="flex justify-between gap-3">
                <dt>mode</dt>
                <dd className="font-mono">{results.query?.effective_mode ?? mode}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt>index</dt>
                <dd className="truncate font-mono" title={results.index?.name}>{results.index?.name ?? "-"}</dd>
              </div>
            </dl>
            <button
              type="button"
              className="mt-3 rounded border border-gray-300 px-2 py-1 text-xs text-gray-700 hover:bg-gray-100"
              onClick={() => setShowDebug((value) => !value)}
            >
              Debug
            </button>
          </div>
          <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
            <h2 className="text-sm font-semibold text-gray-700">施行年</h2>
            <p className="mt-2 text-xs text-gray-500">空欄で全ての年を対象にします。</p>
          </div>
        </aside>
        <section className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-base font-semibold">検索結果 {results.total} 件</h2>
              <p className="text-xs text-gray-500">処理時間 {results.took_ms} ms</p>
            </div>
            {isLoading && <Loader2 className="h-5 w-5 animate-spin text-gray-500" />}
          </div>
          {error && <p className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-700">{error}</p>}
          {showDebug && (
            <pre className="max-h-64 overflow-auto rounded-md border border-gray-300 bg-white p-3 text-xs text-gray-700">
              {JSON.stringify({ request: requestBody, query: results.query, index: results.index }, null, 2)}
            </pre>
          )}
          <div className="space-y-3">
            {results.hits.map((hit, index) => (
              <article
                key={hit.file_id}
                ref={(element) => {
                  resultRefs.current[index] = element;
                }}
                onClick={() => setSelectedIndex(index)}
                className={clsx(
                  "rounded-lg border bg-white p-4 shadow-sm",
                  selectedIndex === index ? "border-blue-500 ring-1 ring-blue-500" : "border-gray-200"
                )}
              >
                <div className="text-xs uppercase tracking-wide text-gray-500">{formatLocation(hit)}</div>
                <div className="mt-2 text-sm leading-relaxed text-gray-900">{renderSnippet(hit)}</div>
                {hit.url && (
                  <a href={hit.url} className="mt-3 inline-flex items-center gap-1 text-sm text-blue-600 hover:underline">
                    パーマリンク
                    <ExternalLink className="h-3.5 w-3.5" />
                  </a>
                )}
              </article>
            ))}
            {!results.hits.length && !isLoading && (
              <div className="rounded-lg border border-gray-200 bg-white p-6 text-center text-sm text-gray-500">
                検索結果がありません。
              </div>
            )}
          </div>
        </section>
      </main>
    </div>
  );
}
