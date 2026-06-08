export interface HighlightRange {
  start: number;
  end: number;
}

export interface SearchHit {
  file_id: string;
  source_type?: "law" | "diet" | string;
  law_id: string;
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

export interface SearchResponse {
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
  debug?: {
    ranking_signals?: Record<string, boolean>;
  };
}

export interface SearchRequest {
  q: string;
  mode: string;
  source?: string;
  filters: Record<string, string>;
  size: number;
  page: number;
}

export interface SearchResult {
  data: SearchResponse;
  requestId: string | null;
}

export interface LawSection {
  id: string;
  law_id: string;
  law_name: string;
  article_no: string;
  paragraph_no: number | string | null;
  item_no: number | string | null;
  caption?: string;
  heading: string;
  text: string;
  url: string;
  path: string;
}

export interface LawDocument {
  law_id: string;
  law_name: string;
  sections: LawSection[];
}

const API_BASE = "/api";

export function extractErrorMessage(body: unknown, status: number): string {
  if (body && typeof body === "object") {
    const obj = body as Record<string, unknown>;
    if (typeof obj.detail === "string") return obj.detail;
    const parts: string[] = [];
    for (const [key, value] of Object.entries(obj)) {
      if (key === "request_id") continue;
      if (Array.isArray(value)) parts.push(`${key}: ${value.join(", ")}`);
      else if (typeof value === "string") parts.push(`${key}: ${value}`);
    }
    if (parts.length) return parts.join(" / ");
  }
  return `検索に失敗しました (${status})`;
}

export async function postSearch(body: SearchRequest, signal: AbortSignal): Promise<SearchResult> {
  const response = await fetch(`${API_BASE}/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  const requestId = response.headers.get("X-Request-ID");
  if (!response.ok) {
    let errorBody: unknown = null;
    try {
      errorBody = await response.json();
    } catch {
      errorBody = null;
    }
    const error = new Error(extractErrorMessage(errorBody, response.status));
    (error as Error & { requestId?: string | null }).requestId = requestId;
    throw error;
  }
  const data = (await response.json()) as SearchResponse;
  return { data, requestId };
}

export async function fetchLawDocument(lawId: string, article?: string): Promise<LawDocument> {
  const params = new URLSearchParams();
  if (article) params.set("article", article);
  const suffix = params.toString() ? `?${params.toString()}` : "";
  const response = await fetch(`${API_BASE}/laws/${encodeURIComponent(lawId)}${suffix}`);
  if (!response.ok) {
    let errorBody: unknown = null;
    try {
      errorBody = await response.json();
    } catch {
      errorBody = null;
    }
    throw new Error(extractErrorMessage(errorBody, response.status));
  }
  return (await response.json()) as LawDocument;
}
