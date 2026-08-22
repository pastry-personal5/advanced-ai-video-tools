"""Presentation-only source preview boundary for the job editor."""

# PySide6 exposes Qt types dynamically, which Pylint cannot introspect.
# pylint: disable=no-name-in-module,unnecessary-lambda

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl, Qt, Signal, Slot
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QFrame, QHBoxLayout, QSizePolicy, QToolButton, QVBoxLayout, QWidget


class SourcePreviewPane(QFrame):
    """Display the selected local source identity without affecting processing."""

    def __init__(self, parent: QWidget | None = None) -> None:
        # Declarative widget construction is intentionally kept together.
        # pylint: disable=too-many-statements
        super().__init__(parent)
        self.setObjectName("sourcePreviewPane")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.setMinimumWidth(600)
        self.video = QVideoWidget()
        self.video.setObjectName("sourcePreviewVideo")
        self.video.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.video.setMinimumSize(0, 0)
        self.video.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setMuted(True)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video)
        self.previous_button = self._control("⏪", "Previous clip", "previewPreviousButton")
        self.play_pause_button = self._control("▶", "Play or pause preview", "previewPlayPauseButton")
        self.first_frame_button = self._control("⏮", "Go to the first frame of the video", "previewFirstFrameButton")
        self.last_frame_button = self._control("⏭", "Go to the last frame of the video", "previewLastFrameButton")
        self.next_button = self._control("⏩", "Next clip", "previewNextButton")
        controls = QHBoxLayout()
        for button in (self.play_pause_button, self.first_frame_button, self.last_frame_button, self.previous_button, self.next_button):
            controls.addWidget(button)
        self._buttons = (self.play_pause_button, self.first_frame_button, self.last_frame_button, self.previous_button, self.next_button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.video, 1)
        layout.addLayout(controls)
        layout.setStretch(1, 1)
        self.previous_button.clicked.connect(lambda: self.previous_requested.emit())
        self.play_pause_button.clicked.connect(self._toggle_playback)
        self.first_frame_button.clicked.connect(lambda: self.first_frame_requested.emit())
        self.last_frame_button.clicked.connect(lambda: self.last_frame_requested.emit())
        self.next_button.clicked.connect(lambda: self.next_requested.emit())
        self._paths: tuple[Path, ...] = ()
        self._selected_index = -1
        self.player.playbackStateChanged.connect(self._playback_state_changed)
        self.player.mediaStatusChanged.connect(self._media_status_changed)
        self.player.errorOccurred.connect(self._preview_error)

    @staticmethod
    def _control(glyph: str, label: str, object_name: str) -> QToolButton:
        """Create an icon-only preview control with native accessibility text."""

        button = QToolButton()
        button.setText(glyph)
        button.setObjectName(object_name)
        button.setAccessibleName(label)
        button.setToolTip(label)
        button.setAutoRaise(True)
        return button

    def set_source(self, path: Path | None) -> None:
        """Show only the selected editor source filename."""

        self.player.stop()
        if path is None:
            self.player.setSource(QUrl())
        else:
            self.player.setSource(QUrl.fromLocalFile(str(path)))
            self.player.play()

    def set_sources(self, paths: tuple[Path, ...], selected_index: int) -> None:
        """Update navigation state from the editor's ordered source list."""

        self._paths = paths
        self._selected_index = selected_index
        self.set_source(paths[selected_index] if 0 <= selected_index < len(paths) else None)
        has_source = bool(paths) and 0 <= selected_index < len(paths)
        self.play_pause_button.setEnabled(has_source)
        self.first_frame_button.setEnabled(has_source)
        self.last_frame_button.setEnabled(has_source)
        self.previous_button.setEnabled(has_source and selected_index > 0)
        self.next_button.setEnabled(has_source and selected_index < len(paths) - 1)

    def heightForWidth(self, width: int) -> int:  # pylint: disable=invalid-name
        """Return the approved 3:4 preview geometry for a given width."""

        return max(1, width * 4 // 3)

    def hasHeightForWidth(self) -> bool:  # pylint: disable=invalid-name
        """Declare the width-driven preview geometry to Qt layouts."""

        return True

    @Slot()
    def _toggle_playback(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    @Slot()
    def go_to_first_frame(self) -> None:
        """Pause and seek the active source to its first frame."""

        self.player.pause()
        self.player.setPosition(0)

    @Slot()
    def go_to_last_frame(self) -> None:
        """Pause and seek the active source to its last available frame."""

        self.player.pause()
        self.player.setPosition(max(0, self.player.duration() - 1))

    @Slot(QMediaPlayer.PlaybackState)
    def _playback_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.play_pause_button.setText("Ⅱ" if playing else "▶")
        self.play_pause_button.setToolTip("Pause preview" if playing else "Play preview")

    @Slot(QMediaPlayer.MediaStatus)
    def _media_status_changed(self, status: QMediaPlayer.MediaStatus) -> None:
        """Keep the final decoded frame visible when native playback ends."""

        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.player.pause()
            if self.player.duration() > 0:
                self.player.setPosition(max(0, self.player.duration() - 1))

    @Slot(QMediaPlayer.Error, str)
    def _preview_error(self, _error: QMediaPlayer.Error, _error_string: str) -> None:
        message = "Preview unavailable; preflight can still inspect this clip."
        self.preview_error.emit(message)

    def shutdown(self) -> None:
        """Stop playback and release native preview outputs during window close."""

        self.player.stop()
        self.player.setVideoOutput(None)
        self.player.setAudioOutput(None)

    previous_requested = Signal()
    play_pause_requested = Signal()
    first_frame_requested = Signal()
    last_frame_requested = Signal()
    next_requested = Signal()
    preview_error = Signal(str)
