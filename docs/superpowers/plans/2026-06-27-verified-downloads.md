# Verified Downloads Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `mvw download` skip already-downloaded valid files, redownload corrupt ones, and verify every fresh download against its expected byte size — with clear per-file status and an end-of-run summary.

**Architecture:** A single `verify_size` helper in `download.py` is the integrity primitive. The HTTP `download()` function gains post-transfer size verification (against the server's `Content-Length`, falling back to the API `size`) and a resume guard that restarts from scratch when a `206` response's total disagrees with the expected size. The CLI's `_run_downloads` consults `verify_size` before each transfer to skip/redownload, threads the API `size` into the download plan, and reports status lines plus a summary.

**Tech Stack:** Python 3, Typer, Rich, httpx, pytest, respx.

## Global Constraints

- Integrity is verified by **byte size only** — the MVW API provides no hash/checksum.
- Pre-download skip decisions use the API `size` (the only value available before connecting). Tolerance is `0` (exact); when API `size <= 0` the check degrades to "exists and non-empty".
- Post-download completeness uses the server's HTTP `Content-Length` when present, else the API `size` as a fallback. When neither is available the transfer is accepted as-is.
- HLS (`.m3u8`) downloads have no reliable expected size: their skip check uses the "exists and non-empty" branch only, and `download_hls()` verification is unchanged (ffmpeg exit code + non-empty output).
- A fresh/failed download must never leave a corrupt **final** file: the `.part` is promoted via `part.replace(dest)` only after verification passes.
- Exit codes are preserved: ffmpeg missing → 4; any download failure → 5; otherwise 0. Skips and redownloads alone are success.
- Follow existing code style: `from __future__ import annotations`, type hints, focused functions. Run the full suite with `pytest -q` from the repo root.

---

### Task 1: `verify_size` integrity helper

**Files:**
- Modify: `src/mvw/download.py` (add `verify_size` after the `is_hls` function, ~line 27)
- Test: `tests/test_download.py`

**Interfaces:**
- Consumes: nothing (only stdlib `pathlib.Path`).
- Produces: `verify_size(path: Path, expected: int, *, tolerance: int = 0) -> bool` — `True` iff the file is considered valid. When `expected > 0`: file exists and `abs(actual - expected) <= tolerance`. When `expected <= 0`: file exists and is non-empty. Missing/unreadable file → `False`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_download.py` (import is already `from mvw.download import ...` — extend it to include `verify_size`):

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_download.py -k verify_size -v`
Expected: FAIL with `ImportError: cannot import name 'verify_size'` (or `NameError`).

- [ ] **Step 3: Implement `verify_size`**

In `src/mvw/download.py`, add directly below the `is_hls` function:

```python
def verify_size(path: Path, expected: int, *, tolerance: int = 0) -> bool:
    """Return True if ``path`` is a plausibly complete download.

    When ``expected`` is positive it is the byte oracle (the API ``size``):
    the file must exist and its size must be within ``tolerance`` of it. When
    ``expected`` is non-positive (e.g. HLS, where no reliable size exists),
    validity degrades to "exists and is non-empty".
    """
    try:
        actual = path.stat().st_size
    except OSError:
        return False
    if expected > 0:
        return abs(actual - expected) <= tolerance
    return actual > 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_download.py -k verify_size -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/mvw/download.py tests/test_download.py
git commit -m "feat(download): add verify_size integrity helper"
```

---

### Task 2: post-download verification + resume guard in `download()`

**Files:**
- Modify: `src/mvw/download.py` — replace the `download()` function body (currently ~lines 36-81)
- Test: `tests/test_download.py`

**Interfaces:**
- Consumes: nothing new from Task 1 at runtime.
- Produces: updated signature
  `download(url: str, dest: Path, *, on_progress: ProgressCb | None = None, resume: bool = True, expected_size: int | None = None, client: httpx.Client | None = None) -> Path`.
  Raises `DownloadError("size mismatch downloading <url>: got X, expected Y")` and leaves no `.part`/final file when the received byte count disagrees with the effective expected size. The new `expected_size` keyword is the API `size`, used as the completeness fallback and to guard resume.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_download.py`. The short-read test uses a custom byte stream so the response carries **no** `Content-Length`, forcing the `expected_size` fallback:

```python
class _ShortStream(httpx.SyncByteStream):
    """Yields fewer bytes than the caller's expected_size, with no length header."""

    def __iter__(self):
        yield b"hello"  # 5 bytes

    def close(self):
        pass


@respx.mock
def test_download_raises_when_short_of_expected_size(tmp_path: Path):
    respx.get("https://v/m.mp4").mock(
        return_value=httpx.Response(200, stream=_ShortStream())
    )
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
                206, content=b"world",
                headers={"content-range": "bytes 6-10/11", "content-length": "5"},
            )
        # Restart attempt: full file from byte 0.
        return httpx.Response(
            200, content=b"hello world", headers={"content-length": "11"}
        )

    respx.get("https://v/m.mp4").mock(side_effect=handler)
    download("https://v/m.mp4", dest, expected_size=20)

    assert dest.read_bytes() == b"hello world"
    assert seen_ranges == ["bytes=6-", None]  # tried resume, then restarted clean
    assert not part.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_download.py -k "short_of_expected or remote_total" -v`
Expected: FAIL — `download()` has no `expected_size` parameter / no size check (e.g. `TypeError: unexpected keyword argument 'expected_size'`).

- [ ] **Step 3: Replace the `download()` implementation**

In `src/mvw/download.py`, replace the entire current `download(...) -> Path:` function (from its `def download(` line through `return dest`) with:

```python
def download(
    url: str,
    dest: Path,
    *,
    on_progress: ProgressCb | None = None,
    resume: bool = True,
    expected_size: int | None = None,
    client: httpx.Client | None = None,
) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")

    owns_client = client is None
    client = client or httpx.Client(timeout=60.0, follow_redirects=True)
    downloaded = 0
    total: int | None = None
    try:
        # At most two passes: one resume attempt, then a clean restart if the
        # server's 206 total disagrees with the known expected size.
        for _attempt in range(2):
            existing = part.stat().st_size if (resume and part.exists()) else 0
            headers = {}
            mode = "wb"
            if existing:
                headers["Range"] = f"bytes={existing}-"
                mode = "ab"
            with client.stream("GET", url, headers=headers) as resp:
                if resp.status_code not in (200, 206):
                    raise DownloadError(f"HTTP {resp.status_code} downloading {url}")
                if resp.status_code == 200:
                    # Server is sending the whole file; ignore any partial .part.
                    existing = 0
                    mode = "wb"
                total = None
                cl = resp.headers.get("content-length")
                if cl is not None:
                    total = int(cl) + existing
                # Resume guard: a 206 whose total disagrees with the known
                # expected size means the remote changed under us. Drop the
                # stale partial and retry once from byte 0.
                if (
                    resp.status_code == 206
                    and existing
                    and expected_size
                    and expected_size > 0
                    and total is not None
                    and total != expected_size
                ):
                    resp.close()
                    part.unlink(missing_ok=True)
                    resume = False
                    continue
                downloaded = existing
                with open(part, mode) as fh:
                    for chunk in resp.iter_bytes():
                        fh.write(chunk)
                        downloaded += len(chunk)
                        if on_progress:
                            on_progress(downloaded, total)
            break
    except httpx.TransportError as exc:
        raise DownloadError(f"network error: {exc}") from exc
    finally:
        if owns_client:
            client.close()

    # Completeness check: prefer the server's Content-Length total for this
    # transfer; fall back to the API-provided expected_size. Promote .part to
    # the final name only after this passes.
    effective = total if total is not None else (
        expected_size if expected_size and expected_size > 0 else None
    )
    if effective is not None and downloaded != effective:
        part.unlink(missing_ok=True)
        raise DownloadError(
            f"size mismatch downloading {url}: got {downloaded}, expected {effective}"
        )

    part.replace(dest)
    return dest
```

- [ ] **Step 4: Run the download tests to verify they pass**

Run: `pytest tests/test_download.py -v`
Expected: PASS — the two new tests plus the existing `test_download_streams_and_renames` and `test_download_resumes_with_range` (which pass no `expected_size`, so the guard is inert and behavior is unchanged).

- [ ] **Step 5: Commit**

```bash
git add src/mvw/download.py tests/test_download.py
git commit -m "feat(download): verify byte count and guard resume against changed remote"
```

---

### Task 3: skip/redownload, `--force`, status lines, and summary in the CLI

**Files:**
- Modify: `src/mvw/cli.py` — import `verify_size`; add `--force` option; extend the plan tuple with the expected size; update `dry_run` unpacking; rewrite `_run_downloads`.
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `verify_size(path, expected, *, tolerance=0) -> bool` (Task 1); `download(..., expected_size=...)` (Task 2); existing `download_hls`, `is_hls`, `pick_resolution`.
- Produces: `_run_downloads(plan, *, subtitles: bool, force: bool = False) -> None`, where `plan` is a list of `(dest: Path, url: str, tier: str, sub_url: str, size: int)` tuples. Prints one status line per file and a final `Done: N downloaded, N skipped, N redownloaded, N failed` summary.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_cli.py` (the existing `_r` fixture already accepts `size` via `**over`). These monkeypatch `cli.download_file` with a fake that writes a controllable number of bytes, so no network is touched:

```python
def _fake_writer(calls, *, nbytes):
    def fake_dl(url, dest, **kwargs):
        calls.append(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"x" * nbytes)
        return dest
    return fake_dl


def test_download_skips_existing_valid_file(monkeypatch, tmp_path):
    rows = [_r("Feuer und Flamme (S07/E05)", size=11,
               url_video="https://v.mp4", url_video_hd="")]
    monkeypatch.setattr(cli, "_make_client", lambda cfg: FakeClient(rows))
    calls = []
    monkeypatch.setattr(cli, "download_file", _fake_writer(calls, nbytes=11))

    args = ["download", "#Feuer und Flamme", "--resolution", "medium",
            "--output", str(tmp_path)]
    first = runner.invoke(cli.app, args)
    assert first.exit_code == 0
    assert len(calls) == 1

    second = runner.invoke(cli.app, args)
    assert second.exit_code == 0
    assert len(calls) == 1  # not downloaded again
    assert "already exists, skipped" in second.stdout


def test_download_redownloads_corrupt_file(monkeypatch, tmp_path):
    rows = [_r("Feuer und Flamme (S07/E05)", size=999,
               url_video="https://v.mp4", url_video_hd="")]
    monkeypatch.setattr(cli, "_make_client", lambda cfg: FakeClient(rows))
    calls = []
    # Writes only 5 bytes although the API size is 999 -> always "corrupt".
    monkeypatch.setattr(cli, "download_file", _fake_writer(calls, nbytes=5))

    args = ["download", "#Feuer und Flamme", "--resolution", "medium",
            "--output", str(tmp_path)]
    runner.invoke(cli.app, args)            # first download leaves a 5-byte file
    second = runner.invoke(cli.app, args)   # sees size mismatch -> redownload
    assert len(calls) == 2
    assert "corrupted" in second.stdout
    assert "redownloading" in second.stdout


def test_download_force_redownloads_valid_file(monkeypatch, tmp_path):
    rows = [_r("Feuer und Flamme (S07/E05)", size=11,
               url_video="https://v.mp4", url_video_hd="")]
    monkeypatch.setattr(cli, "_make_client", lambda cfg: FakeClient(rows))
    calls = []
    monkeypatch.setattr(cli, "download_file", _fake_writer(calls, nbytes=11))

    base = ["download", "#Feuer und Flamme", "--resolution", "medium",
            "--output", str(tmp_path)]
    runner.invoke(cli.app, base)                       # 1 download
    forced = runner.invoke(cli.app, base + ["--force"])
    assert forced.exit_code == 0
    assert len(calls) == 2                             # downloaded again
    assert "already exists" not in forced.stdout


def test_download_prints_summary(monkeypatch, tmp_path):
    rows = [_r("Feuer und Flamme (S07/E05)", size=11,
               url_video="https://v.mp4", url_video_hd="")]
    monkeypatch.setattr(cli, "_make_client", lambda cfg: FakeClient(rows))
    monkeypatch.setattr(cli, "download_file", _fake_writer([], nbytes=11))
    result = runner.invoke(
        cli.app,
        ["download", "#Feuer und Flamme", "--resolution", "medium",
         "--output", str(tmp_path)],
    )
    assert result.exit_code == 0
    assert "Done:" in result.stdout
    assert "1 downloaded" in result.stdout
    assert "0 skipped" in result.stdout
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_cli.py -k "skips_existing or redownloads_corrupt or force_redownloads or prints_summary" -v`
Expected: FAIL — `--force` is an unknown option and/or files are redownloaded every run (skip/summary text absent).

- [ ] **Step 3: Add the `verify_size` import**

In `src/mvw/cli.py`, update the `from mvw.download import (...)` block (currently lines 18-20) to include `verify_size`:

```python
from mvw.download import (
    DownloadError, FFmpegMissingError, download as download_file, download_hls,
    is_hls, pick_resolution, verify_size,
)
```

- [ ] **Step 4: Add the `--force` option to the `download` command**

In `src/mvw/cli.py`, in the `download(...)` command signature, add this option immediately after the `subtitles` option (around line 97):

```python
    force: bool = typer.Option(False, "--force", help="redownload even if a valid file exists"),
```

- [ ] **Step 5: Thread the expected size into the plan and fix dry-run unpacking**

In `src/mvw/cli.py`, change the plan type annotation and the `plan.append(...)` call inside the `download` command (around lines 135 and 145):

```python
    # Build plan: (dest_path, url, tier, subtitle_url, expected_size)
    plan: list[tuple[Path, str, str, str, int]] = []
```

```python
        plan.append((dest, url, tier, ep.result.url_subtitle, ep.result.size))
```

Update the dry-run block (around line 148) to unpack the 5-tuple:

```python
    if dry_run:
        console.print(display.dry_run_tree([(d, u, t) for d, u, t, _s, _sz in plan]))
        console.print(f"[dim]{len(plan)} file(s) planned[/]")
        return
```

And pass `force` through to `_run_downloads` (the call near the end of the command, currently `_run_downloads(plan, subtitles=subtitles)`):

```python
    _run_downloads(plan, subtitles=subtitles, force=force)
```

- [ ] **Step 6: Rewrite `_run_downloads`**

In `src/mvw/cli.py`, replace the entire current `_run_downloads` function with:

```python
def _run_downloads(plan, *, subtitles: bool, force: bool = False) -> None:
    overall_progress, file_progress, group = _make_progress()
    counts = {"downloaded": 0, "skipped": 0, "redownloaded": 0, "failed": 0}
    ffmpeg_missing = False
    with Live(group, console=console):
        overall = overall_progress.add_task("Overall", total=len(plan))
        for dest, url, _tier, sub_url, size in plan:
            hls = is_hls(url)
            # HLS output has no reliable expected size; fall back to non-empty.
            expected = 0 if hls else size

            is_redownload = False
            if not force and dest.exists():
                if verify_size(dest, expected):
                    console.print(f"[green]✓[/] {dest.name} — already exists, skipped")
                    counts["skipped"] += 1
                    overall_progress.advance(overall)
                    continue
                console.print(
                    f"[yellow]⚠[/] {dest.name} — corrupted (size mismatch), redownloading"
                )
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
                    download_file(url, dest, on_progress=cb, expected_size=size)
                if subtitles and sub_url:
                    download_file(sub_url, dest.with_suffix(".xml"))
                counts["redownloaded" if is_redownload else "downloaded"] += 1
                console.print(f"[cyan]↓[/] {dest.name} — downloaded")
            except FFmpegMissingError as exc:
                ffmpeg_missing = True
                err_console.print(display.error_panel(
                    f"{dest.name}: {exc}\nInstall ffmpeg: https://ffmpeg.org/download.html"
                ))
            except DownloadError as exc:
                counts["failed"] += 1
                err_console.print(display.error_panel(f"{dest.name}: {exc}"))
            finally:
                file_progress.update(task, visible=False)
                overall_progress.advance(overall)
    console.print(
        f"[bold]Done:[/] {counts['downloaded']} downloaded, "
        f"{counts['skipped']} skipped, {counts['redownloaded']} redownloaded, "
        f"{counts['failed']} failed"
    )
    if ffmpeg_missing:
        raise typer.Exit(4)
    elif counts["failed"]:
        raise typer.Exit(5)
```

- [ ] **Step 7: Run the new CLI tests to verify they pass**

Run: `pytest tests/test_cli.py -k "skips_existing or redownloads_corrupt or force_redownloads or prints_summary" -v`
Expected: PASS (4 tests).

- [ ] **Step 8: Run the full suite to verify no regressions**

Run: `pytest -q`
Expected: PASS — all prior tests (including `test_real_mp4_download`, `test_download_missing_ffmpeg_exits_4`, `test_download_dry_run_lists_plan`) still green. Note: `test_real_mp4_download` uses `size=1` but a `Content-Length: 11` response, so `download()` verifies against the Content-Length (11 == 11) and the API `size` fallback is not consulted — it still passes.

- [ ] **Step 9: Commit**

```bash
git add src/mvw/cli.py tests/test_cli.py
git commit -m "feat(cli): skip valid files, redownload corrupt, add --force and summary"
```

---

### Task 4: README documentation

**Files:**
- Modify: `README.md` (document `--force` and the skip/verify behavior in the download section)

**Interfaces:**
- Consumes: the finished behavior from Tasks 1-3.
- Produces: user-facing docs only (no code).

- [ ] **Step 1: Locate the download options section**

Run: `grep -n "download\|--season\|--dry-run\|Options\|--force" README.md`
Expected: shows the download command/options area to edit (and confirms `--force` is not yet documented).

- [ ] **Step 2: Document the new behavior**

In `README.md`, in the `download` command's options/behavior section, add entries matching the file's existing format (adapt the surrounding markdown style — table row vs. bullet — to whatever is already used):

```markdown
- `--force` — redownload every matched entry even if a valid file already exists.

By default, `download` checks each target path before fetching:

- a file whose size matches the catalog's expected byte size is **skipped**
  (`✓ … already exists, skipped`);
- a file whose size does **not** match (truncated/corrupt from an interrupted
  run) is deleted and **redownloaded** (`⚠ … corrupted (size mismatch),
  redownloading`);
- HLS (`.m3u8`) targets have no reliable size, so any non-empty existing file
  is treated as complete.

Each fresh download is verified against the server's `Content-Length` (falling
back to the catalog size) before the temporary `.part` file is promoted to its
final name, so an interrupted transfer never leaves a corrupt final file. A run
ends with a summary line, e.g. `Done: 8 downloaded, 5 skipped, 2 redownloaded,
1 failed`.
```

- [ ] **Step 3: Verify the docs render and match behavior**

Run: `grep -n "force\|already exists, skipped\|redownloaded" README.md`
Expected: the new lines are present and consistent with the status strings emitted in `_run_downloads` (Task 3).

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: document download skip/verify behavior and --force"
```

---

## Self-Review notes

- **Spec coverage:** Integrity model → Task 1 (`verify_size`). Post-download completeness + resume guard → Task 2. Pre-download skip check, `--force`, status lines, summary, exit codes → Task 3. README → Task 4. All spec sections map to a task.
- **Type consistency:** `verify_size(path, expected, *, tolerance=0) -> bool` is defined in Task 1 and consumed identically in Tasks 2/3. `download(..., expected_size=None)` is defined in Task 2 and called with `expected_size=size` in Task 3. The plan tuple is consistently the 5-tuple `(dest, url, tier, sub_url, size)` across the `download` command, `dry_run` unpacking, and `_run_downloads`.
- **No placeholders:** every code and command step contains concrete content.
