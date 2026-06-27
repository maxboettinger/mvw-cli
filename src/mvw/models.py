from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

_TIER_TO_FIELD = {"high": "url_video_hd", "medium": "url_video", "low": "url_video_low"}
_FALLBACK_ORDER = {
    "best": ["high", "medium", "low"],
    "high": ["high", "medium", "low"],
    "medium": ["medium", "low", "high"],
    "low": ["low", "medium", "high"],
}


@dataclass
class MediathekResult:
    channel: str
    topic: str
    title: str
    description: str
    timestamp: int
    duration: int
    size: int
    url_website: str
    url_subtitle: str
    url_video: str
    url_video_low: str
    url_video_hd: str
    filmliste_timestamp: str
    id: str

    @classmethod
    def from_api(cls, d: dict) -> "MediathekResult":
        g = d.get
        return cls(
            channel=g("channel", "") or "",
            topic=g("topic", "") or "",
            title=g("title", "") or "",
            description=g("description", "") or "",
            timestamp=int(g("timestamp", 0) or 0),
            duration=int(g("duration", 0) or 0),
            size=int(g("size", 0) or 0),
            url_website=g("url_website", "") or "",
            url_subtitle=g("url_subtitle", "") or "",
            url_video=g("url_video", "") or "",
            url_video_low=g("url_video_low", "") or "",
            url_video_hd=g("url_video_hd", "") or "",
            filmliste_timestamp=str(g("filmlisteTimestamp", "") or ""),
            id=str(g("id", "") or ""),
        )

    @property
    def aired(self) -> datetime:
        return datetime.fromtimestamp(self.timestamp, tz=timezone.utc)

    @property
    def duration_human(self) -> str:
        s = self.duration
        h, rem = divmod(s, 3600)
        m, sec = divmod(rem, 60)
        if h:
            return f"{h}:{m:02d}:{sec:02d}"
        return f"{m}:{sec:02d}"

    @property
    def size_human(self) -> str:
        n = float(self.size)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if n < 1024 or unit == "TB":
                return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
            n /= 1024
        return f"{n:.1f} TB"

    def resolution_present(self, tier: str) -> bool:
        return bool(getattr(self, _TIER_TO_FIELD[tier], ""))

    @property
    def resolutions(self) -> list[str]:
        return [t for t in ("low", "medium", "high") if self.resolution_present(t)]

    def resolve_video(self, preference: str) -> tuple[str | None, str | None]:
        for tier in _FALLBACK_ORDER.get(preference, _FALLBACK_ORDER["best"]):
            url = getattr(self, _TIER_TO_FIELD[tier], "")
            if url:
                return url, tier
        return None, None


@dataclass
class QueryInfo:
    total_results: int
    result_count: int
    search_engine_time: float
    filmliste_timestamp: str

    @classmethod
    def from_api(cls, d: dict) -> "QueryInfo":
        return cls(
            total_results=int(d.get("totalResults", 0) or 0),
            result_count=int(d.get("resultCount", 0) or 0),
            search_engine_time=float(d.get("searchEngineTime", 0) or 0),
            filmliste_timestamp=str(d.get("filmlisteTimestamp", "") or ""),
        )


@dataclass
class QueryResult:
    results: list[MediathekResult]
    query_info: QueryInfo
