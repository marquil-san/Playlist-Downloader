"""All interaction with the yt-dlp CLI lives here.

Two responsibilities:
1. Loading a playlist's flat video list (`--flat-playlist --dump-single-json`).
2. Downloading videos one at a time while reporting live progress.
"""

from __future__ import annotations

import json
import re
import shutil
from typing import Callable, List, Optional

from command_executor import CommandExecutor, run_command_capture_output
from models import DownloadProgress, Playlist, Video

# Matches yt-dlp's default progress line, e.g.:
# "[download]  12.3% of   50.00MiB at    1.20MiB/s ETA 00:35"
_PROGRESS_RE = re.compile(
    r"\[download\]\s+(?P<percent>[\d.]+)%"
    r"(?:\s+of\s+\S+)?"
    r"(?:\s+at\s+(?P<speed>\S+))?"
    r"(?:\s+ETA\s+(?P<eta>\S+))?"
)

_DESTINATION_RE = re.compile(r"\[download\]\s+Destination:\s+(?P<path>.+)")
_ALREADY_RE = re.compile(r"\[download\]\s+(?P<path>.+)\s+has already been downloaded")
_MERGER_RE = re.compile(r"\[Merger\]")


def is_ytdlp_available() -> bool:
    return shutil.which("yt-dlp") is not None


def is_ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def load_playlist(playlist_url: str) -> Playlist:
    """Fetch a playlist's flat video list via yt-dlp.

    Must be called from a background thread -- this blocks until yt-dlp
    finishes fetching and parsing the playlist metadata.
    """
    if not is_ytdlp_available():
        raise RuntimeError(
            "yt-dlp was not found on this system. Install the dependencies "
            "from requirements.txt before loading a playlist."
        )

    output = run_command_capture_output(
        ["yt-dlp", "--flat-playlist", "--dump-single-json", playlist_url]
    )
    data = json.loads(output)

    playlist_title = data.get("title") or "Untitled Playlist"
    entries = data.get("entries") or []

    videos: List[Video] = []
    for entry in entries:
        if not entry:
            continue
        video_id = entry.get("id")
        title = entry.get("title") or video_id
        if not video_id:
            continue
        videos.append(Video(video_id=video_id, title=title))

    if not videos:
        raise RuntimeError("No videos were found in this playlist.")

    return Playlist(title=playlist_title, videos=videos)


def parse_progress_line(line: str, current_title: str) -> Optional[DownloadProgress]:
    """Parse a single line of yt-dlp output into a DownloadProgress update."""
    match = _PROGRESS_RE.search(line)
    if match:
        percent = float(match.group("percent"))
        speed = match.group("speed") or ""
        eta = match.group("eta") or ""
        return DownloadProgress(
            video_title=current_title,
            percent=percent,
            speed=speed,
            eta=eta,
            status="downloading",
        )

    if _DESTINATION_RE.search(line):
        return DownloadProgress(video_title=current_title, percent=0.0, status="downloading")

    if _ALREADY_RE.search(line):
        return DownloadProgress(video_title=current_title, percent=100.0, status="finished")

    if _MERGER_RE.search(line):
        return DownloadProgress(
            video_title=current_title, percent=100.0, speed="", eta="", status="merging"
        )

    return None


def build_download_command(video: Video, destination_folder: str) -> List[str]:
    """Build the exact yt-dlp download command for a single video."""
    output_template = f"{destination_folder}/%(title)s.%(ext)s"
    return [
        "yt-dlp",
        "-f",
        "bv*+ba/b",
        "-o",
        output_template,
        video.watch_url,
    ]


class PlaylistDownloader:
    """Downloads a list of videos sequentially, one at a time.

    Progress and lifecycle events are delivered through callbacks. Callbacks
    fire from a background thread; the caller is responsible for marshaling
    UI updates back onto the main thread.
    """

    def __init__(
        self,
        videos: List[Video],
        destination_folder: str,
        on_progress: Callable[[int, int, DownloadProgress], None],
        on_video_finished: Callable[[int, int, Video, bool], None],
        on_all_finished: Callable[[], None],
    ) -> None:
        self._videos = videos
        self._destination_folder = destination_folder
        self._on_progress = on_progress
        self._on_video_finished = on_video_finished
        self._on_all_finished = on_all_finished
        self._current_index = -1
        self._cancelled = False
        self._current_executor: Optional[CommandExecutor] = None

    def start(self) -> None:
        self._download_next()

    def cancel(self) -> None:
        self._cancelled = True
        if self._current_executor is not None:
            self._current_executor.cancel()

    def _download_next(self) -> None:
        if self._cancelled:
            self._on_all_finished()
            return

        self._current_index += 1
        if self._current_index >= len(self._videos):
            self._on_all_finished()
            return

        video = self._videos[self._current_index]
        command = build_download_command(video, self._destination_folder)
        total = len(self._videos)
        index = self._current_index

        def handle_line(line: str) -> None:
            progress = parse_progress_line(line, video.title)
            if progress is not None:
                self._on_progress(index, total, progress)

        def handle_finished(return_code: int) -> None:
            success = return_code == 0
            self._on_video_finished(index, total, video, success)
            self._download_next()

        def handle_error(exc: Exception) -> None:
            self._on_video_finished(index, total, video, False)
            self._download_next()

        self._current_executor = CommandExecutor(
            command=command,
            on_line=handle_line,
            on_finished=handle_finished,
            on_error=handle_error,
        )
        self._current_executor.start()
