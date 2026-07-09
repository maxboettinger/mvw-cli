from mvw.filters import dedup, exclude, latest_season, normalize_title
from mvw.models import MediathekResult


def _r(title, topic="Feuer und Flamme", **over):
    base = dict(
        channel="WDR",
        topic=topic,
        title=title,
        description="",
        timestamp=1000,
        duration=2700,
        size=1,
        url_website="",
        url_subtitle="",
        url_video="https://v.mp4",
        url_video_low="",
        url_video_hd="",
        filmlisteTimestamp="",
        id=title,
    )
    base.update(over)
    return MediathekResult.from_api(base)


def test_exclude_matches_title_case_insensitive():
    rows = [_r("Folge 5"), _r("Folge 5 (Audiodeskription)")]
    out = exclude(rows, ["audiodeskription"])
    assert [r.title for r in out] == ["Folge 5"]


def test_normalize_strips_variant_markers():
    assert normalize_title("Folge 5 (Audiodeskription)") == normalize_title("Folge 5")
    assert normalize_title("Folge 5 mit Gebärdensprache") == normalize_title("Folge 5")


def test_dedup_keeps_best_copy():
    plain = _r("Folge 5", url_video_hd="")  # 1 resolution
    hd = _r("Folge 5 (Audiodeskription)", url_video_hd="https://hd.mp4")  # 2 resolutions, dup title
    out = dedup([plain, hd])
    assert len(out) == 1
    assert out[0].url_video_hd == "https://hd.mp4"


def test_latest_season_keeps_max_season():
    s6 = _r("Feuer und Flamme (S06/E01)")
    s7a = _r("Feuer und Flamme (S07/E01)")
    s7b = _r("Feuer und Flamme (S07/E02)")
    out = latest_season([s6, s7a, s7b])
    assert {r.title for r in out} == {s7a.title, s7b.title}
