from __future__ import annotations

import re

from mvw.models import MediathekResult

_VARIANT_MARKERS = [
    r"\(?audiodeskription\)?",
    r"\(?mit geb(ä|ae)rdensprache\)?",
    r"\(?geb(ä|ae)rdensprache\)?",
    r"\(?h(ö|oe)rfassung\)?",
]
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_WS = re.compile(r"\s+")


def normalize_title(title: str) -> str:
    t = title.lower()
    for marker in _VARIANT_MARKERS:
        t = re.sub(marker, " ", t)
    t = _PUNCT.sub(" ", t)
    return _WS.sub(" ", t).strip()


def compile_patterns(patterns: list[str]) -> list[re.Pattern[str]]:
    """Compile --exclude regexes, raising ValueError with a user-facing message."""
    compiled = []
    for p in patterns:
        try:
            compiled.append(re.compile(p, re.IGNORECASE))
        except re.error as exc:
            raise ValueError(f"invalid regex {p!r}: {exc}") from exc
    return compiled


def exclude(results: list[MediathekResult], patterns: list[str]) -> list[MediathekResult]:
    if not patterns:
        return list(results)
    compiled = compile_patterns(patterns)
    kept = []
    for r in results:
        haystack = f"{r.title}\n{r.topic}\n{r.description}"
        if any(c.search(haystack) for c in compiled):
            continue
        kept.append(r)
    return kept


def _score(r: MediathekResult) -> tuple[int, int]:
    return (len(r.resolutions), r.duration)


def dedup(results: list[MediathekResult]) -> list[MediathekResult]:
    best: dict[str, MediathekResult] = {}
    order: list[str] = []
    for r in results:
        key = f"{r.topic.lower().strip()}|{normalize_title(r.title)}"
        if key not in best:
            best[key] = r
            order.append(key)
        elif _score(r) > _score(best[key]):
            best[key] = r
    return [best[k] for k in order]


def latest_season(results: list[MediathekResult]) -> list[MediathekResult]:
    from mvw.episodes import parse_se

    seasons = []
    for r in results:
        season, _ = parse_se(r.title)
        seasons.append(season)
    detected = [s for s in seasons if s is not None]
    if not detected:
        return list(results)
    top = max(detected)
    return [r for r, s in zip(results, seasons, strict=True) if s == top]
