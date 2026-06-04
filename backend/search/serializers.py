from __future__ import annotations

from typing import Any

from rest_framework import serializers

from .service import MAX_REGEX_LENGTH, MAX_RESULT_WINDOW, SearchService


class SearchFiltersField(serializers.DictField):
    child = serializers.CharField(allow_blank=True, required=False)

    def to_internal_value(self, data: Any) -> dict[str, str]:
        value = super().to_internal_value(data)
        return {key: val for key, val in value.items() if val != ""}


class SearchRequestSerializer(serializers.Serializer):
    q = serializers.CharField(allow_blank=True, trim_whitespace=True)
    mode = serializers.ChoiceField(
        choices=["auto", "literal", "keyword", "boolean", "citation", "regex"], default="literal"
    )
    filters = SearchFiltersField(required=False, default=dict)
    size = serializers.IntegerField(min_value=1, max_value=100, default=20)
    # Absolute cap; the precise `from + size` window is enforced in validate().
    page = serializers.IntegerField(min_value=1, max_value=MAX_RESULT_WINDOW, default=1)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs.get("mode") == "regex":
            try:
                SearchService.validate_regex(attrs.get("q", ""))
            except ValueError as exc:
                raise serializers.ValidationError({"q": str(exc)}) from exc
        elif len(attrs.get("q", "")) > 500:
            raise serializers.ValidationError({"q": "Query must be 500 characters or fewer."})
        if attrs.get("mode") == "regex" and len(attrs.get("q", "")) > MAX_REGEX_LENGTH:
            raise serializers.ValidationError(
                {"q": f"Regex query must be {MAX_REGEX_LENGTH} characters or fewer."}
            )
        try:
            SearchService.validate_pagination(attrs.get("page", 1), attrs.get("size", 20))
        except ValueError as exc:
            raise serializers.ValidationError({"page": str(exc)}) from exc
        return attrs


class SearchHitSerializer(serializers.Serializer):
    file_id = serializers.CharField()
    law_id = serializers.CharField(allow_blank=True, default="")
    law_name = serializers.CharField(allow_blank=True, default="")
    article_no = serializers.CharField(allow_blank=True, default="")
    paragraph_no = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    item_no = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    path = serializers.CharField()
    line = serializers.IntegerField()
    snippet = serializers.CharField()
    snippet_text = serializers.CharField()
    highlights = serializers.ListField(child=serializers.DictField(), default=list)
    url = serializers.CharField(allow_blank=True, default="")
    blocks = serializers.ListField(child=serializers.DictField(), default=list)


class SearchResponseSerializer(serializers.Serializer):
    hits = SearchHitSerializer(many=True)
    total = serializers.IntegerField()
    took_ms = serializers.IntegerField()
    query = serializers.DictField(required=False)
    index = serializers.DictField(required=False)
    debug = serializers.DictField(required=False)
