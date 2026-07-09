from pathlib import Path

import httpx
import pytest
import respx

from mvw.download import (
    DownloadError,
    download,
    download_hls,
    is_hls,
    pick_resolution,
    remote_size,
    verify_size,
)
from mvw.models import MediathekResult


def _r(**over):
    base = dict(
        channel="WDR",
        topic="T",
        title="x",
        timestamp=1,
        duration=1,
        url_video="https://v/m.mp4",
        url_video_low="",
        url_video_hd="https://v/hd.mp4",
        id="1",
    )
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
        "https://x/playlist.m3u8",
        dest,
        ffmpeg=str(ffmpeg),
        on_progress=lambda d, t: seen.append((d, t)),
        poll_interval=0.1,
    )

    assert result == dest
    assert dest.read_bytes() == b"chunk-achunk-b"
    # HLS has no known total, so it is reported as indeterminate.
    assert seen and all(t is None for _, t in seen)
    # Final report reflects the fully-written file size.
    assert seen[-1][0] == len(b"chunk-achunk-b")


def test_download_hls_raises_on_ffmpeg_failure(tmp_path: Path):
    ffmpeg = _fake_ffmpeg(tmp_path, rc=1)
    dest = tmp_path / "out.mkv"
    with pytest.raises(DownloadError, match="ffmpeg failed"):
        download_hls("https://x/playlist.m3u8", dest, ffmpeg=str(ffmpeg))
    assert not dest.exists()
    assert not dest.with_name("out.mkv.part").exists()


def test_verify_size_missing_file(tmp_path):
    assert verify_size(tmp_path / "nope.mp4", 10) is False


def test_verify_size_zero_byte_file(tmp_path):
    f = tmp_path / "empty.mp4"
    f.write_bytes(b"")
    assert verify_size(f, 10) is False
    # expected<=0 path also rejects an empty file
    assert verify_size(f, 0) is False


def test_verify_size_exact_match(tmp_path):
    f = tmp_path / "ok.mp4"
    f.write_bytes(b"0123456789")  # 10 bytes
    assert verify_size(f, 10) is True


def test_verify_size_off_by_one_mismatch(tmp_path):
    f = tmp_path / "bad.mp4"
    f.write_bytes(b"012345678")  # 9 bytes
    assert verify_size(f, 10) is False
    assert verify_size(f, 10, tolerance=1) is True


def test_verify_size_unknown_expected_accepts_nonempty(tmp_path):
    f = tmp_path / "hls.mkv"
    f.write_bytes(b"x")
    assert verify_size(f, 0) is True
    assert verify_size(f, -1) is True


class _ShortStream(httpx.SyncByteStream):
    """Yields fewer bytes than the caller's expected_size, with no length header."""

    def __iter__(self):
        yield b"hello"  # 5 bytes

    def close(self):
        pass


@respx.mock
def test_download_raises_when_short_of_expected_size(tmp_path: Path):
    respx.get("https://v/m.mp4").mock(return_value=httpx.Response(200, stream=_ShortStream()))
    dest = tmp_path / "out.mp4"
    with pytest.raises(DownloadError, match="size mismatch"):
        download("https://v/m.mp4", dest, expected_size=11)
    assert not dest.exists()
    assert not dest.with_name("out.mp4.part").exists()


@respx.mock
def test_download_restarts_when_remote_total_differs(tmp_path: Path):
    dest = tmp_path / "out.mp4"
    part = dest.with_name("out.mp4.part")
    part.write_bytes(b"OLDOLD")  # 6 stale bytes from a previous run

    seen_ranges: list[str | None] = []

    def handler(request):
        rng = request.headers.get("range")
        seen_ranges.append(rng)
        if rng is not None:
            # Resume attempt: server reports a different total (11) than the
            # caller's expected_size (20) -> remote changed, must restart.
            return httpx.Response(
                206,
                content=b"world",
                headers={"content-range": "bytes 6-10/11", "content-length": "5"},
            )
        # Restart attempt: full file from byte 0.
        return httpx.Response(200, content=b"hello world", headers={"content-length": "11"})

    respx.get("https://v/m.mp4").mock(side_effect=handler)
    download("https://v/m.mp4", dest, expected_size=20)

    assert dest.read_bytes() == b"hello world"
    assert seen_ranges == ["bytes=6-", None]  # tried resume, then restarted clean
    assert not part.exists()


@respx.mock
def test_download_resume_continues_on_valid_206(tmp_path: Path):
    dest = tmp_path / "out.mp4"
    part = dest.with_name("out.mp4.part")
    part.write_bytes(b"hello ")  # 6 bytes already present

    def handler(request):
        assert request.headers["range"] == "bytes=6-"
        return httpx.Response(
            206,
            content=b"world",
            headers={"content-range": "bytes 6-10/11", "content-length": "5"},
        )

    respx.get("https://v/m.mp4").mock(side_effect=handler)
    # expected_size matches the server's total (11), so the resume guard stays
    # inert and the partial is continued, not restarted.
    download("https://v/m.mp4", dest, expected_size=11)
    assert dest.read_bytes() == b"hello world"
    assert not part.exists()


@respx.mock
def test_remote_size_from_head(tmp_path: Path):
    respx.head("https://v/m.mp4").mock(
        return_value=httpx.Response(200, headers={"content-length": "4242"})
    )
    assert remote_size("https://v/m.mp4") == 4242


@respx.mock
def test_remote_size_falls_back_to_range_when_head_unsupported():
    respx.head("https://v/m.mp4").mock(return_value=httpx.Response(405))
    respx.get("https://v/m.mp4").mock(
        return_value=httpx.Response(206, headers={"content-range": "bytes 0-0/9001"})
    )
    assert remote_size("https://v/m.mp4") == 9001


@respx.mock
def test_remote_size_none_when_unknown():
    respx.head("https://v/m.mp4").mock(return_value=httpx.Response(200))  # no length
    respx.get("https://v/m.mp4").mock(return_value=httpx.Response(200))  # ignores range
    assert remote_size("https://v/m.mp4") is None


@respx.mock
def test_remote_size_none_on_network_error():
    respx.head("https://v/m.mp4").mock(side_effect=httpx.ConnectError("boom"))
    respx.get("https://v/m.mp4").mock(side_effect=httpx.ConnectError("boom"))
    assert remote_size("https://v/m.mp4") is None


@respx.mock
def test_download_ignores_malformed_content_length(tmp_path: Path):
    respx.get("https://v/m.mp4").mock(
        return_value=httpx.Response(200, content=b"data", headers={"content-length": "garbage"})
    )
    dest = tmp_path / "out.mp4"
    download("https://v/m.mp4", dest)  # must not raise ValueError
    assert dest.read_bytes() == b"data"


def test_download_hls_stall_timeout_kills_ffmpeg(tmp_path: Path):
    script = tmp_path / "stalling_ffmpeg"
    script.write_text("#!/bin/sh\nsleep 30\n")  # writes nothing, would hang
    script.chmod(0o755)
    dest = tmp_path / "out.mkv"
    import time

    start = time.monotonic()
    with pytest.raises(DownloadError, match="stalled"):
        download_hls(
            "https://x/playlist.m3u8",
            dest,
            ffmpeg=str(script),
            poll_interval=0.05,
            stall_timeout=0.3,
        )
    assert time.monotonic() - start < 10  # killed, did not wait for the sleep
    assert not dest.exists()
    assert not dest.with_name("out.mkv.part").exists()
