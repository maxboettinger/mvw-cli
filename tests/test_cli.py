import httpx
import respx
from typer.testing import CliRunner

import mvw.cli as cli
from mvw.download import FFmpegMissingError
from mvw.models import MediathekResult, QueryInfo, QueryResult

runner = CliRunner()


def _r(title, **over):
    base = dict(channel="WDR", topic="Feuer und Flamme", title=title,
                timestamp=1568707200, duration=2700, size=1,
                url_video="https://v.mp4", url_video_hd="https://hd.mp4", id=title)
    base.update(over)
    return MediathekResult.from_api(base)


class FakeClient:
    def __init__(self, rows):
        self.rows = rows

    def query(self, payload):
        return QueryResult(self.rows, QueryInfo(len(self.rows), len(self.rows), 1.0, ""))

    def iter_all(self, payload, page_size=50, cap=None):
        rows = self.rows if cap is None else self.rows[:cap]
        yield from rows


def test_search_renders_table(monkeypatch):
    monkeypatch.setattr(cli, "_make_client", lambda cfg: FakeClient([_r("Folge 5")]))
    result = runner.invoke(cli.app, ["search", "#Feuer und Flamme"])
    assert result.exit_code == 0
    assert "Feuer und Flamme" in result.stdout
    assert "of 1" in result.stdout


def test_download_dry_run_lists_plan(monkeypatch, tmp_path):
    rows = [_r("Feuer und Flamme (S07/E05)"), _r("Feuer und Flamme (S07/E06)")]
    monkeypatch.setattr(cli, "_make_client", lambda cfg: FakeClient(rows))
    result = runner.invoke(
        cli.app,
        ["download", "#Feuer und Flamme", "--season", "--dry-run", "--output", str(tmp_path)],
    )
    assert result.exit_code == 0
    assert "s07e05" in result.stdout
    assert "s07e06" in result.stdout


def test_download_missing_ffmpeg_exits_4(monkeypatch, tmp_path):
    rows = [_r("Feuer und Flamme (S07/E05)",
               url_video="https://cdn.example.com/stream.m3u8",
               url_video_hd="https://cdn.example.com/stream_hd.m3u8")]
    monkeypatch.setattr(cli, "_make_client", lambda cfg: FakeClient(rows))

    def _fake_download_hls(url, dest, **kwargs):
        raise FFmpegMissingError("ffmpeg not found on PATH")

    monkeypatch.setattr(cli, "download_hls", _fake_download_hls)
    result = runner.invoke(
        cli.app,
        ["download", "#Feuer und Flamme", "--output", str(tmp_path)],
    )
    assert result.exit_code == 4


def test_download_excludes_audiodeskription(monkeypatch, tmp_path):
    rows = [_r("Feuer und Flamme (S07/E05)"),
            _r("Feuer und Flamme (S07/E05) (Audiodeskription)")]
    monkeypatch.setattr(cli, "_make_client", lambda cfg: FakeClient(rows))
    result = runner.invoke(
        cli.app,
        ["download", "#Feuer und Flamme", "--season", "--dry-run",
         "--exclude", "Audiodeskription", "--output", str(tmp_path)],
    )
    assert result.exit_code == 0
    assert result.stdout.lower().count("s07e05") == 1


def test_real_mp4_download(monkeypatch, tmp_path):
    """Locks finding #1: download import alias prevents command shadowing."""
    rows = [_r("Feuer und Flamme (S07/E05)",
               url_video="https://example.test/v.mp4",
               url_video_hd="")]
    monkeypatch.setattr(cli, "_make_client", lambda cfg: FakeClient(rows))

    with respx.mock:
        respx.get("https://example.test/v.mp4").mock(
            return_value=httpx.Response(
                200, content=b"video-bytes",
                headers={"content-length": "11"},
            )
        )
        result = runner.invoke(
            cli.app,
            ["download", "#Feuer und Flamme", "--resolution", "medium",
             "--output", str(tmp_path)],
        )

    assert result.exit_code == 0
    mp4_files = list(tmp_path.rglob("*.mp4"))
    assert len(mp4_files) == 1
    assert mp4_files[0].read_bytes() == b"video-bytes"


def test_season_flag_gates_foldering(monkeypatch, tmp_path):
    """Locks finding #2: --season gates Plex folder structure vs flat output."""
    rows = [_r("Feuer und Flamme (S07/E05)"), _r("Feuer und Flamme (S07/E06)")]
    monkeypatch.setattr(cli, "_make_client", lambda cfg: FakeClient(rows))

    # With --season: full Plex path, Season 07 folder visible in dry-run output
    result_season = runner.invoke(
        cli.app,
        ["download", "#Feuer und Flamme", "--season", "--dry-run",
         "--output", str(tmp_path)],
    )
    assert result_season.exit_code == 0
    assert "Season 07" in result_season.stdout

    # Without --season: flat output, Season 07 must not appear, but s07e05 still in filename
    result_flat = runner.invoke(
        cli.app,
        ["download", "#Feuer und Flamme", "--dry-run", "--output", str(tmp_path)],
    )
    assert result_flat.exit_code == 0
    assert "Season 07" not in result_flat.stdout
    assert "s07e05" in result_flat.stdout.lower()


def test_overall_progress_counts_files_not_bytes():
    """Regression: the overall bar tracks a file count, so it must use a
    count column (MofN) and never byte/speed columns, which produced the
    bogus "10/10 bytes" / "0 bytes/s" display."""
    from rich.progress import (
        DownloadColumn, MofNCompleteColumn, TransferSpeedColumn,
    )

    overall, per_file, _ = cli._make_progress()

    assert any(isinstance(c, MofNCompleteColumn) for c in overall.columns)
    assert not any(
        isinstance(c, (DownloadColumn, TransferSpeedColumn)) for c in overall.columns
    )
    # Per-file bars are byte-based and keep the byte/speed columns.
    assert any(isinstance(c, DownloadColumn) for c in per_file.columns)
    assert any(isinstance(c, TransferSpeedColumn) for c in per_file.columns)
