import type { SearchRequest, SearchResponse } from "../api/search";

interface Props {
  requestBody: SearchRequest;
  requestId: string | null;
  query: SearchResponse["query"];
  index: SearchResponse["index"];
}

export function DebugPanel({ requestBody, requestId, query, index }: Props) {
  return (
    <pre className="max-h-64 overflow-auto rounded-md border border-gray-300 bg-white p-3 text-xs text-gray-700">
      {JSON.stringify({ request: requestBody, request_id: requestId, query, index }, null, 2)}
    </pre>
  );
}
