from pathlib import Path

from mvw.episodes import Episode
from mvw.models import MediathekResult
from mvw.naming import DEFAULT_TEMPLATE, render, sanitize


def _ep(title="Einsatz in Bochum (S07/E05)", topic="Feuer und Flamme"):
    r = MediathekResult.from_api(
        {"channel": "WDR", "topic": topic, "title": title,
         "timestamp": 1568707200, "duration": 60, "url_video": "https://v.mp4", "id": "x"}
    )
    return Episode(result=r, season=7, episode=5)


def test_sanitize_removes_illegal_chars():
    assert sanitize('a/b:c?"<>|') == "a b c"
    assert sanitize("trailing.  ") == "trailing"


def test_render_default_template_plex_layout():
    p = render(_ep(), tier="high", ext="mp4")
    assert p == Path(
        "Feuer und Flamme (2019)/Season 07/"
        "Feuer und Flamme (2019) - s07e05 - Einsatz in Bochum [1080p].mp4"
    )


def test_render_custom_template():
    tmpl = "{series}.{year}.S{s:02d}E{e:02d}.{res}.{ext}"
    p = render(_ep(), template=tmpl, tier="medium", ext="mp4")
    assert p == Path("Feuer und Flamme.2019.S07E05.720p.mp4")


def test_render_prevents_path_injection_in_token_values():
    """Slashes in series/title must not create extra directory levels."""
    ep = _ep(
        title="Berlin/Köln (S01/E03)",
        topic="Tatort: Köln/Bonn"
    )
    p = render(ep, tier="high", ext="mp4")
    # With the default template "{series} ({year})/Season {s:02d}/{series} ({year}) - s{s:02d}e{e:02d} - {ep_title} [{res}].{ext}",
    # we expect exactly 3 parts after split: [series_dir, season_dir, filename]
    # If slashes were NOT scrubbed, we'd get extra parts like ["Tatort: Köln", "Bonn", ...]
    assert len(p.parts) == 3
    # Verify that slashes were replaced with spaces in the parts
    # The series part should contain the scrubbed topic (spaces instead of slashes)
    assert "Tatort" in p.parts[0] and "Bonn" in p.parts[0]
    assert "Season 07" in p.parts[1]
    # The filename should contain the scrubbed episode title (spaces instead of slashes)
    assert "Berlin" in p.parts[2] and "Köln" in p.parts[2]
