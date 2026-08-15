from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from django.conf import settings

from .boolean_query import parse_boolean_query
from .citation import Citation, citation_key, parse_citation_query
from .open_search_client import OpenSearchBackend, SearchHit, highlight_config

MAX_REGEX_LENGTH = 120
LONG_LITERAL_THRESHOLD = 15
# Leading/trailing wildcard on the `content_long` keyword field is a substring
# scan over every candidate doc, so it gets expensive on a full corpus. Cap the
# term length that earns a wildcard clause; longer literals fall back to the
# `content` phrase query only (tail of very long items may be missed, which the
# README documents). The 500-char `q` ceiling means 201..500 only phrase-match.
MAX_LONG_LITERAL_WILDCARD_LENGTH = 200
# OpenSearch refuses `from + size` beyond index.max_result_window (default 10000).
# Cap deep pagination here so a request like page=999999 fails fast with a clear
# 400 instead of hitting OpenSearch with a huge `from` (slow / 5xx).
MAX_RESULT_WINDOW = 10000
DANGEROUS_REGEX_PATTERNS = (
    r"\.\*.*\.\*",
    r"\(\.\+\)\+",
    r"\(\.\*\)\+",
    r"\([^)]*[+*][^)]*\)[+*]",
)
# Allowed filter keys per source. `all` accepts the union so a cross-search can
# constrain every half. Unknown keys are rejected (400) before the query reaches
# OpenSearch.
LAW_FILTER_KEYS = frozenset({"law", "year"})
DIET_FILTER_KEYS = frozenset({"house", "meeting", "speaker", "date_from", "date_to"})
SHUISHO_FILTER_KEYS = frozenset(
    {"house", "session", "speaker", "date_from", "date_to", "shuisho_kind"}
)
ALLOWED_FILTER_KEYS = {
    "law": LAW_FILTER_KEYS,
    "diet": DIET_FILTER_KEYS,
    "shuisho": SHUISHO_FILTER_KEYS,
    "all": LAW_FILTER_KEYS | DIET_FILTER_KEYS | SHUISHO_FILTER_KEYS,
}
SHUISHO_KINDS = ("question", "answer")
# Citation parsing is law-centric (article_no/law_name map onto law records).
# Diet reuses article_no for the speech order and shuisho for the paragraph
# position, so citation handling is disabled for both.
CITATION_SOURCES = frozenset({"law", "all"})
DATE_FILTER_KEYS = ("date_from", "date_to")
# The `date` mapping is strict yyyy-MM-dd. date.fromisoformat (Py3.11+) also
# accepts basic/week forms like 20250609 or 2025-W24-1, which would pass here
# unnormalized and then fail to parse in OpenSearch. Pin the format first.
DATE_FILTER_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass
class SearchParams:
    q: str
    mode: str
    filters: dict[str, str | None]
    size: int
    page: int
    source: str = "law"


