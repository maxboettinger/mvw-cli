from __future__ import annotations

import json as jsonlib
from pathlib import Path

import typer
from rich.console import Console, Group
from rich.live import Live
from rich.progress import (
    BarColumn,
    DownloadColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

from mvw import config as configmod
from mvw import display, episodes, filters, naming, query
from mvw.api import MediathekClient, MediathekError
from mvw.download import (
    DownloadError,
    FFmpegMissingError,
    download_hls,
    is_hls,
    pick_resolution,
    remote_size,
    verify_size,
)
from mvw.download import (
    download as download_file,
)

app = typer.Typer(help="Search and download from MediathekViewWeb.", no_args_is_help=True)
console = Console()
err_console = Console(stderr=True)


def _load_config() -> dict:
    try:
        return configmod.load()
    except configmod.ConfigError as exc:
        err_console.print(display.error_panel(str(exc)))
        raise typer.Exit(2) from exc


def _make_client(cfg: dict) -> MediathekClient:
    return MediathekClient(user_agent=cfg["user_agent"], timeout=cfg["request_timeout"])


@app.command()
def search(
    query_str: str = typer.Argument("", help="MVW query string, e.g. '!ARD #Tatort >80'"),
    channel: str | None = typer.Option(None, "--channel"),
    topic: str | None = typer.Option(None, "--topic"),
    title: str | None = typer.Option(None, "--title"),
    description: str | None = typer.Option(None, "--description"),
    min_duration: int | None = typer.Option(None, "--min-duration", help="minutes"),
    max_duration: int | None = typer.Option(None, "--max-duration", help="minutes"),
    sort: str = typer.Option("timestamp", "--sort"),
    order: str = typer.Option("desc", "--order"),
    future: bool = typer.Option(False, "--future"),
    limit: int = typer.Option(15, "--limit"),
    offset: int = typer.Option(0, "--offset"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    cfg = _load_config()
    payload = query.build_payload(
        query_str or None,
        channel=channel,
        topic=topic,
        title=title,
        description=description,
        min_duration=min_duration,
        max_duration=max_duration,
        sort_by=sort,
        sort_order=order,
        future=future,
        offset=offset,
        size=limit,
    )
    client = _make_client(cfg)
    try:
        result = client.query(payload)
    except MediathekError as exc:
        err_console.print(display.error_panel(str(exc)))
        raise typer.Exit(2) from exc

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
        f"[dim]showing {a}–{b} of {total} · {result.query_info.search_engine_time:.1f} ms[/]"
    )


@app.command()
def download(
    query_str: str = typer.Argument("", help="MVW query string"),
    channel: str | None = typer.Option(None, "--channel"),
    topic: str | None = typer.Option(None, "--topic"),
    title: str | None = typer.Option(None, "--title"),
    min_duration: int | None = typer.Option(None, "--min-duration", help="minutes"),
    max_duration: int | None = typer.Option(None, "--max-duration", help="minutes"),
    season: bool = typer.Option(False, "--season", help="group into Plex season folders"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    resolution: str | None = typer.Option(None, "--resolution"),
    output: Path | None = typer.Option(None, "--output", "-o"),
    template: str | None = typer.Option(None, "--template"),
    exclude: list[str] = typer.Option([], "--exclude", help="regex (repeatable)"),
    dedup: bool = typer.Option(False, "--dedup"),
    latest_season: bool = typer.Option(False, "--latest-season"),
    season_number: int | None = typer.Option(None, "--season-number"),
    subtitles: bool = typer.Option(False, "--subtitles"),
    force: bool = typer.Option(False, "--force", help="redownload even if a valid file exists"),
    limit: int = typer.Option(200, "--limit", help="max entries to resolve"),
) -> None:
    cfg = _load_config()
    pref = resolution or cfg["resolution"]
    tmpl = template or cfg["template"]
    out_dir = output or Path(cfg["download_dir"])

    payload = query.build_payload(
        query_str or None,
        channel=channel,
        topic=topic,
        title=title,
        min_duration=min_duration,
        max_duration=max_duration,
    )
    client = _make_client(cfg)

    try:
        with console.status("Searching…", spinner="dots"):
            rows = list(client.iter_all(payload, page_size=cfg["page_size"], cap=limit))
    except MediathekError as exc:
        err_console.print(display.error_panel(str(exc)))
        raise typer.Exit(2) from exc

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
        rendered = naming.render(ep, template=tmpl, tier=tier, ext=ext)
        dest = out_dir / rendered if season else out_dir / rendered.name
        plan.append((dest, url, tier, ep.result.url_subtitle))

    if dry_run:
        console.print(display.dry_run_tree([(d, u, t) for d, u, t, _ in plan]))
        console.print(f"[dim]{len(plan)} file(s) planned[/]")
        return

    _run_downloads(plan, subtitles=subtitles, force=force)


def _make_progress() -> tuple[Progress, Progress, Group]:
    """Build the download progress display.

    Two separate ``Progress`` instances are used because a single ``Progress``
    applies one column set to every task, yet the two task kinds carry different
    units: the overall bar counts *files*, while per-file bars count *bytes*.
    Rendering a file count through byte/speed columns produced the nonsensical
    "10/10 bytes" / "0 bytes/s" overall display. They are stacked in a ``Group``
    so both still render under a single ``Live``.
    """
    overall = Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),  # "12/78", a count — no bogus byte unit
        TimeRemainingColumn(),
    )
    per_file = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        DownloadColumn(),  # bytes — correct here
        TransferSpeedColumn(),
    )
    return overall, per_file, Group(overall, per_file)


