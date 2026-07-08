"""Data models used across the Playlist Downloader application."""

from dataclasses import dataclass, field
from typing import List


@dataclass
class Video:
    """A single video entry belonging to a playlist."""

    video_id: str
    title: str
    selected: bool = False

    @property
    def thumbnail_url(self) -> str:
        return f"https://i.ytimg.com/vi/{self.video_id}/hqdefault.jpg"

    @property
    def watch_url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"


@dataclass
class Playlist:
    """A YouTube playlist loaded via yt-dlp."""

    title: str
    videos: List[Video] = field(default_factory=list)

    @property
    def selected_videos(self) -> List[Video]:
        return [video for video in self.videos if video.selected]


@dataclass
class DownloadProgress:
    """Progress information for a single video currently being downloaded."""

    video_title: str
    percent: float = 0.0
    speed: str = ""
    eta: str = ""
    status: str = "starting"  # starting | downloading | finished | error