class SearchService:
    def __init__(
        self,
        backend: OpenSearchBackend | None = None,
        backend_factory: Callable[[str], OpenSearchBackend] | None = None,
    ) -> None:
        self.backend_factory = backend_factory or (lambda index: OpenSearchBackend(index=index))
        self.backend = backend or self.backend_factory(settings.OPENSEARCH_INDEX)

    def _backend_for_source(self, source: str) -> OpenSearchBackend:
        if source == "diet":
            return self.backend_factory(settings.OPENSEARCH_DIET_INDEX)
        if source == "shuisho":
            return self.backend_factory(settings.OPENSEARCH_SHUISHO_INDEX)
        if source == "all":
            # Span the law alias the service was configured with plus the other
            # corpora aliases, so an injected backend's index is honored instead
            # of the global setting (keeps cross-source routing unit-testable).
            indices = [
                self.backend.index,
                settings.OPENSEARCH_DIET_INDEX,
                settings.OPENSEARCH_SHUISHO_INDEX,
            ]
            return self.backend_factory(",".join(indices))
        return self.backend

    def ensure_index(self) -> None:
        self.backend.ensure_index()

    def list_laws(self) -> list[str]:
        return sorted(self.backend.law_names())

    def law_document(
        self, law_id: str, article: str | None = None, context: int | None = None
    ) -> dict[str, Any] | None:
        response = self.backend.law_document(
            law_id, article=article if article and context is None else None
        )
        hits = response.get("hits", {}).get("hits", [])
        sections = [self._convert_law_section(hit) for hit in hits]
        sections = [section for section in sections if section["text"]]
        if not sections:
            return None
        sections.sort(key=self._section_sort_key)
        if article and context is not None:
            sections = self._context_sections(sections, article, context)
            if not sections:
                return None
        return {
            "law_id": law_id,
            "law_name": sections[0]["law_name"],
            "sections": sections,
        }

    def build_query(self, params: SearchParams) -> dict[str, Any]:
        raw_query = params.q.strip()
        if not raw_query:
            return {
                "query": {"match_none": {}},
                "highlight": highlight_config(),
            }
        parsed_citation = parse_citation_query(raw_query)
        citation = parsed_citation.citation
        citation_filter_key = citation_key(citation)
        citation_only = bool(citation.article_no and not parsed_citation.residual_query)
        residual_query = parsed_citation.residual_query
        # Citation parsing is law-centric: article_no/law_name map onto law
        # records. Diet records reuse article_no for the speech order (and
        # shuisho for the paragraph position), so applying citation handling
        # there returns 発言709 / requires law_name=民法 and drops real hits.
        # For those sources, ignore the citation split and treat the whole query
        # as free-text content search.
        treat_citation = params.source in CITATION_SOURCES
        # Text used for content matching. Law/all strip the citation prefix
        # (residual); diet/shuisho search the raw string as-is.
        text_query = (residual_query or raw_query) if treat_citation else raw_query
        # A pure citation lookup (民法709条) drives `must` to match_all and routes
        # the citation into the law-scoped filters only. There is no free-text
        # term to constrain diet records with, so for cross-search this must not
        # fall through to "every speech matches".
        citation_lookup = (
            treat_citation
            and bool(citation.article_no)
            and (
                params.mode == "citation"
                or (params.mode in {"auto", "literal", "keyword"} and citation_only)
            )
        )

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
        elif treat_citation and params.mode == "citation":
            if not citation.article_no:
                raise ValueError("Citation query must include an article number.")
            must.append({"match_all": {}})
        elif (
            treat_citation
            and params.mode in {"auto", "literal", "keyword"}
            and citation.article_no
            and citation_only
        ):
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
        elif params.mode == "keyword":
            must.append(
                {
                    "multi_match": {
                        "query": text_query,
                        "fields": ["content^2", "content.keywordish", "caption^3", "heading^3"],
                        "operator": "and",
                    }
                }
            )
        else:
            # must.append({"match_phrase": {"content": params.q}})
            must.append(self._literal_content_clause(text_query))
        law_filter = params.filters.get("law") if params.filters else None
        year_filter = params.filters.get("year") if params.filters else None
        house_filter = params.filters.get("house") if params.filters else None
        meeting_filter = params.filters.get("meeting") if params.filters else None
        speaker_filter = params.filters.get("speaker") if params.filters else None
        date_from_filter = params.filters.get("date_from") if params.filters else None
        date_to_filter = params.filters.get("date_to") if params.filters else None
        session_filter = params.filters.get("session") if params.filters else None
        shuisho_kind_filter = params.filters.get("shuisho_kind") if params.filters else None

        # Split filters by the source they constrain. For source="all" these are
        # applied per-source (see _source_filter_clauses) so a diet-only filter
        # such as speaker does not drop every law hit, and vice versa. Filters
        # shared by diet and shuisho (house / speaker / date) are appended to
        # both groups.
        law_scoped: list[dict[str, Any]] = []
        diet_scoped: list[dict[str, Any]] = []
        shuisho_scoped: list[dict[str, Any]] = []

        if law_filter:
            law_scoped.append(self._law_name_filter(law_filter))
            boost_should.extend(self._law_name_boosts(law_filter))
        if year_filter:
            law_scoped.append({"term": {"year_enforced": year_filter}})

        if house_filter:
            house_clause = {"term": {"house": house_filter}}
            diet_scoped.append(house_clause)
            shuisho_scoped.append(house_clause)
        if meeting_filter:
            diet_scoped.append(self._keyword_or_prefix_filter("meeting_name", meeting_filter))
        if speaker_filter:
            speaker_clause = self._speaker_filter(speaker_filter)
            diet_scoped.append(speaker_clause)
            shuisho_scoped.append(speaker_clause)
        if date_from_filter or date_to_filter:
            date_range: dict[str, str] = {}
            if date_from_filter:
                date_range["gte"] = date_from_filter
            if date_to_filter:
                date_range["lte"] = date_to_filter
            date_clause = {"range": {"date": date_range}}
            diet_scoped.append(date_clause)
            shuisho_scoped.append(date_clause)
        if session_filter:
            shuisho_scoped.append({"term": {"session": session_filter}})
        if shuisho_kind_filter:
            shuisho_scoped.append({"term": {"shuisho_kind": shuisho_kind_filter}})

        # A citation (民法709条 -> law_name + article_no ...) only constrains law
        # records, so it joins the law-scoped group. Skipped for diet, where these
        # fields mean something else (article_no is the speech order).
        if treat_citation:
            if citation.law_name:
                law_scoped.append(self._law_name_filter(citation.law_name))
                boost_should.extend(self._law_name_boosts(citation.law_name))
            if citation.article_no:
                law_scoped.append({"term": {"article_no": citation.article_no}})
            if citation.paragraph_no is not None:
                law_scoped.append({"term": {"paragraph_no": str(citation.paragraph_no)}})
            if citation.item_no is not None:
                law_scoped.append({"term": {"item_no": str(citation.item_no)}})

        filter_clauses.extend(
            self._source_filter_clauses(
                params.source,
                {"law": law_scoped, "diet": diet_scoped, "shuisho": shuisho_scoped},
                law_only=citation_lookup,
            )
        )

        if treat_citation and citation_filter_key:
            boost_should.append(
                {"match_phrase_prefix": {"citation_key.prefix": citation_filter_key}}
            )

        boost_should.extend(
            self._ranking_boosts(
                params.mode, text_query, citation_filter_key if treat_citation else None
            )
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
    def classify_query(raw_query: str, mode: str, source: str = "law") -> dict[str, Any]:
        parsed_citation = parse_citation_query(raw_query.strip())
        citation = parsed_citation.citation
        citation_only = bool(citation.article_no and not parsed_citation.residual_query)
        # Diet / shuisho search treats citation parsing as plain content search,
        # so never report an effective citation mode there (see build_query).
        treat_citation = source in CITATION_SOURCES
        effective_mode = mode
        if mode == "auto":
            effective_mode = (
                "citation"
                if treat_citation and citation.article_no and citation_only
                else "literal"
            )
        elif (
            treat_citation
            and mode in {"literal", "keyword"}
            and citation.article_no
            and citation_only
        ):
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
    def _source_filter_clauses(
        source: str,
        scoped: dict[str, list[dict[str, Any]]],
        law_only: bool = False,
    ) -> list[dict[str, Any]]:
        if source != "all":
            # A single-source search targets one alias, so every filter group can
            # be applied flatly: the groups for the other sources reference
            # fields that source does not populate, but the alias only holds this
            # source_type, so a non-matching group would only ever drop hits the
            # user explicitly filtered for.
            return [
                {"term": {"source_type": source}},
                *scoped.get(source, []),
            ]
        # Cross-search. A pure citation lookup has no free-text term to constrain
        # the non-law records with (`must` is match_all), so collapse to law-only
        # rather than letting the other branches match every document.
        if law_only:
            return [{"term": {"source_type": "law"}}, *scoped.get("law", [])]
        # Otherwise match a doc of any source that satisfies that source's own
        # filters. Each branch carries its own source_type term, so a filter for
        # one source never drops the others.
        return [
            {
                "bool": {
                    "should": [
                        {
                            "bool": {
                                "filter": [{"term": {"source_type": source_type}}, *clauses],
                            }
                        }
                        for source_type, clauses in scoped.items()
                    ],
                    "minimum_should_match": 1,
                }
            }
        ]

    @staticmethod
    def _law_name_filter(value: str) -> dict[str, Any]:
        # Match the canonical law_name OR any registered alias (民法典 -> 民法),
        # so a law selected/typed by an alias still filters correctly.
        return {
            "bool": {
                "should": [
                    {"term": {"law_name": value}},
                    {"term": {"law_aliases": value}},
                ],
                "minimum_should_match": 1,
            }
        }

    @staticmethod
    def _law_name_boosts(value: str) -> list[dict[str, Any]]:
        return [
            {"match_phrase_prefix": {"law_name.prefix": value}},
            {"match_phrase_prefix": {"law_aliases.prefix": value}},
        ]

    @staticmethod
    def _keyword_or_prefix_filter(field: str, value: str) -> dict[str, Any]:
        return {
            "bool": {
                "should": [
                    {"term": {field: value}},
                    {"prefix": {field: value}},
                ],
                "minimum_should_match": 1,
            }
        }

    @classmethod
    def _speaker_filter(cls, value: str) -> dict[str, Any]:
        return {
            "bool": {
                "should": [
                    cls._keyword_or_prefix_filter("speaker", value),
                    cls._keyword_or_prefix_filter("speaker_yomi", value),
                ],
                "minimum_should_match": 1,
            }
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

    @classmethod
    def _literal_content_clause(cls, term: str) -> dict[str, Any]:
        if len(term) <= LONG_LITERAL_THRESHOLD or len(term) > MAX_LONG_LITERAL_WILDCARD_LENGTH:
            return cls._content_phrase_clause(term)
        return {
            "bool": {
                "should": [
                    cls._content_phrase_clause(term),
                    cls._content_long_wildcard_clause(term),
                ],
                "minimum_should_match": 1,
            }
        }

    @staticmethod
    def _content_long_wildcard_clause(term: str, boost: float | None = None) -> dict[str, Any]:
        escaped = term.replace("\\", "\\\\").replace("*", "\\*").replace("?", "\\?")
        payload: dict[str, Any] = {
            "value": f"*{escaped}*",
            "case_insensitive": True,
        }
        if boost is not None:
            payload["boost"] = boost
        return {"wildcard": {"content_long": payload}}

    @classmethod
    def _ranking_boosts(
        cls, mode: str, term: str, citation_filter_key: str | None
    ) -> list[dict[str, Any]]:
        if mode in {"boolean", "regex", "keyword"}:
            return []
        boosts: list[dict[str, Any]] = []
        if citation_filter_key:
            boosts.append({"term": {"citation_key": {"value": citation_filter_key, "boost": 12.0}}})
        if term:
            boosts.extend(
                [
                    {
                        "match_phrase": {
                            "caption": {
                                "query": term,
                                "analyzer": "whitespace",
                                "boost": 5.0,
                            }
                        }
                    },
                    {
                        "match_phrase": {
                            "heading": {
                                "query": term,
                                "analyzer": "whitespace",
                                "boost": 5.0,
                            }
                        }
                    },
                    {
                        "match_phrase": {
                            "content": {
                                "query": term,
                                "analyzer": "whitespace",
                                "boost": 2.0,
                            }
                        }
                    },
                ]
            )
            if LONG_LITERAL_THRESHOLD < len(term) <= MAX_LONG_LITERAL_WILDCARD_LENGTH:
                boosts.append(cls._content_long_wildcard_clause(term, boost=3.0))
        return boosts

    @staticmethod
    def _is_citation_only_query(raw_query: str, citation_filter_key: str | None) -> bool:
        if not citation_filter_key:
            return False
        compact_query = re.sub(r"\s+", "", raw_query)
        compact_citation = re.sub(r"\s+", "", citation_filter_key)
        return compact_query == compact_citation

    @staticmethod
    def _index_payload(backend: OpenSearchBackend) -> dict[str, Any]:
        # `name` stays the comma-joined alias for backward compatibility; for
        # source="all" callers can use the split `indices` list instead of
        # parsing the string.
        return {"name": backend.index, "indices": backend.index.split(",")}

    def search(self, params: SearchParams) -> dict[str, Any]:
        if not params.q.strip():
            backend = self._backend_for_source(params.source)
            return {
                "hits": [],
                "total": 0,
                "took_ms": 0,
                "query": self.classify_query(params.q, params.mode, params.source),
                "index": self._index_payload(backend),
                "source": params.source,
            }
        body = self.build_query(params)
        size = params.size
        page = max(params.page, 1)
        from_ = (page - 1) * size
        backend = self._backend_for_source(params.source)
        # diet/shuisho/all may target an optional alias before it exists (fresh
        # env, CI, first boot). Tolerate the missing index so `all` still
        # returns law hits and the others return 0 results instead of a 5xx.
        ignore_unavailable = params.source != "law"
        response = backend.search(
            body=body, size=size, from_=from_, ignore_unavailable=ignore_unavailable
        )
        hits = [self._convert_hit(hit, params.q) for hit in response["hits"]["hits"]]
        return {
            "hits": hits,
            "total": response["hits"].get("total", {}).get("value", 0),
            "took_ms": response.get("took", 0),
            "query": self.classify_query(params.q, params.mode, params.source),
            "index": self._index_payload(backend),
            "source": params.source,
        } | self._debug_payload(params)

    def debug_query(self, params: SearchParams) -> dict[str, Any]:
        body = self.build_query(params)
        parsed = parse_citation_query(params.q.strip())
        return {
            "query_dsl": body,
            "parsed_citation": self._citation_payload(parsed.citation),
            "effective_mode": self.classify_query(params.q, params.mode, params.source)[
                "effective_mode"
            ],
            "ranking_signals": self._debug_payload(params)
            .get("debug", {})
            .get("ranking_signals", {}),
            "index": {"name": self._backend_for_source(params.source).index},
        }

    @staticmethod
    def _debug_payload(params: SearchParams) -> dict[str, Any]:
        if not settings.DEBUG:
            return {}
        parsed = parse_citation_query(params.q.strip())
        citation_filter_key = citation_key(parsed.citation)
        filters = params.filters or {}
        return {
            "debug": {
                "ranking_signals": {
                    "citation_exact": bool(citation_filter_key),
                    "law_name": bool(parsed.citation.law_name or filters.get("law")),
                    "heading": bool(parsed.residual_query or params.q.strip()),
                    "content": bool(params.q.strip()),
                    "content_long": len(parsed.residual_query or params.q.strip())
                    > LONG_LITERAL_THRESHOLD,
                }
            }
        }

    @staticmethod
    def validate_pagination(page: int, size: int) -> None:
        window = (page - 1) * size + size
        if window > MAX_RESULT_WINDOW:
            raise ValueError(
                f"Pagination beyond {MAX_RESULT_WINDOW} results is not supported "
                "(narrow the query or reduce page/size)."
            )

    @staticmethod
    def validate_filters(source: str, filters: dict[str, str | None] | None) -> None:
        if not filters:
            return
        allowed = ALLOWED_FILTER_KEYS.get(source, LAW_FILTER_KEYS)
        unknown = sorted(key for key in filters if key not in allowed)
        if unknown:
            raise ValueError(f"Unsupported filter(s) for source '{source}': {', '.join(unknown)}.")
        parsed_dates: dict[str, date] = {}
        for key in DATE_FILTER_KEYS:
            raw = filters.get(key)
            if not raw:
                continue
            if not DATE_FILTER_PATTERN.match(raw):
                raise ValueError(f"{key} must be a valid YYYY-MM-DD date.")
            try:
                parsed_dates[key] = date.fromisoformat(raw)
            except ValueError as exc:
                raise ValueError(f"{key} must be a valid YYYY-MM-DD date.") from exc
        date_from = parsed_dates.get("date_from")
        date_to = parsed_dates.get("date_to")
        if date_from and date_to and date_from > date_to:
            raise ValueError("date_from must not be after date_to.")
        kind = filters.get("shuisho_kind")
        if kind and kind not in SHUISHO_KINDS:
            raise ValueError(f"shuisho_kind must be one of: {', '.join(SHUISHO_KINDS)}.")

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
        highlight_snippet = self._best_highlight_snippet(hit.get("highlight", {}))
        snippet_text, highlights = self._snippet_with_ranges(
            highlight_snippet or source.get("content", "") or source.get("caption", ""),
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
            source_type=source.get("source_type", "law") or "law",
            law_id=source.get("law_id", "") or "",
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
            house=source.get("house"),
            meeting_name=source.get("meeting_name"),
            date=source.get("date"),
            speaker=source.get("speaker"),
            speaker_group=source.get("speaker_group"),
            speaker_position=source.get("speaker_position"),
            speaker_role=source.get("speaker_role"),
            session=source.get("session"),
            shuisho_kind=source.get("shuisho_kind"),
            shuisho_number=source.get("shuisho_number"),
        )
        return {
            "file_id": data.file_id,
            "source_type": data.source_type,
            "law_id": data.law_id,
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
            "house": data.house,
            "meeting_name": data.meeting_name,
            "date": data.date,
            "speaker": data.speaker,
            "speaker_group": data.speaker_group,
            "speaker_position": data.speaker_position,
            "speaker_role": data.speaker_role,
            "session": data.session,
            "shuisho_kind": data.shuisho_kind,
            "shuisho_number": data.shuisho_number,
        }

    @staticmethod
    def _best_highlight_snippet(highlight: dict[str, Any]) -> str:
        for field in ("content", "caption", "heading"):
            snippets = highlight.get(field, [])
            marked = [str(snippet) for snippet in snippets if "<mark>" in str(snippet)]
            if marked:
                return "".join(marked)
        for field in ("content", "caption", "heading"):
            snippets = highlight.get(field, [])
            if snippets:
                return "".join(str(snippet) for snippet in snippets)
        return ""

    @staticmethod
    def _convert_law_section(hit: dict[str, Any]) -> dict[str, Any]:
        source = hit.get("_source", {})
        blocks = source.get("blocks", [])
        text = source.get("content_plain") or source.get("content") or ""
        if not text and isinstance(blocks, list):
            block_texts = [
                block.get("text") or block.get("html") or block.get("content") or ""
                for block in blocks
                if isinstance(block, dict)
            ]
            text = "\n\n".join(item for item in block_texts if item)
        return {
            "id": str(hit.get("_id", "")),
            "law_id": source.get("law_id", "") or "",
            "law_name": source.get("law_name", "") or "",
            "article_no": source.get("article_no", "") or "",
            "paragraph_no": source.get("paragraph_no"),
            "item_no": source.get("item_no"),
            "caption": source.get("caption", "") or "",
            "heading": source.get("heading", "") or "",
            "text": text,
            "url": source.get("url", "") or "",
            "path": source.get("path", "") or "",
        }

    @staticmethod
    def _section_sort_key(
        section: dict[str, Any],
    ) -> tuple[
        list[tuple[int, int | str]],
        list[tuple[int, int | str]],
        list[tuple[int, int | str]],
        str,
    ]:
        return (
            SearchService._natural_label_key(section.get("article_no")),
            SearchService._natural_label_key(section.get("paragraph_no")),
            SearchService._natural_label_key(section.get("item_no")),
            str(section.get("id", "")),
        )

    @staticmethod
    def _context_sections(
        sections: list[dict[str, Any]], article: str, context: int
    ) -> list[dict[str, Any]]:
        positions = [
            index
            for index, section in enumerate(sections)
            if str(section.get("article_no")) == article
        ]
        if not positions:
            return []
        start = max(min(positions) - context, 0)
        end = min(max(positions) + context + 1, len(sections))
        return sections[start:end]

    @staticmethod
    def _natural_label_key(value: Any) -> list[tuple[int, int | str]]:
        if value is None or value == "":
            return []
        parts = re.split(r"(\d+)", str(value))
        return [(0, int(part)) if part.isdigit() else (1, part) for part in parts if part]

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
