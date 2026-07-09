import json

import httpx
import pytest
import respx

from mvw.api import MediathekClient, MediathekError

URL = "https://mediathekviewweb.de/api/query"


def _resp(results, total):
    return {
        "result": {
            "results": results,
            "queryInfo": {
                "totalResults": total,
                "resultCount": len(results),
                "searchEngineTime": "1.0",
                "filmlisteTimestamp": "1",
            },
        },
        "err": None,
    }


def _row(i):
    return {
        "channel": "WDR",
        "topic": "T",
        "title": f"E{i}",
        "timestamp": 1000 + i,
        "duration": 60,
        "size": 1,
        "url_video": f"https://v/{i}.mp4",
        "id": str(i),
    }


@respx.mock
def test_query_sends_text_plain_body_and_parses():
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=_resp([_row(1)], 1)))
    client = MediathekClient(user_agent="mvw/test")
    result = client.query({"queries": [], "size": 15})
    req = route.calls.last.request
    assert req.headers["content-type"].startswith("text/plain")
    assert req.headers["user-agent"] == "mvw/test"
    assert json.loads(req.content)["size"] == 15
    assert result.query_info.total_results == 1
    assert result.results[0].title == "E1"


@respx.mock
def test_query_raises_on_err():
    respx.post(URL).mock(return_value=httpx.Response(200, json={"result": None, "err": ["boom"]}))
    with pytest.raises(MediathekError, match="boom"):
        MediathekClient().query({"queries": []})


@respx.mock
def test_iter_all_paginates_until_total():
    pages = {0: _resp([_row(1), _row(2)], 3), 2: _resp([_row(3)], 3)}

    def handler(request):
        offset = json.loads(request.content)["offset"]
        return httpx.Response(200, json=pages[offset])

    respx.post(URL).mock(side_effect=handler)
    client = MediathekClient()
    got = list(client.iter_all({"queries": [], "offset": 0, "size": 15}, page_size=2))
    assert [r.id for r in got] == ["1", "2", "3"]


@respx.mock
def test_query_invalid_json_raises_mediathek_error():
    respx.post(URL).mock(return_value=httpx.Response(200, text="<html>gateway error</html>"))
    with pytest.raises(MediathekError, match="invalid response"):
        MediathekClient(backoff_base=0).query({"queries": []})


@respx.mock
def test_query_retries_5xx_then_succeeds():
    route = respx.post(URL).mock(
        side_effect=[
            httpx.Response(502),
            httpx.Response(200, json=_resp([_row(1)], 1)),
        ]
    )
    result = MediathekClient(backoff_base=0).query({"queries": []})
    assert route.call_count == 2
    assert result.results[0].id == "1"


@respx.mock
def test_query_5xx_exhausts_retries():
    route = respx.post(URL).mock(return_value=httpx.Response(503))
    with pytest.raises(MediathekError, match="HTTP 503"):
        MediathekClient(retries=1, backoff_base=0).query({"queries": []})
    assert route.call_count == 2


@respx.mock
def test_query_4xx_fails_immediately_without_retry():
    route = respx.post(URL).mock(return_value=httpx.Response(400, text="bad"))
    with pytest.raises(MediathekError, match="HTTP 400"):
        MediathekClient(retries=3, backoff_base=0).query({"queries": []})
    assert route.call_count == 1


@respx.mock
def test_query_retries_transport_error_then_succeeds():
    route = respx.post(URL).mock(
        side_effect=[
            httpx.ConnectError("boom"),
            httpx.Response(200, json=_resp([_row(1)], 1)),
        ]
    )
    result = MediathekClient(backoff_base=0).query({"queries": []})
    assert route.call_count == 2
    assert result.query_info.total_results == 1
