from mvw.episodes import Episode, assign, group_by_season, parse_se
from mvw.models import MediathekResult


def _r(title, ts=1568707200):  # 2019-09-17
    return MediathekResult.from_api(
        {
            "channel": "WDR",
            "topic": "Feuer und Flamme",
            "title": title,
            "timestamp": ts,
            "duration": 60,
            "url_video": "https://v.mp4",
            "id": title,
        }
    )


def test_parse_se_patterns():
    assert parse_se("Feuer und Flamme (S07/E05)") == (7, 5)
    assert parse_se("Staffel 7, Folge 5") == (7, 5)
    assert parse_se("Folge 12") == (None, 12)
    assert parse_se("Der Titel (123)") == (None, 123)
    assert parse_se("Kein Muster hier") == (None, None)


def test_assign_uses_explicit_then_year_and_order():
    rows = [
        _r("Folge 2", ts=1568707200),
        _r("Folge 1", ts=1568707100),
        _r("Ohne Nummer", ts=1568707300),
    ]
    eps = assign(rows)
    by_title = {e.result.title: e for e in eps}
    assert by_title["Folge 1"].episode == 1
    assert by_title["Folge 2"].episode == 2
    assert by_title["Ohne Nummer"].episode == 3  # next free in date order
    assert all(e.season == 2019 for e in eps)  # year fallback


def test_season_override():
    eps = assign([_r("Folge 1")], season_override=7)
    assert eps[0].season == 7


def test_group_by_season_sorted():
    eps = [Episode(_r("a"), 7, 2), Episode(_r("b"), 7, 1), Episode(_r("c"), 6, 1)]
    grouped = group_by_season(eps)
    assert list(grouped.keys()) == [6, 7]
    assert [e.episode for e in grouped[7]] == [1, 2]
