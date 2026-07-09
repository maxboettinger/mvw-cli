from __future__ import annotations

from pathlib import Path

from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

from mvw.models import MediathekResult

_TIER_BADGE = {"low": "LOW", "medium": "SD", "high": "HD"}


def res_badges(result: MediathekResult) -> str:
    return " ".join(_TIER_BADGE[t] for t in result.resolutions)


def results_table(results: list[MediathekResult], *, start_index: int = 1) -> Table:
    table = Table(show_lines=False, expand=True)
    table.add_column("#", justify="right", style="dim", no_wrap=True)
    table.add_column("Channel", style="cyan", no_wrap=True)
    table.add_column("Topic", style="magenta")
    table.add_column("Title")
    table.add_column("Date", no_wrap=True)
    table.add_column("Dur", justify="right", no_wrap=True)
    table.add_column("Res", no_wrap=True)
    for i, r in enumerate(results, start=start_index):
        table.add_row(
            str(i),
            r.channel,
            r.topic,
            r.title,
            r.aired.strftime("%Y-%m-%d"),
            r.duration_human,
            res_badges(r),
        )
    return table


def detail_panel(result: MediathekResult) -> Panel:
    lines = [
        f"[bold]Channel:[/] {result.channel}",
        f"[bold]Topic:[/] {result.topic}",
        f"[bold]Title:[/] {result.title}",
        f"[bold]Aired:[/] {result.aired.strftime('%Y-%m-%d %H:%M')}",
        f"[bold]Duration:[/] {result.duration_human}",
        f"[bold]Size:[/] {result.size_human}",
        f"[bold]Resolutions:[/] {res_badges(result) or '—'}",
        "",
        result.description or "(no description)",
        "",
        f"[dim]Video:[/] {result.url_video or '—'}",
        f"[dim]HD:[/] {result.url_video_hd or '—'}",
        f"[dim]Low:[/] {result.url_video_low or '—'}",
        f"[dim]Subtitle:[/] {result.url_subtitle or '—'}",
        f"[dim]Website:[/] {result.url_website or '—'}",
    ]
    return Panel("\n".join(lines), title=result.title, border_style="cyan")


def dry_run_tree(plans: list[tuple[Path, str, str]]) -> Tree:
    root = Tree("[bold]Planned downloads[/]")
    folders: dict[str, Tree] = {}
    for dest, _url, tier in plans:
        parent_key = str(dest.parent)
        if parent_key not in folders:
            folders[parent_key] = root.add(f"[blue]{parent_key}[/]")
        folders[parent_key].add(f"{dest.name}  [dim]({tier})[/]")
    return root


def error_panel(message: str) -> Panel:
    return Panel(message, title="Error", border_style="red")
