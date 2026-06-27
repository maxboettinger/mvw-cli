from __future__ import annotations

import json
from collections.abc import Iterator

import httpx

from mvw.models import MediathekResult, QueryInfo, QueryResult


class MediathekError(Exception):
    """Raised on API errors, HTTP failures, or transport errors."""


class MediathekClient:
    def __init__(
        self,
        user_agent: str = "mvw/0.1.0",
        timeout: float = 30.0,
        retries: int = 2,
        base_url: str = "https://mediathekviewweb.de/api/query",
    ) -> None:
        self.user_agent = user_agent
        self.timeout = timeout
        self.retries = retries
        self.base_url = base_url

    def query(self, payload: dict) -> QueryResult:
        headers = {"Content-Type": "text/plain", "User-Agent": self.user_agent}
        body = json.dumps(payload)
        transport_err: Exception | None = None
        for _ in range(self.retries + 1):
            try:
                resp = httpx.post(
                    self.base_url, content=body, headers=headers, timeout=self.timeout
                )
            except httpx.TransportError as exc:
                transport_err = exc
                continue
            if resp.status_code != 200:
                raise MediathekError(f"HTTP {resp.status_code}: {resp.text[:200]}")
            data = resp.json()
            err = data.get("err")
            if err:
                raise MediathekError("; ".join(str(e) for e in err))
            result = data.get("result") or {}
            results = [MediathekResult.from_api(r) for r in result.get("results", [])]
            info = QueryInfo.from_api(result.get("queryInfo", {}))
            return QueryResult(results=results, query_info=info)
        raise MediathekError(f"network error: {transport_err}")

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
