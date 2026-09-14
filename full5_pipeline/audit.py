"""Strict JSON decoding and lossless field inventory; no automatic feature approval."""
from __future__ import annotations

import json
import math
from collections import Counter
from typing import Any

MAX_BYTES = 20 * 1024 * 1024
MAX_DEPTH = 64
MAX_NODES = 250_000
SOURCES = frozenset({"MATCH", "LEAGUE", "FORM", "TABLE", "PLAYER"})


class DataError(ValueError):
    """Safe error message: never includes raw payload or credentials."""


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise DataError("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _constant(value):
    raise DataError("NONFINITE_JSON_NUMBER")


def decode(raw: bytes) -> Any:
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_BYTES:
        raise DataError("INVALID_PAYLOAD_SIZE")
    try:
        value = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_object,
                           parse_constant=_constant)
    except DataError:
        raise
    except (UnicodeError, ValueError, RecursionError):
        raise DataError("INVALID_JSON") from None
    if not isinstance(value, (dict, list)) or not value:
        raise DataError("EMPTY_OR_SCALAR_PAYLOAD")
    # Validate finite numbers, nesting and node budget before downstream use.
    list(leaves(value))
    return value


def _escape(key: str) -> str:
    return key.replace("~", "~0").replace("/", "~1")


def leaves(value):
    """Iterative JSON Pointer traversal, including nulls and empty containers."""
    stack = [("", value, 0)]
    count = 0
    while stack:
        pointer, node, depth = stack.pop()
        count += 1
        if depth > MAX_DEPTH or count > MAX_NODES:
            raise DataError("PAYLOAD_COMPLEXITY_LIMIT")
        if isinstance(node, float) and not math.isfinite(node):
            raise DataError("NONFINITE_JSON_NUMBER")
        if isinstance(node, dict) and node:
            for key, child in reversed(list(node.items())):
                stack.append((pointer + "/" + _escape(key), child, depth + 1))
        elif isinstance(node, list) and node:
            for index in reversed(range(len(node))):
                stack.append((pointer + "/" + str(index), node[index], depth + 1))
        else:
            yield pointer, node


def inventory(source: str, raw: bytes) -> dict:
    if source not in SOURCES:
        raise DataError("UNKNOWN_SOURCE")
    rows = []
    for pointer, value in leaves(decode(raw)):
        # Exact field mappings must be reviewed against real source schemas.
        # Never treat a numeric field as a safe pre-match feature by default.
        kind = ("null" if value is None else "boolean" if isinstance(value, bool)
                else "number" if isinstance(value, (int, float))
                else "string" if isinstance(value, str)
                else "empty_array" if isinstance(value, list) else "empty_object")
        rows.append({"source": source, "pointer": pointer, "type": kind,
                     "missing": value is None, "status": "PENDING_SCHEMA_REVIEW",
                     "reason": "Exact semantic and temporal mapping required"})
    return {"source": source, "leaf_count": len(rows),
            "type_counts": dict(Counter(row["type"] for row in rows)),
            "fields": rows, "approved_feature_count": 0}
