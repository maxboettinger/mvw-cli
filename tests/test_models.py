from datetime import datetime, timezone

from mvw.models import MediathekResult, QueryInfo


def _sample(**over):
    base = dict(
        channel="WDR", topic="Feuer und Flamme", title="Folge 5",
        description="d", timestamp=1568707200, duration=2700, size=1_288_490_188,
        url_website="https://w", url_subtitle="https://s.xml",
        url_video="https://v.mp4", url_video_low="https://low.mp4",
        url_video_hd="https://hd.mp4", filmlisteTimestamp="1568800000", id="abc",
    )
    base.update(over)
    return base


def test_from_api_and_humanizers():
    r = MediathekResult.from_api(_sample())
    assert r.topic == "Feuer und Flamme"
    assert r.aired == datetime(2019, 9, 17, 8, 0, tzinfo=timezone.utc)
    assert r.duration_human == "45:00"
    assert r.size_human == "1.2 GB"


def test_resolve_best_prefers_hd_then_falls_back():
    r = MediathekResult.from_api(_sample())
    assert r.resolve_video("best") == ("https://hd.mp4", "high")
    r2 = MediathekResult.from_api(_sample(url_video_hd=""))
    assert r2.resolve_video("best") == ("https://v.mp4", "medium")
    r3 = MediathekResult.from_api(_sample(url_video_hd="", url_video=""))
    assert r3.resolve_video("high") == ("https://low.mp4", "low")
    assert r3.resolution_present("high") is False


def test_query_info_from_api():
    qi = QueryInfo.from_api(
        {"totalResults": 342, "resultCount": 15,
         "searchEngineTime": "12.34", "filmlisteTimestamp": "1568800000"}
    )
    assert qi.total_results == 342
    assert qi.search_engine_time == 12.34