def _print_line(text: str, *, error: bool = False) -> None:
    """Print a one-line status without wrapping (keeps Live output stable)."""
    target = err_console if error else console
    target.print(text, no_wrap=True, overflow="ignore", crop=False)


def _run_downloads(plan, *, subtitles: bool, force: bool = False) -> None:
    overall_progress, file_progress, group = _make_progress()
    counts = {"downloaded": 0, "skipped": 0, "redownloaded": 0, "failed": 0}
    ffmpeg_missing = False
    with Live(group, console=console):
        overall = overall_progress.add_task("Overall", total=len(plan))
        for dest, url, _tier, sub_url in plan:
            hls = is_hls(url)
            probe: int | None = None
            is_redownload = False
            if not force and dest.exists():
                # Probe the real size of the tier we'd fetch; HLS has no single
                # size, so fall back to "exists and non-empty".
                probe = None if hls else remote_size(url)
                expected = 0 if (hls or probe is None) else probe
                if verify_size(dest, expected):
                    _print_line(f"[green]✓[/] {dest.name} — already exists, skipped")
                    counts["skipped"] += 1
                    overall_progress.advance(overall)
                    continue
                _print_line(f"[yellow]⚠[/] {dest.name} — corrupted (size mismatch), redownloading")
                dest.unlink(missing_ok=True)
                is_redownload = True

            task = file_progress.add_task(dest.name, total=None)

            def cb(done: int, total, _t=task):
                file_progress.update(_t, completed=done, total=total)

            try:
                if hls:
                    file_progress.update(task, description=f"{dest.name} (ffmpeg)")
                    download_hls(url, dest, on_progress=cb)
                else:
                    download_file(url, dest, on_progress=cb, expected_size=probe)
                counts["redownloaded" if is_redownload else "downloaded"] += 1
                _print_line(f"[cyan]↓[/] {dest.name} — downloaded")
                if subtitles and sub_url:
                    try:
                        download_file(sub_url, dest.with_suffix(".xml"))
                    except DownloadError as exc:
                        _print_line(
                            f"[yellow]⚠[/] {dest.name} (subtitle) — failed: {exc}", error=True
                        )
            except FFmpegMissingError as exc:
                ffmpeg_missing = True
                err_console.print(
                    display.error_panel(
                        f"{dest.name}: {exc}\nInstall ffmpeg: https://ffmpeg.org/download.html"
                    )
                )
            except DownloadError as exc:
                counts["failed"] += 1
                _print_line(f"[red]✗[/] {dest.name} — failed: {exc}")
            finally:
                file_progress.update(task, visible=False)
                overall_progress.advance(overall)
    _print_line(
        f"[bold]Done:[/] {counts['downloaded']} downloaded, "
        f"{counts['skipped']} skipped, {counts['redownloaded']} redownloaded, "
        f"{counts['failed']} failed"
    )
    if ffmpeg_missing:
        raise typer.Exit(4)
    elif counts["failed"]:
        raise typer.Exit(5)


@app.command()
def info(target: str = typer.Argument(..., help="query string; shows the first match")) -> None:
    cfg = _load_config()
    payload = query.build_payload(target, size=1)
    client = _make_client(cfg)
    try:
        result = client.query(payload)
    except MediathekError as exc:
        err_console.print(display.error_panel(str(exc)))
        raise typer.Exit(2) from exc
    if not result.results:
        console.print("No results.")
        raise typer.Exit(0)
    console.print(display.detail_panel(result.results[0]))


config_app = typer.Typer(help="Manage configuration.")
app.add_typer(config_app, name="config")


@config_app.command("show")
def config_show() -> None:
    for k, v in _load_config().items():
        console.print(f"[cyan]{k}[/] = {v}")


@config_app.command("set")
def config_set(key: str, value: str) -> None:
    try:
        configmod.set_value(key, value)
    except configmod.ConfigError as exc:
        err_console.print(display.error_panel(str(exc)))
        raise typer.Exit(2) from exc
    console.print(f"Set [cyan]{key}[/] = {value}")


@config_app.command("path")
def config_path_cmd() -> None:
    console.print(str(configmod.config_path()))


if __name__ == "__main__":
    app()
