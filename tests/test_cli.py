import httpx
import respx
from typer.testing import CliRunner

import mvw.cli as cli
from mvw.download import FFmpegMissingError
from mvw.models import MediathekResult, QueryInfo, QueryResult

runner = CliRunner()


def _r(title, **over):
    base = dict(
        channel="WDR",
        topic="Feuer und Flamme",
        title=title,
        timestamp=1568707200,
        duration=2700,
        size=1,
        url_video="https://v.mp4",
        url_video_hd="https://hd.mp4",
        id=title,
    )
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
    rows = [
        _r(
            "Feuer und Flamme (S07/E05)",
            url_video="https://cdn.example.com/stream.m3u8",
            url_video_hd="https://cdn.example.com/stream_hd.m3u8",
        )
    ]
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
    rows = [_r("Feuer und Flamme (S07/E05)"), _r("Feuer und Flamme (S07/E05) (Audiodeskription)")]
    monkeypatch.setattr(cli, "_make_client", lambda cfg: FakeClient(rows))
    result = runner.invoke(
        cli.app,
        [
            "download",
            "#Feuer und Flamme",
            "--season",
            "--dry-run",
            "--exclude",
            "Audiodeskription",
            "--output",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0
    assert result.stdout.lower().count("s07e05") == 1


def test_real_mp4_download(monkeypatch, tmp_path):
    """Locks finding #1: download import alias prevents command shadowing."""
    rows = [
        _r("Feuer und Flamme (S07/E05)", url_video="https://example.test/v.mp4", url_video_hd="")
    ]
    monkeypatch.setattr(cli, "_make_client", lambda cfg: FakeClient(rows))

    with respx.mock:
        respx.get("https://example.test/v.mp4").mock(
            return_value=httpx.Response(
                200,
                content=b"video-bytes",
                headers={"content-length": "11"},
            )
        )
        result = runner.invoke(
            cli.app,
            ["download", "#Feuer und Flamme", "--resolution", "medium", "--output", str(tmp_path)],
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
        ["download", "#Feuer und Flamme", "--season", "--dry-run", "--output", str(tmp_path)],
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


def _fake_writer(calls, *, nbytes):
    def fake_dl(url, dest, **kwargs):
        calls.append(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"x" * nbytes)
        return dest

    return fake_dl


def test_download_skips_existing_valid_file(monkeypatch, tmp_path):
    rows = [_r("Feuer und Flamme (S07/E05)", size=11, url_video="https://v.mp4", url_video_hd="")]
    monkeypatch.setattr(cli, "_make_client", lambda cfg: FakeClient(rows))
    calls = []
    monkeypatch.setattr(cli, "download_file", _fake_writer(calls, nbytes=11))
    monkeypatch.setattr(cli, "remote_size", lambda url, **kw: 11)

    args = ["download", "#Feuer und Flamme", "--resolution", "medium", "--output", str(tmp_path)]
    first = runner.invoke(cli.app, args)
    assert first.exit_code == 0
    assert len(calls) == 1

    second = runner.invoke(cli.app, args)
    assert second.exit_code == 0
    assert len(calls) == 1  # not downloaded again
    assert "already exists, skipped" in second.stdout


def test_download_redownloads_corrupt_file(monkeypatch, tmp_path):
    rows = [_r("Feuer und Flamme (S07/E05)", size=999, url_video="https://v.mp4", url_video_hd="")]
    monkeypatch.setattr(cli, "_make_client", lambda cfg: FakeClient(rows))
    calls = []
    # Writes only 5 bytes although the server "really" has 11 -> always "corrupt".
    monkeypatch.setattr(cli, "download_file", _fake_writer(calls, nbytes=5))
    monkeypatch.setattr(cli, "remote_size", lambda url, **kw: 11)

    args = ["download", "#Feuer und Flamme", "--resolution", "medium", "--output", str(tmp_path)]
    runner.invoke(cli.app, args)  # first download leaves a 5-byte file
    second = runner.invoke(cli.app, args)  # sees size mismatch -> redownload
    assert second.exit_code == 0
    assert len(calls) == 2
    assert "corrupted" in second.stdout
    assert "redownloading" in second.stdout


def test_download_force_redownloads_valid_file(monkeypatch, tmp_path):
    rows = [_r("Feuer und Flamme (S07/E05)", size=11, url_video="https://v.mp4", url_video_hd="")]
    monkeypatch.setattr(cli, "_make_client", lambda cfg: FakeClient(rows))
    calls = []
    monkeypatch.setattr(cli, "download_file", _fake_writer(calls, nbytes=11))

    base = ["download", "#Feuer und Flamme", "--resolution", "medium", "--output", str(tmp_path)]
    runner.invoke(cli.app, base)  # 1 download
    forced = runner.invoke(cli.app, [*base, "--force"])
    assert forced.exit_code == 0
    assert len(calls) == 2  # downloaded again
    assert "already exists" not in forced.stdout


def test_download_prints_summary(monkeypatch, tmp_path):
    rows = [_r("Feuer und Flamme (S07/E05)", size=11, url_video="https://v.mp4", url_video_hd="")]
    monkeypatch.setattr(cli, "_make_client", lambda cfg: FakeClient(rows))
    monkeypatch.setattr(cli, "download_file", _fake_writer([], nbytes=11))
    result = runner.invoke(
        cli.app,
        ["download", "#Feuer und Flamme", "--resolution", "medium", "--output", str(tmp_path)],
    )
    assert result.exit_code == 0
    assert "Done:" in result.stdout
    assert "1 downloaded" in result.stdout
    assert "0 skipped" in result.stdout
    assert "0 redownloaded, 0 failed" in result.stdout


def test_overall_progress_counts_files_not_bytes():
    """Regression: the overall bar tracks a file count, so it must use a
    count column (MofN) and never byte/speed columns, which produced the
    bogus "10/10 bytes" / "0 bytes/s" display."""
    from rich.progress import (
        DownloadColumn,
        MofNCompleteColumn,
        TransferSpeedColumn,
    )

    overall, per_file, _ = cli._make_progress()

    assert any(isinstance(c, MofNCompleteColumn) for c in overall.columns)
    assert not any(isinstance(c, (DownloadColumn, TransferSpeedColumn)) for c in overall.columns)
    # Per-file bars are byte-based and keep the byte/speed columns.
    assert any(isinstance(c, DownloadColumn) for c in per_file.columns)
    assert any(isinstance(c, TransferSpeedColumn) for c in per_file.columns)


def test_config_set_unknown_key_exits_2(monkeypatch, tmp_path):
    monkeypatch.setattr(cli.configmod, "config_path", lambda: tmp_path / "config.toml")
    result = runner.invoke(cli.app, ["config", "set", "pagesize", "50"])
    assert result.exit_code == 2
    assert "unknown config key" in result.output


def test_config_set_bad_value_exits_2(monkeypatch, tmp_path):
    monkeypatch.setattr(cli.configmod, "config_path", lambda: tmp_path / "config.toml")
    result = runner.invoke(cli.app, ["config", "set", "page_size", "abc"])
    assert result.exit_code == 2
    assert "page_size" in result.output


def test_corrupt_config_file_exits_2(monkeypatch, tmp_path):
    p = tmp_path / "config.toml"
    p.write_text("not = = valid")
    monkeypatch.setattr(cli.configmod, "config_path", lambda: p)
    result = runner.invoke(cli.app, ["config", "show"])
    assert result.exit_code == 2
    assert "config.toml" in result.output


def test_download_invalid_exclude_regex_exits_2(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "_make_client", lambda cfg: FakeClient([_r("Folge 1")]))
    result = runner.invoke(
        cli.app,
        ["download", "#X", "--exclude", "[invalid", "--output", str(tmp_path)],
    )
    assert result.exit_code == 2
    assert "invalid regex" in result.output


def test_download_invalid_template_exits_2(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "_make_client", lambda cfg: FakeClient([_r("Folge 1")]))
    result = runner.invoke(
        cli.app,
        ["download", "#X", "--template", "{nope}.{ext}", "--output", str(tmp_path)],
    )
    assert result.exit_code == 2
    assert "template" in result.output


def test_version_flag():
    result = runner.invoke(cli.app, ["--version"])
    assert result.exit_code == 0
    assert "mvw " in result.output


def test_search_rejects_invalid_sort():
    result = runner.invoke(cli.app, ["search", "#X", "--sort", "bogus"])
    assert result.exit_code != 0


def test_search_rejects_invalid_order():
    result = runner.invoke(cli.app, ["search", "#X", "--order", "sideways"])
    assert result.exit_code != 0


def test_download_rejects_invalid_resolution_flag(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "_make_client", lambda cfg: FakeClient([_r("Folge 1")]))
    result = runner.invoke(
        cli.app, ["download", "#X", "--resolution", "ultra", "--output", str(tmp_path)]
    )
    assert result.exit_code != 0


def test_download_rejects_invalid_resolution_from_config(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "_make_client", lambda cfg: FakeClient([_r("Folge 1")]))
    monkeypatch.setattr(
        cli, "_load_config", lambda: {**cli.configmod.DEFAULTS, "resolution": "ultra"}
    )
    result = runner.invoke(cli.app, ["download", "#X", "--output", str(tmp_path)])
    assert result.exit_code == 2
    assert "resolution" in result.output


def test_traceback_locals_disabled():
    assert cli.app.pretty_exceptions_show_locals is False


def test_download_duplicate_targets_skipped_with_warning(monkeypatch, tmp_path):
    # Two identical titles render to the same destination path.
    rows = [_r("Folge 1", id="a"), _r("Folge 1", id="b")]
    monkeypatch.setattr(cli, "_make_client", lambda cfg: FakeClient(rows))
    calls = []
    monkeypatch.setattr(cli, "download_file", _fake_writer(calls, nbytes=11))
    result = runner.invoke(
        cli.app,
        ["download", "#X", "--resolution", "medium", "--output", str(tmp_path)],
    )
    assert result.exit_code == 0
    assert len(calls) == 1
    assert "duplicate target" in result.output


def test_download_subtitles_use_de_suffix(monkeypatch, tmp_path):
    rows = [_r("Folge 1", url_subtitle="https://x/sub.ttml")]
    monkeypatch.setattr(cli, "_make_client", lambda cfg: FakeClient(rows))
    calls = []
    monkeypatch.setattr(cli, "download_file", _fake_writer(calls, nbytes=11))
    result = runner.invoke(
        cli.app,
        ["download", "#X", "--resolution", "medium", "--subtitles", "--output", str(tmp_path)],
    )
    assert result.exit_code == 0
    written = sorted(p.name for p in tmp_path.rglob("*.de.ttml"))
    assert len(written) == 1
