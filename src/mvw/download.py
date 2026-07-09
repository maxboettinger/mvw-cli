from __future__ import annotations

import contextlib
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

import httpx

from mvw.models import MediathekResult

ProgressCb = Callable[[int, "int | None"], None]


class DownloadError(Exception):
    pass


class FFmpegMissingError(DownloadError):
    pass


def is_hls(url: str) -> bool:
    return ".m3u8" in url.split("?", 1)[0].lower()


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


def remote_size(url: str, *, client: httpx.Client | None = None) -> int | None:
    """Best-effort probe of a URL's byte size without downloading the body.

    Tries an HTTP HEAD first; if that gives no usable size (many CDNs reject
    HEAD), falls back to a ranged GET and reads the total from Content-Range
    WITHOUT reading the body. Returns the size in bytes, or None when it cannot
    be determined or any network error occurs. Never raises — callers use it
    only as a hint.
    """
    owns_client = client is None
    client = client or httpx.Client(timeout=30.0, follow_redirects=True)
    try:
        try:
            resp = client.head(url)
            if resp.status_code == 200:
                cl = resp.headers.get("content-length")
                if cl is not None and cl.isdigit():
                    return int(cl)
        except httpx.HTTPError:
            pass
        # Fallback: a 1-byte ranged GET exposes the full size via Content-Range.
        # Use stream() and never read the body, so a server that ignores Range
        # (returns 200) does not trigger a full download.
        try:
            with client.stream("GET", url, headers={"Range": "bytes=0-0"}) as resp:
                if resp.status_code == 206:
                    cr = resp.headers.get("content-range")  # "bytes 0-0/12345"
                    if cr and "/" in cr:
                        total = cr.rsplit("/", 1)[1]
                        if total.isdigit():
                            return int(total)
        except httpx.HTTPError:
            pass
        return None
    finally:
        if owns_client:
            client.close()


def pick_resolution(result: MediathekResult, preference: str) -> tuple[str, str]:
    url, tier = result.resolve_video(preference)
    if not url or not tier:
        raise DownloadError("no video URL available for this entry")
    return url, tier


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
    effective = (
        total
        if total is not None
        else (expected_size if expected_size and expected_size > 0 else None)
    )
    if effective is not None and downloaded != effective:
        part.unlink(missing_ok=True)
        raise DownloadError(
            f"size mismatch downloading {url}: got {downloaded}, expected {effective}"
        )

    part.replace(dest)
    return dest


def download_hls(
    url: str,
    dest: Path,
    *,
    ffmpeg: str = "ffmpeg",
    on_progress: ProgressCb | None = None,
    poll_interval: float = 0.5,
) -> Path:
    if shutil.which(ffmpeg) is None:
        raise FFmpegMissingError("ffmpeg not found on PATH; required for HLS (.m3u8) downloads")
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    part.unlink(missing_ok=True)
    cmd = [ffmpeg, "-y", "-i", url, "-c", "copy", str(part)]

    def report() -> None:
        # HLS has no known total, so report bytes written so far against an
        # indeterminate total (None) to drive a live size/speed display.
        if on_progress is not None:
            with contextlib.suppress(OSError):
                on_progress(part.stat().st_size, None)

    # Stream ffmpeg's chatty stderr to a temp file rather than a PIPE we never
    # read; an unread PIPE can fill its buffer and deadlock the child.
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as errf:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=errf)
        try:
            while proc.poll() is None:
                report()
                time.sleep(poll_interval)
        finally:
            proc.wait()
        if proc.returncode != 0:
            errf.seek(0)
            tail = errf.read()[-300:]
            part.unlink(missing_ok=True)
            raise DownloadError(f"ffmpeg failed ({proc.returncode}): {tail}")
    report()
    if part.stat().st_size == 0:
        part.unlink(missing_ok=True)
        raise DownloadError("ffmpeg produced an empty output file")
    part.replace(dest)
    return dest
