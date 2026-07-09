from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit

from mvw.episodes import Episode, clean_episode_title

DEFAULT_TEMPLATE = (
    "{series} ({year})/Season {s:02d}/"
    "{series} ({year}) - s{s:02d}e{e:02d} - {ep_title} [{res}].{ext}"
)
RES_LABELS = {"high": "1080p", "medium": "720p", "low": "480p"}
TEMPLATE_TOKENS = ("series", "year", "s", "e", "ep_title", "res", "channel", "date", "ext")


class TemplateError(ValueError):
    """User-supplied filename template is invalid; the message is user-facing."""


_ILLEGAL = re.compile(r'[/\\:*?"<>|]')
_WS = re.compile(r"\s+")
_SUBTITLE_SUFFIXES = {".ttml", ".xml", ".vtt", ".srt"}


def subtitle_dest(dest: Path, sub_url: str) -> Path:
    """Sidecar subtitle path next to the video, e.g. ``X.mp4`` -> ``X.de.ttml``.

    The ``.de`` language tag is what Plex/Jellyfin parse; MVW indexes German
    public broadcasting, so German is the only language on offer. The extension
    follows the subtitle URL when recognizable, defaulting to TTML (the format
    the broadcasters actually serve).
    """
    suffix = Path(urlsplit(sub_url).path).suffix.lower()
    if suffix not in _SUBTITLE_SUFFIXES:
        suffix = ".ttml"
    return dest.with_suffix(f".de{suffix}")


def sanitize(component: str) -> str:
    s = _ILLEGAL.sub(" ", component)
    s = _WS.sub(" ", s).strip()
    s = s.rstrip(". ")
    return s[:150]


def render(episode: Episode, *, template: str = DEFAULT_TEMPLATE, tier: str, ext: str) -> Path:
    r = episode.result
    # A zero timestamp means "no broadcast date": render "unknown" rather than
    # the misleading epoch values 1970 / 1970-01-01.
    dated = r.timestamp > 0
    values: dict[str, str | int] = {
        "series": r.topic,
        "year": r.aired.year if dated else "unknown",
        "s": episode.season,
        "e": episode.episode,
        "ep_title": clean_episode_title(r.title),
        "res": RES_LABELS.get(tier, tier),
        "channel": r.channel,
        "date": r.aired.strftime("%Y-%m-%d") if dated else "unknown",
        "ext": ext,
    }
    # Scrub path separators from string values to prevent path injection.
    # Integers (year, s, e) are left unchanged to preserve format specs like :02d.
    for key in ("series", "ep_title", "res", "channel", "date", "ext"):
        value = values[key]
        if isinstance(value, str):
            values[key] = value.replace("/", " ").replace("\\", " ")
    try:
        rendered = template.format(**values)
    except KeyError as exc:
        valid = ", ".join("{" + t + "}" for t in TEMPLATE_TOKENS)
        raise TemplateError(
            f"unknown template token {{{exc.args[0]}}}; valid tokens: {valid}"
        ) from exc
    except (ValueError, IndexError) as exc:
        raise TemplateError(f"invalid template {template!r}: {exc}") from exc
    parts = [sanitize(p) for p in rendered.split("/") if p]
    return Path(*parts)
