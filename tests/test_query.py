from mvw.query import build_payload, parse_raw


def test_parse_raw_prefixes_and_default_field():
    queries, dmin, dmax = parse_raw("!ARD #Tatort +Schokolade *Berlin feuer flamme")
    assert {"fields": ["channel"], "query": "ARD"} in queries
    assert {"fields": ["topic"], "query": "Tatort"} in queries
    assert {"fields": ["title"], "query": "Schokolade"} in queries
    assert {"fields": ["description"], "query": "Berlin"} in queries
    # bare words default to topic+title, combined into one query string
    assert {"fields": ["topic", "title"], "query": "feuer flamme"} in queries
    assert dmin is None and dmax is None


def test_parse_raw_repeated_selector_is_or():
    queries, _, _ = parse_raw("!ARD !ZDF")
    chan = [q for q in queries if q["fields"] == ["channel"]]
    assert len(chan) == 1
    assert chan[0]["query"] == "ARD ZDF"


def test_parse_raw_duration_minutes_to_seconds():
    _, dmin, dmax = parse_raw(">80 <120")
    assert dmin == 80 * 60
    assert dmax == 120 * 60


def test_build_payload_merges_flags_and_raw():
    p = build_payload("#Feuer und Flamme", channel="WDR", min_duration=20, size=50)
    assert {"fields": ["channel"], "query": "WDR"} in p["queries"]
    assert {"fields": ["topic"], "query": "Feuer und Flamme"} in p["queries"]
    assert p["duration_min"] == 1200
    assert p["size"] == 50
    assert p["sortBy"] == "timestamp"
    assert p["sortOrder"] == "desc"
    assert p["future"] is False
    assert p["offset"] == 0
