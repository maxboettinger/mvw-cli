from __future__ import annotations

import json
import time
from collections.abc import Iterator

import httpx

from mvw import __version__
from mvw.models import MediathekResult, QueryInfo, QueryResult


class MediathekError(Exception):
    """Raised on API errors, HTTP failures, or transport errors."""


class MediathekClient:
    def __init__(
        self,
        user_agent: str = f"mvw/{__version__}",
        timeout: float = 30.0,
        retries: int = 2,
        base_url: str = "https://mediathekviewweb.de/api/query",
        backoff_base: float = 0.5,
    ) -> None:
        self.user_agent = user_agent
        self.timeout = timeout
        self.retries = retries
        self.base_url = base_url
        self.backoff_base = backoff_base

    def query(self, payload: dict) -> QueryResult:
        headers = {"Content-Type": "text/plain", "User-Agent": self.user_agent}
        body = json.dumps(payload)
        last_err = ""
        for attempt in range(self.retries + 1):
            if attempt and self.backoff_base:
                time.sleep(self.backoff_base * 2 ** (attempt - 1))
            try:
                resp = httpx.post(
                    self.base_url, content=body, headers=headers, timeout=self.timeout
                )
            except httpx.TransportError as exc:
                last_err = f"network error: {exc}"
                continue
            # Server-side errors are usually transient; retry them. Other
            # non-200 statuses (auth, bad request) will not improve on retry.
            if resp.status_code >= 500:
                last_err = f"HTTP {resp.status_code}: {resp.text[:200]}"
                continue
            if resp.status_code != 200:
                raise MediathekError(f"HTTP {resp.status_code}: {resp.text[:200]}")
            try:
                data = resp.json()
            except ValueError as exc:
                raise MediathekError(f"invalid response from API: {exc}") from exc
            err = data.get("err")
            if err:
                raise MediathekError("; ".join(str(e) for e in err))
            result = data.get("result") or {}
            results = [MediathekResult.from_api(r) for r in result.get("results", [])]
            info = QueryInfo.from_api(result.get("queryInfo", {}))
            return QueryResult(results=results, query_info=info)
        raise MediathekError(f"request failed after {self.retries + 1} attempts: {last_err}")

    def iter_all(
        self, payload: dict, page_size: int = 50, cap: int | None = None
    ) -> Iterator[MediathekResult]:
        offset = int(payload.get("offset", 0))
        yielded = 0
        while True:
            page = dict(payload, offset=offset, size=page_size)
            result = self.query(page)
            if not result.results:
                return
            for row in result.results:
                yield row
                yielded += 1
                if cap is not None and yielded >= cap:
                    return
            offset += len(result.results)
            if offset >= result.query_info.total_results:
                return
