import { useEffect, useMemo, useState } from "react";
import { Loader2, Search as SearchIcon } from "lucide-react";
import { clsx } from "clsx";
import { Button } from "./components/ui/button";

interface SearchHit {
  file_id: string;
  path: string;
  line: number;
  snippet: string;
  url: string;
  blocks: Array<Record<string, unknown>>;
}

interface SearchResponse {
  hits: SearchHit[];
  total: number;
  took_ms: number;
}

const MODES = [
  { value: "literal", label: "リテラル" },
  { value: "regex", label: "正規表現" },
];

const DEFAULT_QUERY = "民法 709条";

export default function App() {
  const [query, setQuery] = useState(DEFAULT_QUERY);
  const [mode, setMode] = useState<string>("literal");
  const [lawFilter, setLawFilter] = useState("民法");
  const [yearFilter, setYearFilter] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [results, setResults] = useState<SearchResponse>({ hits: [], total: 0, took_ms: 0 });
  const [error, setError] = useState<string | null>(null);

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

  async function performSearch(body = requestBody) {
    setIsLoading(true);
    setError(null);
    try {
      const response = await fetch("/api/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!response.ok) {
        throw new Error(`検索に失敗しました (${response.status})`);
      }
      const data = (await response.json()) as SearchResponse;
      setResults(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "検索に失敗しました");
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    void performSearch(requestBody);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="min-h-screen bg-muted text-foreground">
      <header className="border-b bg-background">
        <div className="mx-auto flex max-w-6xl items-center gap-4 px-6 py-4">
          <span className="text-xl font-semibold">j-law-grep</span>
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
                  className="w-full rounded-md border border-gray-300 bg-white py-2 pl-9 pr-3 text-sm shadow-sm focus:border-blue-500 focus:outline-none"
                  placeholder="キーワードや法令条番号を入力"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                />
              </div>
              <select
                className="rounded-md border border-gray-300 bg-white px-3 py-2 text-sm shadow-sm"
                value={lawFilter}
                onChange={(event) => setLawFilter(event.target.value)}
              >
                <option value="">すべての法令</option>
                <option value="民法">民法</option>
              </select>
              <input
                className="w-24 rounded-md border border-gray-300 bg-white px-2 py-2 text-sm shadow-sm"
                placeholder="施行年"
                value={yearFilter}
                onChange={(event) => setYearFilter(event.target.value)}
              />
              <div className="flex rounded-md border border-gray-200 bg-white p-0.5 shadow-sm">
                {MODES.map((item) => (
                  <button
                    key={item.value}
                    type="button"
                    onClick={() => setMode(item.value)}
                    className={clsx(
                      "rounded px-3 py-1 text-sm font-medium transition", 
                      mode === item.value
                        ? "bg-gray-900 text-white"
                        : "text-gray-600 hover:bg-gray-100"
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

      <main className="mx-auto grid max-w-6xl grid-cols-1 gap-6 px-6 py-6 md:grid-cols-[240px_1fr]">
        <aside className="space-y-4">
          <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
            <h2 className="text-sm font-semibold text-gray-700">法令フィルタ</h2>
            <p className="mt-2 text-xs text-gray-500">
              MVPでは民法のみを対象としたサンプルデータを検索します。
            </p>
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
          <div className="space-y-3">
            {results.hits.map((hit) => (
              <article key={hit.file_id} className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
                <div className="text-xs uppercase tracking-wide text-gray-500">{hit.path}</div>
                <div
                  className="mt-2 text-sm leading-relaxed text-gray-900"
                  dangerouslySetInnerHTML={{ __html: hit.snippet }}
                />
                {hit.url && (
                  <a href={hit.url} className="mt-3 inline-flex text-sm text-blue-600 hover:underline">
                    パーマリンク
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
