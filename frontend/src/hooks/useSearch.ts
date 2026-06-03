import { useEffect, useRef, useState } from "react";
import { postSearch, type SearchRequest, type SearchResponse } from "../api/search";
import { shouldAutoSearch } from "../search-behavior";

const EMPTY_RESULTS: SearchResponse = { hits: [], total: 0, took_ms: 0 };

interface UseSearchArgs {
  requestBody: SearchRequest;
  query: string;
  mode: string;
  isComposing: boolean;
}

export function useSearch({ requestBody, query, mode, isComposing }: UseSearchArgs) {
  const [results, setResults] = useState<SearchResponse>(EMPTY_RESULTS);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [requestId, setRequestId] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const requestSeqRef = useRef(0);

  async function performSearch(body: SearchRequest = requestBody) {
    if (!body.q.trim()) {
      abortRef.current?.abort();
      setResults(EMPTY_RESULTS);
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
      const { data, requestId: responseId } = await postSearch(body, controller.signal);
      if (requestSeqRef.current === requestSeq) {
        setResults(data);
        setRequestId(responseId);
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        return;
      }
      if (requestSeqRef.current !== requestSeq) {
        return;
      }
      const withId = err as Error & { requestId?: string | null };
      if (withId.requestId !== undefined) setRequestId(withId.requestId);
      setError(err instanceof Error ? err.message : "検索に失敗しました");
    } finally {
      if (requestSeqRef.current === requestSeq) {
        setIsLoading(false);
      }
    }
  }

  useEffect(() => {
    if (!shouldAutoSearch(query, mode, isComposing)) {
      abortRef.current?.abort();
      if (query.trim().length < 2) {
        setResults(EMPTY_RESULTS);
      }
      setIsLoading(false);
      return;
    }
    const handle = setTimeout(() => {
      void performSearch(requestBody);
    }, 250);
    return () => clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isComposing, mode, query, requestBody]);

  return { results, isLoading, error, requestId, search: performSearch };
}
