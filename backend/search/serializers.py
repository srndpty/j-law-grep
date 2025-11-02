from __future__ import annotations

from typing import Any, Dict

from rest_framework import serializers


class SearchFiltersField(serializers.DictField):
    child = serializers.CharField(allow_blank=True, required=False)

    def to_internal_value(self, data: Any) -> Dict[str, str]:
        value = super().to_internal_value(data)
        return {key: val for key, val in value.items() if val != ""}


class SearchRequestSerializer(serializers.Serializer):
    q = serializers.CharField()
    mode = serializers.ChoiceField(choices=["literal", "regex"], default="literal")
    filters = SearchFiltersField(required=False, default=dict)
    size = serializers.IntegerField(min_value=1, max_value=100, default=20)
    page = serializers.IntegerField(min_value=1, default=1)


class SearchHitSerializer(serializers.Serializer):
    file_id = serializers.CharField()
    path = serializers.CharField()
    line = serializers.IntegerField()
    snippet = serializers.CharField()
    url = serializers.CharField(allow_blank=True, default="")
    blocks = serializers.ListField(child=serializers.DictField(), default=list)


class SearchResponseSerializer(serializers.Serializer):
    hits = SearchHitSerializer(many=True)
    total = serializers.IntegerField()
    took_ms = serializers.IntegerField()
