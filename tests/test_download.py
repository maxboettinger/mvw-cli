from pathlib import Path

import httpx
import pytest
import respx

from mvw.download import DownloadError, download, download_hls, is_hls, pick_resolution
from mvw.models import MediathekResult


def _r(**over):
    base = dict(channel="WDR", topic="T", title="x", timestamp=1, duration=1,
                url_video="https://v/m.mp4", url_video_low="", url_video_hd="https://v/hd.mp4",
                id="1")
    base.update(over)
    return MediathekResult.from_api(base)


def test_is_hls():
    assert is_hls("https://x/playlist.m3u8")
    assert is_hls("https://x/playlist.m3u8?token=1")
    assert not is_hls("https://x/v.mp4")


def test_pick_resolution_best_and_missing():
    assert pick_resolution(_r(), "best") == ("https://v/hd.mp4", "high")
    with pytest.raises(DownloadError):
        pick_resolution(_r(url_video="", url_video_hd="", url_video_low=""), "best")


@respx.mock
def test_download_streams_and_renames(tmp_path: Path):
    respx.get("https://v/m.mp4").mock(
        return_value=httpx.Response(200, content=b"hello world", headers={"content-length": "11"})
    )
    dest = tmp_path / "out.mp4"
    seen = []
    result = download("https://v/m.mp4", dest, on_progress=lambda d, t: seen.append((d, t)))
    assert result == dest
    assert dest.read_bytes() == b"hello world"
    assert not dest.with_suffix(".mp4.part").exists()
    assert seen[-1][0] == 11


@respx.mock
def test_download_resumes_with_range(tmp_path: Path):
    dest = tmp_path / "out.mp4"
    part = dest.with_suffix(".mp4.part")
    part.write_bytes(b"hello ")  # 6 bytes already present

    def handler(request):
        assert request.headers["range"] == "bytes=6-"
        return httpx.Response(206, content=b"world", headers={"content-range": "bytes 6-10/11"})

    respx.get("https://v/m.mp4").mock(side_effect=handler)
    download("https://v/m.mp4", dest)
    assert dest.read_bytes() == b"hello world"


def _fake_ffmpeg(tmp_path: Path, *, sleep: float = 0.0, rc: int = 0) -> Path:
    """A stand-in 'ffmpeg' that writes growing bytes to its output (last arg)."""
    script = tmp_path / "fake_ffmpeg"
    script.write_text(
        "#!/bin/sh\n"
        'eval out="\\${$#}"\n'
        f"sleep {sleep}\n"
        'printf "chunk-a" > "$out"\n'
        'printf "chunk-b" >> "$out"\n'
        f"exit {rc}\n"
    )
    script.chmod(0o755)
    return script


def test_download_hls_reports_progress_and_writes_output(tmp_path: Path):
    ffmpeg = _fake_ffmpeg(tmp_path, sleep=0.6)  # outlive one poll tick
    dest = tmp_path / "out.mkv"
    seen: list[tuple[int, object]] = []

    result = download_hls(
        "https://x/playlist.m3u8", dest, ffmpeg=str(ffmpeg),
        on_progress=lambda d, t: seen.append((d, t)), poll_interval=0.1,
    )

    assert result == dest
    assert dest.read_bytes() == b"chunk-achunk-b"
    # HLS has no known total, so it is reported as indeterminate.
    assert seen and all(t is None for _, t in seen)
    # Final report reflects the fully-written file size.
    assert seen[-1][0] == len(b"chunk-achunk-b")


def test_download_hls_raises_on_ffmpeg_failure(tmp_path: Path):
    ffmpeg = _fake_ffmpeg(tmp_path, rc=1)
    with pytest.raises(DownloadError, match="ffmpeg failed"):
        download_hls("https://x/playlist.m3u8", tmp_path / "out.mkv", ffmpeg=str(ffmpeg))
