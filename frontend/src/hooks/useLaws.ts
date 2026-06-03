import { useEffect, useState } from "react";
import { fetchLaws } from "../api/search";

interface UseLawsResult {
  laws: string[];
  error: string | null;
  isLoading: boolean;
}

// Fetches the distinct law names so the filter dropdown is data-driven.
// Failures are non-fatal because the "all laws" option still works.
export function useLaws(): UseLawsResult {
  const [laws, setLaws] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const controller = new AbortController();
    setIsLoading(true);
    fetchLaws(controller.signal)
      .then((items) => {
        setLaws(items);
        setError(null);
      })
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === "AbortError") return;
        setError(err instanceof Error ? err.message : "法令一覧を取得できませんでした。");
      })
      .finally(() => {
        if (!controller.signal.aborted) setIsLoading(false);
      });
    return () => controller.abort();
  }, []);

  return { laws, error, isLoading };
}
