from __future__ import annotations

_PREFIX_FIELD = {"!": "channel", "#": "topic", "+": "title", "*": "description"}


def parse_raw(raw: str) -> tuple[list[dict], int | None, int | None]:
    """Translate the MVW query-string grammar into API query dicts.

    Same selector repeated -> OR (values joined by space, MVW's OR semantics).
    Bare words -> default topic+title field. `>N`/`<N` are duration in minutes.
    Topic prefixes collect immediately following bare words; other prefixes do not.
    """
    by_field: dict[str, list[str]] = {}
    bare: list[str] = []
    dur_min: int | None = None
    dur_max: int | None = None

    tokens = raw.split()
    i = 0

    while i < len(tokens):
        token = tokens[i]
        head = token[0] if token else ""

        if head == ">" and len(token) > 1 and token[1:].isdigit():
            dur_min = int(token[1:]) * 60
            i += 1
        elif head == "<" and len(token) > 1 and token[1:].isdigit():
            dur_max = int(token[1:]) * 60
            i += 1
        elif head in _PREFIX_FIELD and len(token) > 1:
            field = _PREFIX_FIELD[head]
            values = [token[1:]]
            i += 1
            # Topic prefix collects immediately following bare tokens
            if field == "topic":
                while i < len(tokens):
                    next_token = tokens[i]
                    next_head = next_token[0] if next_token else ""
                    # Stop if next token is a prefix or duration
                    if next_head in _PREFIX_FIELD and len(next_token) > 1:
                        break
                    if next_head in ('>', '<') and len(next_token) > 1 and next_token[1:].isdigit():
                        break
                    # This bare token follows topic prefix, collect it
                    values.append(next_token)
                    i += 1
            by_field.setdefault(field, []).extend(values)
        else:
            bare.append(token)
            i += 1

    queries: list[dict] = []
    for field, values in by_field.items():
        queries.append({"fields": [field], "query": " ".join(values)})
    if bare:
        queries.append({"fields": ["topic", "title"], "query": " ".join(bare)})
    return queries, dur_min, dur_max


def build_payload(
    raw: str | None = None,
    *,
    channel: str | None = None,
    topic: str | None = None,
    title: str | None = None,
    description: str | None = None,
    min_duration: int | None = None,
    max_duration: int | None = None,
    sort_by: str = "timestamp",
    sort_order: str = "desc",
    future: bool = False,
    offset: int = 0,
    size: int = 15,
) -> dict:
    queries: list[dict] = []
    dur_min = dur_max = None
    if raw:
        queries, dur_min, dur_max = parse_raw(raw)

    for field, value in (
        ("channel", channel), ("topic", topic),
        ("title", title), ("description", description),
    ):
        if value:
            queries.append({"fields": [field], "query": value})

    if min_duration is not None:
        dur_min = min_duration * 60
    if max_duration is not None:
        dur_max = max_duration * 60

    payload: dict = {
        "queries": queries,
        "sortBy": sort_by,
        "sortOrder": sort_order,
        "future": future,
        "offset": offset,
        "size": size,
    }
    if dur_min is not None:
        payload["duration_min"] = dur_min
    if dur_max is not None:
        payload["duration_max"] = dur_max
    return payload
