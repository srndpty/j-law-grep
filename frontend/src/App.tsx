import { useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import { Button } from "./components/ui/button";
import { isEditableTarget } from "./highlight-ranges";
import { useSearchSettings } from "./hooks/useSearchSettings";
import { useSearch } from "./hooks/useSearch";
import { useLaws } from "./hooks/useLaws";
import { SearchBar } from "./components/SearchBar";
import { SearchModeTabs } from "./components/SearchModeTabs";
import { FilterPanel } from "./components/FilterPanel";
import { SettingsPanel } from "./components/SettingsPanel";
import { DebugPanel } from "./components/DebugPanel";
import { SearchResultList } from "./components/SearchResultList";

export default function App() {
  const {
    query,
    setQuery,
    mode,
    setMode,
    lawFilter,
    setLawFilter,
    yearFilter,
    setYearFilter,
    requestBody,
  } = useSearchSettings();
  const [isComposing, setIsComposing] = useState(false);
  const { results, isLoading, error, requestId, search } = useSearch({
    requestBody,
    query,
    mode,
    isComposing,
  });
  const { laws, error: lawsError, isLoading: lawsIsLoading } = useLaws();

  const [selectedIndex, setSelectedIndex] = useState(0);
  const [showDebug, setShowDebug] = useState(false);
  const resultRefs = useRef<Array<HTMLElement | null>>([]);

  // Reset selection whenever the result set changes.
  useEffect(() => {
    setSelectedIndex(0);
  }, [results]);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "ArrowDown") {
        if (isEditableTarget(event.target) || event.isComposing) return;
        event.preventDefault();
        setSelectedIndex((current) => Math.min(current + 1, Math.max(results.hits.length - 1, 0)));
      }
      if (event.key === "ArrowUp") {
        if (isEditableTarget(event.target) || event.isComposing) return;
        event.preventDefault();
        setSelectedIndex((current) => Math.max(current - 1, 0));
      }
      if (event.key === "Enter") {
        if (isEditableTarget(event.target) || event.isComposing) return;
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
                void search();
              }}
            >
              <SearchBar
                value={query}
                onChange={setQuery}
                onCompositionStart={() => setIsComposing(true)}
                onCompositionEnd={(value) => {
                  setIsComposing(false);
                  setQuery(value);
                }}
              />
              <FilterPanel
                laws={laws}
                lawFilter={lawFilter}
                onLawChange={setLawFilter}
                yearFilter={yearFilter}
                onYearChange={setYearFilter}
              />
              <SearchModeTabs mode={mode} onChange={setMode} />
              <Button type="submit">検索</Button>
            </form>
          </div>
        </div>
      </header>

      <main className="mx-auto grid max-w-7xl grid-cols-1 gap-6 px-6 py-6 md:grid-cols-[260px_1fr]">
        <aside className="space-y-4">
          <SettingsPanel
            effectiveMode={results.query?.effective_mode ?? mode}
            indexName={results.index?.name}
            lawsError={lawsError}
            lawsIsLoading={lawsIsLoading}
            requestId={requestId}
            onToggleDebug={() => setShowDebug((value) => !value)}
          />
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
          {error && (
            <p className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-700">
              {error}
              {requestId && (
                <span className="ml-2 font-mono text-xs text-red-500">
                  (request_id: {requestId})
                </span>
              )}
            </p>
          )}
          {showDebug && (
            <DebugPanel
              requestBody={requestBody}
              requestId={requestId}
              query={results.query}
              index={results.index}
            />
          )}
          <SearchResultList
            hits={results.hits}
            selectedIndex={selectedIndex}
            isLoading={isLoading}
            onSelect={setSelectedIndex}
            setItemRef={(index, element) => {
              resultRefs.current[index] = element;
            }}
          />
        </section>
      </main>
    </div>
  );
}
