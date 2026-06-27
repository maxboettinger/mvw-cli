from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Callable

import httpx

from mvw.models import MediathekResult

ProgressCb = Callable[[int, "int | None"], None]


class DownloadError(Exception):
    pass


class FFmpegMissingError(DownloadError):
    pass


def is_hls(url: str) -> bool:
    return ".m3u8" in url.split("?", 1)[0].lower()


def pick_resolution(result: MediathekResult, preference: str) -> tuple[str, str]:
    url, tier = result.resolve_video(preference)
    if not url:
        raise DownloadError("no video URL available for this entry")
    return url, tier


def download(
    url: str,
    dest: Path,
    *,
    on_progress: ProgressCb | None = None,
    resume: bool = True,
    client: httpx.Client | None = None,
) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    existing = part.stat().st_size if (resume and part.exists()) else 0

    headers = {}
    mode = "wb"
    if existing:
        headers["Range"] = f"bytes={existing}-"
        mode = "ab"

    owns_client = client is None
    client = client or httpx.Client(timeout=60.0, follow_redirects=True)
    try:
        with client.stream("GET", url, headers=headers) as resp:
            if resp.status_code not in (200, 206):
                raise DownloadError(f"HTTP {resp.status_code} downloading {url}")
            if resp.status_code == 200:
                existing = 0
                mode = "wb"
            total: int | None = None
            cl = resp.headers.get("content-length")
            if cl is not None:
                total = int(cl) + existing
            downloaded = existing
            with open(part, mode) as fh:
                for chunk in resp.iter_bytes():
                    fh.write(chunk)
                    downloaded += len(chunk)
                    if on_progress:
                        on_progress(downloaded, total)
    except httpx.TransportError as exc:
        raise DownloadError(f"network error: {exc}") from exc
    finally:
        if owns_client:
            client.close()

    part.replace(dest)
    return dest


def download_hls(url: str, dest: Path, *, ffmpeg: str = "ffmpeg") -> Path:
    if shutil.which(ffmpeg) is None:
        raise FFmpegMissingError(
            "ffmpeg not found on PATH; required for HLS (.m3u8) downloads"
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ffmpeg, "-y", "-i", url, "-c", "copy", str(dest)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise DownloadError(f"ffmpeg failed ({proc.returncode}): {proc.stderr[-300:]}")
    return dest
