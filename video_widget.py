"""A single row widget representing one playlist video."""

from __future__ import annotations

import io
import threading
from typing import Callable, Optional

import customtkinter as ctk
import requests
from PIL import Image

from models import Video

THUMBNAIL_WIDTH = 120
THUMBNAIL_HEIGHT = 90

_ROW_BG = "#232733"
_ROW_BG_HOVER = "#2b3040"
_TITLE_COLOR = "#e6e8ef"


class VideoRowWidget(ctk.CTkFrame):
    """One row in the scrollable playlist list.

    Displays a checkbox, thumbnail, and title. Clicking anywhere on the row
    toggles the checkbox. Thumbnails are fetched over plain HTTP (never via
    yt-dlp) on a background thread so the UI never blocks while loading
    images.
    """

    def __init__(
        self,
        master,
        video: Video,
        on_toggle: Callable[[Video], None],
        **kwargs,
    ) -> None:
        super().__init__(
            master,
            fg_color=_ROW_BG,
            corner_radius=10,
            **kwargs,
        )
        self._video = video
        self._on_toggle = on_toggle
        self._photo_image: Optional[ctk.CTkImage] = None

        self.grid_columnconfigure(2, weight=1)

        self._checkbox_var = ctk.BooleanVar(value=video.selected)
        self._checkbox = ctk.CTkCheckBox(
            self,
            text="",
            variable=self._checkbox_var,
            command=self._handle_checkbox_toggle,
            width=24,
            checkbox_width=22,
            checkbox_height=22,
            corner_radius=6,
            border_color="#565d70",
            fg_color="#5b8def",
            hover_color="#4a76c9",
        )
        self._checkbox.grid(row=0, column=0, padx=(14, 10), pady=14, sticky="w")

        self._thumbnail_label = ctk.CTkLabel(
            self,
            text="",
            width=THUMBNAIL_WIDTH,
            height=THUMBNAIL_HEIGHT,
            fg_color="#181b22",
            corner_radius=8,
        )
        self._thumbnail_label.grid(row=0, column=1, padx=(0, 14), pady=10)

        self._title_label = ctk.CTkLabel(
            self,
            text=video.title,
            text_color=_TITLE_COLOR,
            font=ctk.CTkFont(size=14, weight="normal"),
            anchor="w",
            justify="left",
            wraplength=560,
        )
        self._title_label.grid(row=0, column=2, sticky="ew", padx=(0, 14), pady=10)

        for widget in (self, self._thumbnail_label, self._title_label):
            widget.bind("<Enter>", self._handle_mouse_enter)
            widget.bind("<Leave>", self._handle_mouse_leave)
            widget.bind("<Button-1>", self._handle_row_click)

        self._load_thumbnail_async()

    @property
    def video(self) -> Video:
        return self._video

    def set_selected(self, selected: bool) -> None:
        self._video.selected = selected
        self._checkbox_var.set(selected)

    def _handle_row_click(self, _event) -> None:
        new_value = not self._checkbox_var.get()
        self._checkbox_var.set(new_value)
        self._handle_checkbox_toggle()

    def _handle_checkbox_toggle(self) -> None:
        self._video.selected = self._checkbox_var.get()
        self._on_toggle(self._video)

    def _handle_mouse_enter(self, _event) -> None:
        self.configure(fg_color=_ROW_BG_HOVER)

    def _handle_mouse_leave(self, _event) -> None:
        self.configure(fg_color=_ROW_BG)

    def _load_thumbnail_async(self) -> None:
        thread = threading.Thread(target=self._fetch_thumbnail, daemon=True)
        thread.start()

    def _fetch_thumbnail(self) -> None:
        try:
            response = requests.get(self._video.thumbnail_url, timeout=10)
            response.raise_for_status()
            image = Image.open(io.BytesIO(response.content))
            image = image.convert("RGB")
            image = image.resize((THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT), Image.LANCZOS)
        except (requests.RequestException, OSError):
            return

        def apply_image() -> None:
            if not self.winfo_exists():
                return
            self._photo_image = ctk.CTkImage(
                light_image=image, dark_image=image, size=(THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT)
            )
            self._thumbnail_label.configure(image=self._photo_image, text="")

        try:
            self.after(0, apply_image)
        except RuntimeError:
            pass
