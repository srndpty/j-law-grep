from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .citation import citation_key, parse_citation
from .open_search_client import OpenSearchBackend, SearchHit, highlight_config


@dataclass
class SearchParams:
    q: str
    mode: str
    filters: Dict[str, Optional[str]]
    size: int
    page: int


class SearchService:
    def __init__(self, backend: Optional[OpenSearchBackend] = None) -> None:
        self.backend = backend or OpenSearchBackend()

    def ensure_index(self) -> None:
        self.backend.ensure_index()

    def build_query(self, params: SearchParams) -> Dict[str, Any]:
        citation = parse_citation(params.q)
        citation_filter_key = citation_key(citation)

        must: List[Dict[str, Any]] = []
        filter_clauses: List[Dict[str, Any]] = []
        should: List[Dict[str, Any]] = []

        if params.mode == "regex":
            try:
                re.compile(params.q)
                must.append({"regexp": {"content": {"value": params.q, "flags": "ALL"}}})
            except re.error:
                must.append({"match": {"content": params.q}})
        else:
            must.append({"match_phrase": {"content": params.q}})

        law_filter = params.filters.get("law") if params.filters else None
        year_filter = params.filters.get("year") if params.filters else None

        if law_filter:
            filter_clauses.append({"term": {"law_name": law_filter}})
            should.append({"match_phrase_prefix": {"law_name.prefix": law_filter}})

        if year_filter:
            filter_clauses.append({"term": {"year_enforced": year_filter}})

        if citation.law_name:
            filter_clauses.append({"term": {"law_name": citation.law_name}})
            should.append({"match_phrase_prefix": {"law_name.prefix": citation.law_name}})
        if citation.article_no:
            filter_clauses.append({"term": {"article_no": citation.article_no}})
        if citation.paragraph_no is not None:
            filter_clauses.append({"term": {"paragraph_no": citation.paragraph_no}})
        if citation.item_no is not None:
            filter_clauses.append({"term": {"item_no": citation.item_no}})

        if citation_filter_key:
            should.append({"match_phrase_prefix": {"citation_key.prefix": citation_filter_key}})

        query: Dict[str, Any] = {
            "bool": {
                "must": must,
                "filter": filter_clauses,
            }
        }
        if should:
            query["bool"]["should"] = should
            query["bool"]["minimum_should_match"] = 1

        return {
            "query": query,
            "highlight": highlight_config(),
        }

    def search(self, params: SearchParams) -> Dict[str, Any]:
        body = self.build_query(params)
        size = params.size
        page = max(params.page, 1)
        from_ = (page - 1) * size
        response = self.backend.search(body=body, size=size, from_=from_)
        hits = [self._convert_hit(hit, params.q) for hit in response["hits"]["hits"]]
        return {
            "hits": hits,
            "total": response["hits"].get("total", {}).get("value", 0),
            "took_ms": response.get("took", 0),
        }

    def _convert_hit(self, hit: Dict[str, Any], query: str) -> Dict[str, Any]:
        source = hit.get("_source", {})
        highlight_snippet = "".join(hit.get("highlight", {}).get("content", []))
        snippet = self._ensure_highlight(highlight_snippet or source.get("content", ""), query)
        data = SearchHit(
            file_id=str(hit.get("_id", "")),
            path=source.get("path", ""),
            line=source.get("line", 0),
            snippet=snippet,
            url=source.get("url", ""),
            blocks=source.get("blocks", []),
        )
        return {
            "file_id": data.file_id,
            "path": data.path,
            "line": data.line,
            "snippet": data.snippet,
            "url": data.url,
            "blocks": data.blocks,
        }

    def _ensure_highlight(self, snippet: str, query: str) -> str:
        if not query:
            return snippet
        if "<mark>" in snippet:
            # If the entire sentence is wrapped once, unwrap and re-apply to the term only
            if snippet.count("<mark>") == 1 and snippet.startswith("<mark>") and snippet.endswith("</mark>"):
                snippet = snippet.replace("<mark>", "", 1).rsplit("</mark>", 1)[0]
            else:
                return snippet
        try:
            pattern = re.escape(query)
            return re.sub(pattern, lambda m: f"<mark>{m.group(0)}</mark>", snippet)
        except re.error:
            return snippet
