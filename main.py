"""Playlist Downloader -- a CustomTkinter desktop app for downloading
YouTube playlists one video at a time via yt-dlp.
"""

from __future__ import annotations

import queue
import threading
from tkinter import filedialog, messagebox
from typing import List, Optional

import customtkinter as ctk

from models import DownloadProgress, Playlist, Video
from ytdlp_manager import (
    PlaylistDownloader,
    is_ffmpeg_available,
    is_ytdlp_available,
    load_playlist,
)
from video_widget import VideoRowWidget

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

WINDOW_TITLE = "Playlist Downloader"
WINDOW_SIZE = "1200x800"

_BG_COLOR = "#181b22"
_PANEL_COLOR = "#1f232d"
_ACCENT_COLOR = "#5b8def"
_ACCENT_HOVER = "#4a76c9"
_MUTED_COLOR = "#9aa1b4"
_DANGER_COLOR = "#e0575b"


class PlaylistDownloaderApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()

        self.title(WINDOW_TITLE)
        self.geometry(WINDOW_SIZE)
        self.minsize(900, 600)
        self.configure(fg_color=_BG_COLOR)

        self._playlist: Optional[Playlist] = None
        self._video_rows: List[VideoRowWidget] = []
        self._is_downloading = False
        self._downloader: Optional[PlaylistDownloader] = None
        self._download_failure_count = 0
        self._download_total_count = 0

        self.protocol("WM_DELETE_WINDOW", self._handle_close)

        # Thread-safe channel: background threads push UI-update callables,
        # the main loop drains it on a timer via `after`.
        self._ui_queue: "queue.Queue" = queue.Queue()

        self._build_layout()
        self._poll_ui_queue()

        if not is_ytdlp_available():
            self.after(
                200,
                lambda: messagebox.showwarning(
                    "yt-dlp not found",
                    "yt-dlp was not found on your PATH. Install the packages in "
                    "requirements.txt before loading or downloading playlists.",
                ),
            )

    # ------------------------------------------------------------------
    # Layout construction
    # ------------------------------------------------------------------
    def _build_layout(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self._build_url_bar()
        self._build_selection_bar()
        self._build_video_list()
        self._build_download_bar()

    def _build_url_bar(self) -> None:
        container = ctk.CTkFrame(self, fg_color=_PANEL_COLOR, corner_radius=14)
        container.grid(row=0, column=0, sticky="ew", padx=20, pady=(20, 10))
        container.grid_columnconfigure(0, weight=1)

        self._url_entry = ctk.CTkEntry(
            container,
            placeholder_text="Paste a YouTube playlist URL...",
            height=42,
            corner_radius=10,
            font=ctk.CTkFont(size=14),
        )
        self._url_entry.grid(row=0, column=0, sticky="ew", padx=(16, 10), pady=16)
        self._url_entry.bind("<Return>", lambda _event: self._handle_load_playlist())

        self._load_button = ctk.CTkButton(
            container,
            text="Load Playlist",
            height=42,
            width=150,
            corner_radius=10,
            fg_color=_ACCENT_COLOR,
            hover_color=_ACCENT_HOVER,
            font=ctk.CTkFont(size=14, weight="bold"),
            command=self._handle_load_playlist,
        )
        self._load_button.grid(row=0, column=1, padx=(0, 16), pady=16)

    def _build_selection_bar(self) -> None:
        container = ctk.CTkFrame(self, fg_color="transparent")
        container.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 10))
        container.grid_columnconfigure(0, weight=1)

        self._playlist_title_label = ctk.CTkLabel(
            container,
            text="No playlist loaded yet",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color="#f2f3f7",
            anchor="w",
        )
        self._playlist_title_label.grid(row=0, column=0, sticky="w")

        button_group = ctk.CTkFrame(container, fg_color="transparent")
        button_group.grid(row=0, column=1, sticky="e")

        self._select_all_button = ctk.CTkButton(
            button_group,
            text="Select All",
            width=110,
            height=34,
            corner_radius=8,
            fg_color=_PANEL_COLOR,
            hover_color=_ACCENT_HOVER,
            command=self._handle_select_all,
            state="disabled",
        )
        self._select_all_button.grid(row=0, column=0, padx=(0, 8))

        self._select_none_button = ctk.CTkButton(
            button_group,
            text="Select None",
            width=110,
            height=34,
            corner_radius=8,
            fg_color=_PANEL_COLOR,
            hover_color=_ACCENT_HOVER,
            command=self._handle_select_none,
            state="disabled",
        )
        self._select_none_button.grid(row=0, column=1, padx=(0, 8))

        self._invert_selection_button = ctk.CTkButton(
            button_group,
            text="Invert Selection",
            width=130,
            height=34,
            corner_radius=8,
            fg_color=_PANEL_COLOR,
            hover_color=_ACCENT_HOVER,
            command=self._handle_invert_selection,
            state="disabled",
        )
        self._invert_selection_button.grid(row=0, column=2)

        self._selected_count_label = ctk.CTkLabel(
            container,
            text="",
            font=ctk.CTkFont(size=13),
            text_color=_MUTED_COLOR,
            anchor="w",
        )
        self._selected_count_label.grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))

    def _build_video_list(self) -> None:
        self._video_list_frame = ctk.CTkScrollableFrame(
            self,
            fg_color=_PANEL_COLOR,
            corner_radius=14,
            scrollbar_button_color="#3a4050",
            scrollbar_button_hover_color=_ACCENT_HOVER,
        )
        self._video_list_frame.grid(row=2, column=0, sticky="nsew", padx=20, pady=(0, 10))
        self._video_list_frame.grid_columnconfigure(0, weight=1)

        self._empty_state_label = ctk.CTkLabel(
            self._video_list_frame,
            text="Load a playlist to see its videos here.",
            text_color=_MUTED_COLOR,
            font=ctk.CTkFont(size=14),
        )
        self._empty_state_label.grid(row=0, column=0, pady=40)

    def _build_download_bar(self) -> None:
        container = ctk.CTkFrame(self, fg_color=_PANEL_COLOR, corner_radius=14)
        container.grid(row=3, column=0, sticky="ew", padx=20, pady=(0, 20))
        container.grid_columnconfigure(0, weight=1)

        status_row = ctk.CTkFrame(container, fg_color="transparent")
        status_row.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 0))
        status_row.grid_columnconfigure(0, weight=1)

        self._current_video_label = ctk.CTkLabel(
            status_row,
            text="Ready.",
            anchor="w",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#f2f3f7",
        )
        self._current_video_label.grid(row=0, column=0, sticky="w")

        self._stats_label = ctk.CTkLabel(
            status_row,
            text="",
            anchor="e",
            font=ctk.CTkFont(size=12),
            text_color=_MUTED_COLOR,
        )
        self._stats_label.grid(row=0, column=1, sticky="e")

        self._progress_bar = ctk.CTkProgressBar(
            container,
            height=14,
            corner_radius=7,
            progress_color=_ACCENT_COLOR,
        )
        self._progress_bar.grid(row=1, column=0, sticky="ew", padx=16, pady=(8, 4))
        self._progress_bar.set(0)

        self._overall_label = ctk.CTkLabel(
            container,
            text="",
            anchor="w",
            font=ctk.CTkFont(size=12),
            text_color=_MUTED_COLOR,
        )
        self._overall_label.grid(row=2, column=0, sticky="w", padx=16, pady=(0, 12))

        self._download_button = ctk.CTkButton(
            container,
            text="Download Selected",
            height=46,
            corner_radius=10,
            fg_color=_ACCENT_COLOR,
            hover_color=_ACCENT_HOVER,
            font=ctk.CTkFont(size=15, weight="bold"),
            command=self._handle_download_selected,
            state="disabled",
        )
        self._download_button.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 16))

    # ------------------------------------------------------------------
    # UI thread <-> background thread bridge
    # ------------------------------------------------------------------
    def _poll_ui_queue(self) -> None:
        try:
            while True:
                callback = self._ui_queue.get_nowait()
                callback()
        except queue.Empty:
            pass
        self.after(50, self._poll_ui_queue)

    def _post_to_ui(self, callback) -> None:
        self._ui_queue.put(callback)

    # ------------------------------------------------------------------
    # Loading a playlist
    # ------------------------------------------------------------------
    def _handle_load_playlist(self) -> None:
        url = self._url_entry.get().strip()
        if not url:
            messagebox.showinfo("Playlist Downloader", "Paste a playlist URL first.")
            return

        self._load_button.configure(state="disabled", text="Loading...")
        self._reset_playlist_state()
        self._playlist_title_label.configure(text="Loading playlist...")

        thread = threading.Thread(target=self._load_playlist_worker, args=(url,), daemon=True)
        thread.start()

    def _load_playlist_worker(self, url: str) -> None:
        try:
            playlist = load_playlist(url)
        except Exception as exc:  # noqa: BLE001 -- surfaced to the user as-is
            # Capture the message now -- `exc` itself is cleared by Python as
            # soon as this `except` block exits, so it must not be captured
            # by reference inside a closure that runs later on the UI thread.
            error_message = str(exc)
            self._post_to_ui(lambda: self._handle_playlist_load_error(error_message))
            return

        self._post_to_ui(lambda: self._handle_playlist_loaded(playlist))

    def _handle_playlist_load_error(self, error_message: str) -> None:
        self._load_button.configure(state="normal", text="Load Playlist")
        self._reset_playlist_state()
        messagebox.showerror("Failed to load playlist", error_message)

    def _reset_playlist_state(self) -> None:
        """Clear any previously loaded playlist so stale data/state can't linger."""
        self._playlist = None
        self._clear_video_list()
        self._playlist_title_label.configure(text="No playlist loaded yet")
        self._selected_count_label.configure(text="")
        for button in (
            self._select_all_button,
            self._select_none_button,
            self._invert_selection_button,
            self._download_button,
        ):
            button.configure(state="disabled")

    def _handle_playlist_loaded(self, playlist: Playlist) -> None:
        self._playlist = playlist
        self._load_button.configure(state="normal", text="Load Playlist")
        self._playlist_title_label.configure(text=playlist.title)
        self._populate_video_list(playlist.videos)

        for button in (
            self._select_all_button,
            self._select_none_button,
            self._invert_selection_button,
            self._download_button,
        ):
            button.configure(state="normal")

        self._update_selected_count()

    # ------------------------------------------------------------------
    # Video list rendering
    # ------------------------------------------------------------------
    def _clear_video_list(self) -> None:
        for row in self._video_rows:
            row.destroy()
        self._video_rows = []
        self._empty_state_label.grid_forget()

    def _populate_video_list(self, videos: List[Video]) -> None:
        self._clear_video_list()
        for index, video in enumerate(videos):
            row = VideoRowWidget(
                self._video_list_frame,
                video=video,
                on_toggle=self._handle_video_toggled,
            )
            row.grid(row=index, column=0, sticky="ew", padx=8, pady=6)
            self._video_rows.append(row)

    def _handle_video_toggled(self, _video: Video) -> None:
        self._update_selected_count()

    # ------------------------------------------------------------------
    # Selection controls
    # ------------------------------------------------------------------
    def _handle_select_all(self) -> None:
        for row in self._video_rows:
            row.set_selected(True)
        self._update_selected_count()

    def _handle_select_none(self) -> None:
        for row in self._video_rows:
            row.set_selected(False)
        self._update_selected_count()

    def _handle_invert_selection(self) -> None:
        for row in self._video_rows:
            row.set_selected(not row.video.selected)
        self._update_selected_count()

    def _update_selected_count(self) -> None:
        if self._playlist is None:
            self._selected_count_label.configure(text="")
            return
        selected = len(self._playlist.selected_videos)
        total = len(self._playlist.videos)
        self._selected_count_label.configure(text=f"{selected} of {total} videos selected")

    # ------------------------------------------------------------------
    # Downloading
    # ------------------------------------------------------------------
    def _handle_download_selected(self) -> None:
        if self._playlist is None or self._is_downloading:
            return

        selected_videos = self._playlist.selected_videos
        if not selected_videos:
            messagebox.showinfo("Playlist Downloader", "Select at least one video first.")
            return

        destination_folder = filedialog.askdirectory(title="Choose a download folder")
        if not destination_folder:
            return

        if not is_ffmpeg_available():
            messagebox.showinfo(
                "FFmpeg not found",
                "FFmpeg was not found on your PATH. Downloads will continue, but "
                "yt-dlp may not be able to merge separate video and audio streams "
                "into a single file for every format.",
            )

        self._is_downloading = True
        self._download_failure_count = 0
        self._download_total_count = len(selected_videos)
        self._set_controls_enabled(False)
        self._progress_bar.set(0)
        self._current_video_label.configure(text="Starting download...")
        self._stats_label.configure(text="")
        self._overall_label.configure(text=f"0 of {len(selected_videos)} videos downloaded")

        self._downloader = PlaylistDownloader(
            videos=selected_videos,
            destination_folder=destination_folder,
            on_progress=self._handle_download_progress,
            on_video_finished=self._handle_video_finished,
            on_all_finished=self._handle_all_downloads_finished,
        )
        self._downloader.start()

    def _handle_download_progress(
        self, index: int, total: int, progress: DownloadProgress
    ) -> None:
        def update() -> None:
            self._current_video_label.configure(
                text=f"Downloading: {progress.video_title}"
            )
            self._progress_bar.set(max(0.0, min(progress.percent / 100.0, 1.0)))

            stats_parts = [f"{progress.percent:.1f}%"]
            if progress.speed:
                stats_parts.append(progress.speed)
            if progress.eta:
                stats_parts.append(f"ETA {progress.eta}")
            self._stats_label.configure(text="  |  ".join(stats_parts))

            self._overall_label.configure(
                text=f"Video {index + 1} of {total} -- {progress.status}"
            )

        self._post_to_ui(update)

    def _handle_video_finished(
        self, index: int, total: int, video: Video, success: bool
    ) -> None:
        def update() -> None:
            status = "done" if success else "failed"
            if not success:
                self._download_failure_count += 1
            self._overall_label.configure(
                text=f"{index + 1} of {total} videos processed ({status}: {video.title})"
            )

        self._post_to_ui(update)

    def _handle_all_downloads_finished(self) -> None:
        def update() -> None:
            self._is_downloading = False
            self._set_controls_enabled(True)
            self._progress_bar.set(1.0)
            self._stats_label.configure(text="")

            failures = self._download_failure_count
            total = self._download_total_count
            if failures == 0:
                self._current_video_label.configure(text="Download complete.")
                messagebox.showinfo(
                    "Playlist Downloader", "Finished downloading selected videos."
                )
            else:
                succeeded = total - failures
                self._current_video_label.configure(
                    text=f"Download finished with {failures} failure(s)."
                )
                messagebox.showwarning(
                    "Playlist Downloader",
                    f"Finished: {succeeded} of {total} videos downloaded successfully. "
                    f"{failures} video(s) failed -- check the console output for details.",
                )

        self._post_to_ui(update)

    def _set_controls_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self._download_button.configure(state=state)
        self._load_button.configure(state=state)
        self._select_all_button.configure(state=state)
        self._select_none_button.configure(state=state)
        self._invert_selection_button.configure(state=state)

    def _handle_close(self) -> None:
        """Cancel any in-flight download before the window closes."""
        if self._downloader is not None:
            self._downloader.cancel()
        self.destroy()


def main() -> None:
    app = PlaylistDownloaderApp()
    app.mainloop()


if __name__ == "__main__":
    main()
