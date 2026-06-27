from __future__ import annotations

import json as jsonlib
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.progress import (
    BarColumn, DownloadColumn, Progress, SpinnerColumn,
    TextColumn, TransferSpeedColumn,
)

from mvw import config as configmod
from mvw import display, episodes, filters, naming, query
from mvw.api import MediathekClient, MediathekError
from mvw.download import (
    DownloadError, download, download_hls, is_hls, pick_resolution,
)

app = typer.Typer(help="Search and download from MediathekViewWeb.", no_args_is_help=True)
console = Console()
err_console = Console(stderr=True)


def _make_client(cfg: dict) -> MediathekClient:
    return MediathekClient(
        user_agent=cfg["user_agent"], timeout=cfg["request_timeout"]
    )


@app.command()
def search(
    query_str: str = typer.Argument("", help="MVW query string, e.g. '!ARD #Tatort >80'"),
    channel: Optional[str] = typer.Option(None, "--channel"),
    topic: Optional[str] = typer.Option(None, "--topic"),
    title: Optional[str] = typer.Option(None, "--title"),
    description: Optional[str] = typer.Option(None, "--description"),
    min_duration: Optional[int] = typer.Option(None, "--min-duration", help="minutes"),
    max_duration: Optional[int] = typer.Option(None, "--max-duration", help="minutes"),
    sort: str = typer.Option("timestamp", "--sort"),
    order: str = typer.Option("desc", "--order"),
    future: bool = typer.Option(False, "--future"),
    limit: int = typer.Option(15, "--limit"),
    offset: int = typer.Option(0, "--offset"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    cfg = configmod.load()
    payload = query.build_payload(
        query_str or None, channel=channel, topic=topic, title=title,
        description=description, min_duration=min_duration, max_duration=max_duration,
        sort_by=sort, sort_order=order, future=future, offset=offset, size=limit,
    )
    client = _make_client(cfg)
    try:
        result = client.query(payload)
    except MediathekError as exc:
        err_console.print(display.error_panel(str(exc)))
        raise typer.Exit(2)

    if json_out:
        console.print_json(jsonlib.dumps([r.__dict__ for r in result.results]))
        return

    if not result.results:
        console.print("No results.")
        return

    console.print(display.results_table(result.results, start_index=offset + 1))
    total = result.query_info.total_results
    a = offset + 1
    b = offset + len(result.results)
    console.print(
        f"[dim]showing {a}–{b} of {total} · "
        f"{result.query_info.search_engine_time:.1f} ms[/]"
    )


@app.command()
def download(
    query_str: str = typer.Argument("", help="MVW query string"),
    channel: Optional[str] = typer.Option(None, "--channel"),
    topic: Optional[str] = typer.Option(None, "--topic"),
    title: Optional[str] = typer.Option(None, "--title"),
    min_duration: Optional[int] = typer.Option(None, "--min-duration", help="minutes"),
    max_duration: Optional[int] = typer.Option(None, "--max-duration", help="minutes"),
    season: bool = typer.Option(False, "--season", help="group into Plex season folders"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    resolution: Optional[str] = typer.Option(None, "--resolution"),
    output: Optional[Path] = typer.Option(None, "--output", "-o"),
    template: Optional[str] = typer.Option(None, "--template"),
    exclude: list[str] = typer.Option([], "--exclude", help="regex (repeatable)"),
    dedup: bool = typer.Option(False, "--dedup"),
    latest_season: bool = typer.Option(False, "--latest-season"),
    season_number: Optional[int] = typer.Option(None, "--season-number"),
    subtitles: bool = typer.Option(False, "--subtitles"),
    limit: int = typer.Option(200, "--limit", help="max entries to resolve"),
) -> None:
    cfg = configmod.load()
    pref = resolution or cfg["resolution"]
    tmpl = template or cfg["template"]
    out_dir = output or Path(cfg["download_dir"])

    payload = query.build_payload(
        query_str or None, channel=channel, topic=topic, title=title,
        min_duration=min_duration, max_duration=max_duration,
    )
    client = _make_client(cfg)

    try:
        with console.status("Searching…", spinner="dots"):
            rows = list(client.iter_all(payload, page_size=cfg["page_size"], cap=limit))
    except MediathekError as exc:
        err_console.print(display.error_panel(str(exc)))
        raise typer.Exit(2)

    rows = filters.exclude(rows, exclude)
    if dedup:
        rows = filters.dedup(rows)
    if latest_season:
        rows = filters.latest_season(rows)

    if not rows:
        console.print("No matching entries to download.")
        return

    eps = episodes.assign(rows, season_override=season_number)
    if season:
        ordered = [e for _s, lst in episodes.group_by_season(eps).items() for e in lst]
    else:
        ordered = eps

    # Build plan: (dest_path, url, tier, subtitle_url)
    plan: list[tuple[Path, str, str, str]] = []
    for ep in ordered:
        try:
            url, tier = pick_resolution(ep.result, pref)
        except DownloadError as exc:
            err_console.print(display.error_panel(f"{ep.result.title}: {exc}"))
            continue
        ext = "mp4"
        dest = out_dir / naming.render(ep, template=tmpl, tier=tier, ext=ext)
        plan.append((dest, url, tier, ep.result.url_subtitle))

    if dry_run:
        console.print(display.dry_run_tree([(d, u, t) for d, u, t, _ in plan]))
        console.print(f"[dim]{len(plan)} file(s) planned[/]")
        return

    _run_downloads(plan, subtitles=subtitles)


def _run_downloads(plan, *, subtitles: bool) -> None:
    progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        console=console,
    )
    failures = 0
    with progress:
        overall = progress.add_task("Overall", total=len(plan))
        for dest, url, _tier, sub_url in plan:
            task = progress.add_task(dest.name, total=None)

            def cb(done: int, total, _t=task):
                progress.update(_t, completed=done, total=total)

            try:
                if is_hls(url):
                    progress.update(task, description=f"{dest.name} (ffmpeg)")
                    download_hls(url, dest)
                else:
                    download(url, dest, on_progress=cb)
                if subtitles and sub_url:
                    download(sub_url, dest.with_suffix(".xml"))
            except DownloadError as exc:
                failures += 1
                err_console.print(display.error_panel(f"{dest.name}: {exc}"))
            finally:
                progress.update(task, visible=False)
                progress.advance(overall)
    if failures:
        raise typer.Exit(5)


@app.command()
def info(target: str = typer.Argument(..., help="query string; shows the first match")) -> None:
    cfg = configmod.load()
    payload = query.build_payload(target, size=1)
    client = _make_client(cfg)
    try:
        result = client.query(payload)
    except MediathekError as exc:
        err_console.print(display.error_panel(str(exc)))
        raise typer.Exit(2)
    if not result.results:
        console.print("No results.")
        raise typer.Exit(0)
    console.print(display.detail_panel(result.results[0]))


config_app = typer.Typer(help="Manage configuration.")
app.add_typer(config_app, name="config")


@config_app.command("show")
def config_show() -> None:
    for k, v in configmod.load().items():
        console.print(f"[cyan]{k}[/] = {v}")


@config_app.command("set")
def config_set(key: str, value: str) -> None:
    configmod.set_value(key, value)
    console.print(f"Set [cyan]{key}[/] = {value}")


@config_app.command("path")
def config_path_cmd() -> None:
    console.print(str(configmod.config_path()))


if __name__ == "__main__":
    app()
