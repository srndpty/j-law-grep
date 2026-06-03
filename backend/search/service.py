from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .boolean_query import parse_boolean_query
from .citation import Citation, citation_key, parse_citation_query
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
    filters: dict[str, str | None]
    size: int
    page: int


class SearchService:
    def __init__(self, backend: OpenSearchBackend | None = None) -> None:
        self.backend = backend or OpenSearchBackend()

    def ensure_index(self) -> None:
        self.backend.ensure_index()

    def build_query(self, params: SearchParams) -> dict[str, Any]:
        raw_query = params.q.strip()
        parsed_citation = parse_citation_query(raw_query)
        citation = parsed_citation.citation
        citation_filter_key = citation_key(citation)
        citation_only = bool(citation.article_no and not parsed_citation.residual_query)
        residual_query = parsed_citation.residual_query

        must: list[dict[str, Any]] = []
        filter_clauses: list[dict[str, Any]] = []
        boost_should: list[dict[str, Any]] = []
        must_not: list[dict[str, Any]] = []

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
        elif params.mode == "citation":
            if not citation.article_no:
                raise ValueError("Citation query must include an article number.")
            must.append({"match_all": {}})
        elif params.mode in {"auto", "literal"} and citation.article_no and citation_only:
            must.append({"match_all": {}})
        elif params.mode == "boolean":
            boolean = parse_boolean_query(raw_query)
            for term in boolean.required:
                must.append(self._content_phrase_clause(term))
            for group in boolean.optional_groups:
                must.append(
                    {
                        "bool": {
                            "should": [self._content_phrase_clause(term) for term in group],
                            "minimum_should_match": 1,
                        }
                    }
                )
            for term in boolean.excluded:
                must_not.append(self._content_phrase_clause(term))
            if not must and not must_not:
                must.append({"match_all": {}})
        else:
            # must.append({"match_phrase": {"content": params.q}})
            must.append(self._content_phrase_clause(residual_query or raw_query))
        law_filter = params.filters.get("law") if params.filters else None
        year_filter = params.filters.get("year") if params.filters else None

        if law_filter:
            filter_clauses.append({"term": {"law_name": law_filter}})
            boost_should.append({"match_phrase_prefix": {"law_name.prefix": law_filter}})

        if year_filter:
            filter_clauses.append({"term": {"year_enforced": year_filter}})

        if citation.law_name:
            filter_clauses.append({"term": {"law_name": citation.law_name}})
            boost_should.append({"match_phrase_prefix": {"law_name.prefix": citation.law_name}})
        if citation.article_no:
            filter_clauses.append({"term": {"article_no": citation.article_no}})
        if citation.paragraph_no is not None:
            filter_clauses.append({"term": {"paragraph_no": str(citation.paragraph_no)}})
        if citation.item_no is not None:
            filter_clauses.append({"term": {"item_no": str(citation.item_no)}})

        if citation_filter_key:
            boost_should.append(
                {"match_phrase_prefix": {"citation_key.prefix": citation_filter_key}}
            )

        query: dict[str, Any] = {
            "bool": {
                "must": must,
                "filter": filter_clauses,
            }
        }
        if must_not:
            query["bool"]["must_not"] = must_not
        if boost_should:
            query["bool"]["should"] = boost_should

        return {
            "query": query,
            "highlight": highlight_config(),
        }

    @staticmethod
    def classify_query(raw_query: str, mode: str) -> dict[str, Any]:
        parsed_citation = parse_citation_query(raw_query.strip())
        citation = parsed_citation.citation
        citation_only = bool(citation.article_no and not parsed_citation.residual_query)
        effective_mode = mode
        if mode == "auto":
            effective_mode = "citation" if citation.article_no and citation_only else "literal"
        elif mode == "literal" and citation.article_no and citation_only:
            effective_mode = "citation"
        return {
            "raw": raw_query,
            "mode": mode,
            "effective_mode": effective_mode,
            "parsed": SearchService._citation_payload(citation),
        }

    @staticmethod
    def _citation_payload(citation: Citation) -> dict[str, Any]:
        return {
            "law_name": citation.law_name,
            "article_no": citation.article_no,
            "paragraph_no": citation.paragraph_no,
            "item_no": citation.item_no,
        }

    @staticmethod
    def _content_phrase_clause(term: str) -> dict[str, Any]:
        return {
            "match_phrase": {
                "content": {
                    "query": term,
                    "analyzer": "whitespace",
                    "slop": 0,
                }
            }
        }

    @staticmethod
    def _is_citation_only_query(raw_query: str, citation_filter_key: str | None) -> bool:
        if not citation_filter_key:
            return False
        compact_query = re.sub(r"\s+", "", raw_query)
        compact_citation = re.sub(r"\s+", "", citation_filter_key)
        return compact_query == compact_citation

    def search(self, params: SearchParams) -> dict[str, Any]:
        if not params.q.strip():
            return {
                "hits": [],
                "total": 0,
                "took_ms": 0,
                "query": self.classify_query(params.q, params.mode),
                "index": {"name": self.backend.index},
            }
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
            "query": self.classify_query(params.q, params.mode),
            "index": {"name": self.backend.index},
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

    def _convert_hit(self, hit: dict[str, Any], query: str) -> dict[str, Any]:
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
            article_no = self._extract_article_from_url(url) or self._extract_article_from_path(
                path
            )
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
    def _extract_paragraph_from_url(url: str) -> str | None:
        match = re.search(r"/a/[^/]+/(\d+)", url)
        if not match:
            return None
        return match.group(1)

    def _snippet_with_ranges(self, snippet: str, query: str) -> tuple[str, list[dict[str, int]]]:
        if "<mark>" in snippet or "</mark>" in snippet:
            return self._parse_marked_snippet(snippet)
        return snippet, self._literal_ranges(snippet, query)

    @staticmethod
    def _parse_marked_snippet(snippet: str) -> tuple[str, list[dict[str, int]]]:
        text_parts: list[str] = []
        ranges: list[dict[str, int]] = []
        active_start: int | None = None
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
    def _literal_ranges(snippet: str, query: str) -> list[dict[str, int]]:
        if not query:
            return []
        ranges: list[dict[str, int]] = []
        start = 0
        while True:
            idx = snippet.find(query, start)
            if idx == -1:
                break
            end = idx + len(query)
            ranges.append({"start": idx, "end": end})
            start = end
        return ranges
