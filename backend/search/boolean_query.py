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
    try:
        tokens = list(lexer)
    except ValueError as exc:
        raise ValueError(f"Invalid boolean query: {exc}") from exc

    required: list[str] = []
    optional_groups: list[list[str]] = []
    excluded: list[str] = []
    current_or_group: list[str] = []
    in_or = False

    for token in tokens:
        if token in {"|", "OR"}:
            if required:
                current_or_group.append(required.pop())
            elif not current_or_group:
                raise ValueError("Invalid boolean query: OR must follow a term.")
            in_or = True
            continue
        if token == "-":
            raise ValueError("Invalid boolean query: '-' must be attached to a term.")
        if token.startswith("-") and len(token) > 1:
            excluded.append(token[1:])
            continue
        if in_or:
            if token in {"|", "OR"} or token.startswith("-"):
                raise ValueError("Invalid boolean query: OR must be followed by a term.")
            current_or_group.append(token)
            in_or = False
            continue
        if current_or_group:
            optional_groups.append(current_or_group)
            current_or_group = []
        required.append(token)

    if current_or_group:
        if in_or:
            raise ValueError("Invalid boolean query: OR must be followed by a term.")
        optional_groups.append(current_or_group)

    return BooleanQuery(required=required, optional_groups=optional_groups, excluded=excluded)
