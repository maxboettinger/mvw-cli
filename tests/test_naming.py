from pathlib import Path

import pytest

from mvw.episodes import Episode
from mvw.models import MediathekResult
from mvw.naming import TemplateError, render, sanitize


def _ep(title="Einsatz in Bochum (S07/E05)", topic="Feuer und Flamme"):
    r = MediathekResult.from_api(
        {
            "channel": "WDR",
            "topic": topic,
            "title": title,
            "timestamp": 1568707200,
            "duration": 60,
            "url_video": "https://v.mp4",
            "id": "x",
        }
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
    ep = _ep(title="Berlin/Köln (S01/E03)", topic="Tatort: Köln/Bonn")
    p = render(ep, tier="high", ext="mp4")
    # With the default template ("{series} ({year})/Season {s:02d}/..."),
    # we expect exactly 3 parts after split: [series_dir, season_dir, filename]
    # If slashes were NOT scrubbed, we'd get extra parts like ["Tatort: Köln", "Bonn", ...]
    assert len(p.parts) == 3
    # Verify that slashes were replaced with spaces in the parts
    # The series part should contain the scrubbed topic (spaces instead of slashes)
    assert "Tatort" in p.parts[0] and "Bonn" in p.parts[0]
    assert "Season 07" in p.parts[1]
    # The filename should contain the scrubbed episode title (spaces instead of slashes)
    assert "Berlin" in p.parts[2] and "Köln" in p.parts[2]


def test_render_unknown_token_raises_template_error():
    with pytest.raises(TemplateError, match=r"\{serie\}"):
        render(_ep(), template="{serie}.{ext}", tier="high", ext="mp4")


def test_render_unknown_token_message_lists_valid_tokens():
    with pytest.raises(TemplateError, match=r"\{ep_title\}"):
        render(_ep(), template="{nope}", tier="high", ext="mp4")


def test_render_bad_format_spec_raises_template_error():
    with pytest.raises(TemplateError, match="invalid template"):
        render(_ep(), template="{s:02z}.{ext}", tier="high", ext="mp4")


def test_render_unbalanced_brace_raises_template_error():
    with pytest.raises(TemplateError, match="invalid template"):
        render(_ep(), template="{series", tier="high", ext="mp4")


def test_subtitle_dest_uses_url_suffix():
    from mvw.naming import subtitle_dest

    assert subtitle_dest(Path("a/b.mp4"), "https://x/y/sub.vtt") == Path("a/b.de.vtt")
    assert subtitle_dest(Path("a/b.mp4"), "https://x/y/sub.ttml?q=1") == Path("a/b.de.ttml")


def test_subtitle_dest_unknown_suffix_falls_back_to_ttml():
    from mvw.naming import subtitle_dest

    assert subtitle_dest(Path("a/b.mp4"), "https://x/y/sub.weird") == Path("a/b.de.ttml")
    assert subtitle_dest(Path("a/b.mp4"), "https://x/y/sub") == Path("a/b.de.ttml")
