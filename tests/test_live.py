import pytest

from mvw.api import MediathekClient
from mvw.query import build_payload


@pytest.mark.live
def test_live_query_returns_results():
    client = MediathekClient(user_agent="mvw/test-live")
    result = client.query(build_payload("#Tagesschau", size=3))
    assert result.query_info.total_results > 0
    assert result.results
    assert result.results[0].url_video
