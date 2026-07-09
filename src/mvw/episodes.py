from __future__ import annotations

import re
from dataclasses import dataclass

from mvw.models import MediathekResult

_SE = re.compile(r"S\s*(\d{1,2})\s*[ _/.\-]?\s*E\s*(\d{1,3})", re.IGNORECASE)
_STAFFEL_FOLGE = re.compile(r"Staffel\s*(\d{1,2}).*?Folge\s*(\d{1,3})", re.IGNORECASE)
_FOLGE = re.compile(r"\bFolge\s*(\d{1,3})\b", re.IGNORECASE)
_FOLGE_PRE = re.compile(r"\b(\d{1,3})\.\s*Folge\b", re.IGNORECASE)
_TRAILING_NUM = re.compile(r"\((\d{1,3})\)\s*$")


def parse_se(title: str) -> tuple[int | None, int | None]:
    m = _SE.search(title)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = _STAFFEL_FOLGE.search(title)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = _FOLGE.search(title) or _FOLGE_PRE.search(title)
    if m:
        return None, int(m.group(1))
    m = _TRAILING_NUM.search(title)
    if m:
        return None, int(m.group(1))
    return None, None


def clean_episode_title(title: str) -> str:
    t = _SE.sub("", title)
    t = _STAFFEL_FOLGE.sub("", t)
    t = _FOLGE.sub("", t)
    t = _TRAILING_NUM.sub("", t)
    t = re.sub(r"[\s\-–—:|()]+$", "", t)
    t = re.sub(r"^[\s\-–—:|()]+", "", t)
    return t.strip() or title.strip()


@dataclass
class Episode:
    result: MediathekResult
    season: int
    episode: int


def assign(results: list[MediathekResult], *, season_override: int | None = None) -> list[Episode]:
    parsed = [(r, *parse_se(r.title)) for r in results]

    # Resolve each row's season first.
    def season_of(r: MediathekResult, s: int | None) -> int:
        if season_override is not None:
            return season_override
        if s is not None:
            return s
        # No parsed season and no broadcast date: Season 00 (Plex "Specials")
        # instead of the misleading epoch year 1970.
        return r.aired.year if r.timestamp > 0 else 0

    enriched = [(r, season_of(r, s), e) for (r, s, e) in parsed]

    # Per-season episode numbering by timestamp order; explicit numbers win.
    episodes: list[Episode] = []
    by_season: dict[int, list[tuple[MediathekResult, int | None]]] = {}
    for r, season, e in enriched:
        by_season.setdefault(season, []).append((r, e))

    for season, rows in by_season.items():
        rows.sort(key=lambda re_: re_[0].timestamp)
        used = {e for _, e in rows if e is not None}
        counter = 0
        for r, e in rows:
            if e is None:
                counter += 1
                while counter in used:
                    counter += 1
                used.add(counter)
                num = counter
            else:
                num = e
                counter = max(counter, e)
            episodes.append(Episode(result=r, season=season, episode=num))
    return episodes


def group_by_season(episodes: list[Episode]) -> dict[int, list[Episode]]:
    grouped: dict[int, list[Episode]] = {}
    for ep in episodes:
        grouped.setdefault(ep.season, []).append(ep)
    return {season: sorted(grouped[season], key=lambda e: e.episode) for season in sorted(grouped)}
