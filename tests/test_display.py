from pathlib import Path

from rich.table import Table
from rich.tree import Tree

from mvw.display import dry_run_tree, res_badges, results_table
from mvw.models import MediathekResult


def _r(**over):
    base = dict(channel="WDR", topic="T", title="x", timestamp=1568707200,
                duration=2700, size=1, url_video="https://v.mp4",
                url_video_low="https://l.mp4", url_video_hd="https://h.mp4", id="1")
    base.update(over)
    return MediathekResult.from_api(base)


def test_res_badges_lists_present_tiers():
    assert res_badges(_r()) == "LOW SD HD"
    assert res_badges(_r(url_video_low="", url_video_hd="")) == "SD"


def test_results_table_is_table_with_rows():
    table = results_table([_r(), _r()])
    assert isinstance(table, Table)
    assert table.row_count == 2


def test_dry_run_tree_type():
    tree = dry_run_tree([(Path("Show/Season 01/ep.mp4"), "https://v.mp4", "high")])
    assert isinstance(tree, Tree)
