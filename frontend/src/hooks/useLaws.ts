import { useEffect, useState } from "react";
import { fetchLaws } from "../api/search";

// Fetches the distinct law names so the filter dropdown is data-driven instead
// of hardcoded. Failures fall back to an empty list (the "all laws" option
// still works).
export function useLaws(): string[] {
  const [laws, setLaws] = useState<string[]>([]);

  useEffect(() => {
    const controller = new AbortController();
    fetchLaws(controller.signal)
      .then(setLaws)
      .catch(() => {
        /* non-fatal: keep the empty list */
      });
    return () => controller.abort();
  }, []);

  return laws;
}
