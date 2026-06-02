from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .citation import citation_key, parse_citation
from .open_search_client import OpenSearchBackend, SearchHit, highlight_config

MAX_REGEX_LENGTH = 120
DANGEROUS_REGEX_PATTERNS = (
    r"\.\*.*\.\*",
    r"\(\.\+\)\+",
    r"\(\.\*\)\+",
    r"\([^)]*[+*][^)]*\)[+*]",
)


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
        raw_query = params.q.strip()
        citation = parse_citation(raw_query)
        citation_filter_key = citation_key(citation)
        citation_only = self._is_citation_only_query(raw_query, citation_filter_key)

        must: List[Dict[str, Any]] = []
        filter_clauses: List[Dict[str, Any]] = []
        should: List[Dict[str, Any]] = []

        if params.mode == "regex":
            self.validate_regex(raw_query)
            must.append(
                {
                    "regexp": {
                        "content": {
                            "value": raw_query,
                            "flags": "ALL",
                            "max_determinized_states": 5000,
                        }
                    }
                }
            )
        elif citation.article_no and (params.mode in {"auto", "citation"} or citation_only):
            must.append({"match_all": {}})
        else:
            # must.append({"match_phrase": {"content": params.q}})
            must.append(
                {
                    "match_phrase": {
                        "content": {
                            "query": raw_query,
                            "analyzer": "whitespace",
                            "slop": 0,
                        }
                    }
                }
            )
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
            filter_clauses.append({"term": {"paragraph_no": str(citation.paragraph_no)}})
        if citation.item_no is not None:
            filter_clauses.append({"term": {"item_no": str(citation.item_no)}})

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

    @staticmethod
    def _is_citation_only_query(raw_query: str, citation_filter_key: Optional[str]) -> bool:
        if not citation_filter_key:
            return False
        compact_query = re.sub(r"\s+", "", raw_query)
        compact_citation = re.sub(r"\s+", "", citation_filter_key)
        return compact_query == compact_citation

    def search(self, params: SearchParams) -> Dict[str, Any]:
        if not params.q.strip():
            return {"hits": [], "total": 0, "took_ms": 0}
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

    @staticmethod
    def validate_regex(pattern: str) -> None:
        if not pattern:
            raise ValueError("Regex query must not be empty.")
        if len(pattern) > MAX_REGEX_LENGTH:
            raise ValueError(f"Regex query must be {MAX_REGEX_LENGTH} characters or fewer.")
        for dangerous in DANGEROUS_REGEX_PATTERNS:
            if re.search(dangerous, pattern):
                raise ValueError("Regex query is too broad or expensive.")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"Invalid regex query: {exc}") from exc

    def _convert_hit(self, hit: Dict[str, Any], query: str) -> Dict[str, Any]:
        source = hit.get("_source", {})
        highlight_snippet = "".join(hit.get("highlight", {}).get("content", []))
        snippet_text, highlights = self._snippet_with_ranges(
            highlight_snippet or source.get("content", ""),
            query,
        )
        law_name = source.get("law_name") or ""
        article_no = source.get("article_no") or ""
        paragraph_no = source.get("paragraph_no")
        item_no = source.get("item_no")
        path = source.get("path") or ""
        url = source.get("url", "") or ""
        if not article_no:
            article_no = self._extract_article_from_url(url) or self._extract_article_from_path(path)
        if paragraph_no is None:
            paragraph_no = self._extract_paragraph_from_url(url)
        if not path and law_name:
            path = f"{law_name}/{article_no}" if article_no else law_name
        data = SearchHit(
            file_id=str(hit.get("_id", "")),
            law_name=law_name,
            article_no=article_no,
            paragraph_no=paragraph_no,
            item_no=item_no,
            path=path,
            line=source.get("line", 0),
            snippet=snippet_text,
            snippet_text=snippet_text,
            highlights=highlights,
            url=url,
            blocks=source.get("blocks", []),
        )
        return {
            "file_id": data.file_id,
            "law_name": data.law_name,
            "article_no": data.article_no,
            "paragraph_no": data.paragraph_no,
            "item_no": data.item_no,
            "path": data.path,
            "line": data.line,
            "snippet": data.snippet,
            "snippet_text": data.snippet_text,
            "highlights": data.highlights,
            "url": data.url,
            "blocks": data.blocks,
        }

    @staticmethod
    def _extract_article_from_url(url: str) -> str:
        # URLs look like /l/{law_id}/a/{article_no}/[{paragraph_no}/[{item_no}]]
        match = re.search(r"/a/([^/]+)", url)
        return match.group(1) if match else ""

    @staticmethod
    def _extract_article_from_path(path: str) -> str:
        # Paths look like {law_name}/{article_no}
        parts = path.split("/")
        return parts[1] if len(parts) >= 2 else ""

    @staticmethod
    def _extract_paragraph_from_url(url: str) -> Optional[str]:
        match = re.search(r"/a/[^/]+/(\d+)", url)
        if not match:
            return None
        return match.group(1)

    def _snippet_with_ranges(self, snippet: str, query: str) -> Tuple[str, List[Dict[str, int]]]:
        if "<mark>" in snippet or "</mark>" in snippet:
            return self._parse_marked_snippet(snippet)
        return snippet, self._literal_ranges(snippet, query)

    @staticmethod
    def _parse_marked_snippet(snippet: str) -> Tuple[str, List[Dict[str, int]]]:
        text_parts: List[str] = []
        ranges: List[Dict[str, int]] = []
        active_start: Optional[int] = None
        i = 0
        while i < len(snippet):
            if snippet.startswith("<mark>", i):
                if active_start is None:
                    active_start = len("".join(text_parts))
                i += len("<mark>")
                continue
            if snippet.startswith("</mark>", i):
                if active_start is not None:
                    end = len("".join(text_parts))
                    if end > active_start:
                        ranges.append({"start": active_start, "end": end})
                    active_start = None
                i += len("</mark>")
                continue
            if snippet[i] == "<":
                close = snippet.find(">", i + 1)
                if close != -1:
                    i = close + 1
                    continue
            text_parts.append(snippet[i])
            i += 1

        if active_start is not None:
            end = len("".join(text_parts))
            if end > active_start:
                ranges.append({"start": active_start, "end": end})
        return "".join(text_parts), ranges

    @staticmethod
    def _literal_ranges(snippet: str, query: str) -> List[Dict[str, int]]:
        if not query:
            return []
        ranges: List[Dict[str, int]] = []
        start = 0
        while True:
            idx = snippet.find(query, start)
            if idx == -1:
                break
            end = idx + len(query)
            ranges.append({"start": idx, "end": end})
            start = end
        return ranges
