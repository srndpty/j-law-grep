from __future__ import annotations

import shlex
from dataclasses import dataclass


@dataclass
class BooleanQuery:
    required: list[str]
    optional_groups: list[list[str]]
    excluded: list[str]


def parse_boolean_query(query: str) -> BooleanQuery:
    lexer = shlex.shlex(query, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    tokens = list(lexer)

    required: list[str] = []
    optional_groups: list[list[str]] = []
    excluded: list[str] = []
    current_or_group: list[str] = []
    in_or = False

    for token in tokens:
        if token == "|":
            if required:
                current_or_group.append(required.pop())
            in_or = True
            continue
        if token.startswith("-") and len(token) > 1:
            excluded.append(token[1:])
            continue
        if in_or:
            current_or_group.append(token)
            in_or = False
            continue
        if current_or_group:
            optional_groups.append(current_or_group)
            current_or_group = []
        required.append(token)

    if current_or_group:
        optional_groups.append(current_or_group)

    return BooleanQuery(required=required, optional_groups=optional_groups, excluded=excluded)
