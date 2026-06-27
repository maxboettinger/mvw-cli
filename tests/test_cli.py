from typer.testing import CliRunner

import mvw.cli as cli
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
