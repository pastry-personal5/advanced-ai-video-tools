"""Presentation-only source preview boundary for the job editor."""

# PySide6 exposes Qt types dynamically, which Pylint cannot introspect.
# pylint: disable=no-name-in-module,unnecessary-lambda

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSignalBlocker, QSize, QUrl, Qt, Signal, Slot
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QCheckBox, QGroupBox, QHBoxLayout, QLabel, QSlider, QSizePolicy, QStyle, QToolButton, QVBoxLayout, QWidget

from advanced_ai_video_tools.gui.theme import SPACE_2, SPACE_3

VOLUME_ICON_COLOR = "#b8bcc2"
VOLUME_ICON_OPTICAL_OFFSET = 0


class SourcePreviewPane(QGroupBox):
    """Display the selected local source identity without affecting processing."""

    def __init__(self, parent: QWidget | None = None, *, muted: bool = True, volume: int = 100) -> None:
        # Declarative widget construction is intentionally kept together.
        # pylint: disable=too-many-statements
        super().__init__("Preview", parent)
        self.setObjectName("sourcePreviewPane")
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.setMinimumWidth(450)
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
        self.mute_toggle = QCheckBox()
        self.mute_toggle.setObjectName("previewMuteToggle")
        self.mute_toggle.setAccessibleName("Mute preview")
        self.mute_toggle.setToolTip("Mute preview")
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setObjectName("previewVolumeSlider")
        self.volume_slider.setAccessibleName("Preview volume")
        self.volume_slider.setToolTip("Preview volume")
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setFixedHeight(24)
        self.progress_slider = QSlider(Qt.Orientation.Horizontal)
        self.progress_slider.setObjectName("previewProgressSlider")
        self.progress_slider.setAccessibleName("Preview progress")
        self.progress_slider.setToolTip("Seek preview")
        self.progress_slider.setRange(0, 0)
        self.progress_slider.setEnabled(False)
        self.progress_slider.setTracking(True)
        self.progress_slider.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.progress_slider.setFixedHeight(24)
        self.preview_time_label = QLabel("0:00 / 0:00")
        self.preview_time_label.setObjectName("previewTimeLabel")
        self.preview_time_label.setAccessibleName("Preview time")
        self.preview_time_label.setMinimumWidth(84)
        self.preview_time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._preferred_muted = bool(muted)
        self._duration_ms = 0
        self._apply_audio_preferences(muted, volume)
        self.previous_button = self._control("←", "Previous clip", "previewPreviousButton", muted=True)
        self.play_pause_button = self._control("▶", "Play preview", "previewPlayPauseButton")
        self.first_frame_button = self._control("⏮", "Go to first frame", "previewFirstFrameButton")
        self.last_frame_button = self._control("⏭", "Go to last frame", "previewLastFrameButton")
        self.next_button = self._control("→", "Next clip", "previewNextButton", muted=True)
        self.preview_label = QLabel("Preview")
        self.preview_label.setObjectName("previewLabel")
        self.preview_label.setAccessibleName("Preview status")
        self.preview_label.setWordWrap(True)
        preview_font = QFont(self.preview_label.font())
        preview_font.setPointSize(13)
        preview_font.setWeight(QFont.Weight.DemiBold)
        self.preview_label.setFont(preview_font)
        self.preview_label.setVisible(False)
        self.volume_label = QLabel("Output volume")
        self.volume_label.setObjectName("outputVolumeLabel")
        self.volume_label.setFixedHeight(24)
        self.volume_label.setContentsMargins(0, 0, 16, 0)
        self.minimum_volume_icon = self._volume_icon(QStyle.StandardPixmap.SP_MediaVolumeMuted, "Minimum volume", "minimumVolumeIcon")
        self.maximum_volume_icon = self._volume_icon(QStyle.StandardPixmap.SP_MediaVolume, "Maximum volume", "maximumVolumeIcon")
        self.mute_label = QLabel("Mute")
        self.mute_label.setObjectName("muteLabel")
        self.mute_label.setBuddy(self.mute_toggle)
        playback_controls = QHBoxLayout()
        playback_controls.setContentsMargins(0, 0, 0, 0)
        playback_controls.setSpacing(SPACE_2)
        for button in (self.play_pause_button, self.first_frame_button, self.last_frame_button):
            playback_controls.addWidget(button)
        navigation_controls = QHBoxLayout()
        navigation_controls.setContentsMargins(0, 0, 0, 0)
        navigation_controls.setSpacing(SPACE_2)
        for button in (self.previous_button, self.next_button):
            navigation_controls.addWidget(button)
        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.addLayout(playback_controls)
        controls.addStretch(1)
        controls.addLayout(navigation_controls)
        self._buttons = (self.play_pause_button, self.first_frame_button, self.last_frame_button, self.previous_button, self.next_button)
        self.volume_row = QWidget()
        self.volume_row.setObjectName("previewVolumeRow")
        self.volume_row.setFixedHeight(24)
        self.volume_row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        volume_controls = QHBoxLayout(self.volume_row)
        volume_controls.setContentsMargins(0, 0, 0, 0)
        volume_controls.setSpacing(SPACE_2)
        volume_controls.addWidget(self.volume_label, alignment=Qt.AlignmentFlag.AlignVCenter)
        volume_controls.addWidget(self.minimum_volume_icon, alignment=Qt.AlignmentFlag.AlignVCenter)
        volume_controls.addWidget(self.volume_slider, 1, alignment=Qt.AlignmentFlag.AlignVCenter)
        volume_controls.addWidget(self.maximum_volume_icon, alignment=Qt.AlignmentFlag.AlignVCenter)
        mute_controls = QHBoxLayout()
        mute_controls.setContentsMargins(0, 0, 0, 0)
        mute_controls.addStretch(1)
        mute_group = QHBoxLayout()
        mute_group.setContentsMargins(0, 0, 0, 0)
        mute_group.setSpacing(SPACE_2)
        mute_group.addWidget(self.mute_toggle)
        mute_group.addWidget(self.mute_label)
        mute_controls.addLayout(mute_group)
        audio_controls = QVBoxLayout()
        audio_controls.setContentsMargins(0, 0, 0, 0)
        audio_controls.setSpacing(SPACE_2)
        audio_controls.addWidget(self.volume_row)
        audio_controls.addLayout(mute_controls)
        progress_row = QHBoxLayout()
        progress_row.setContentsMargins(0, 0, 0, 0)
        progress_row.setSpacing(SPACE_2)
        progress_row.addWidget(self.progress_slider, 1)
        progress_row.addWidget(self.preview_time_label)
        layout = QVBoxLayout(self)
        # Keep the playback canvas aligned with the actual source-list widget,
        # which sits below the Source Clips group title and content inset.
        layout.setContentsMargins(SPACE_3, SPACE_3 + SPACE_2, SPACE_3, SPACE_3)
        layout.setSpacing(SPACE_2)
        layout.addWidget(self.preview_label)
        layout.addWidget(self.video, 1)
        layout.addLayout(progress_row)
        layout.addLayout(controls)
        layout.addLayout(audio_controls)
        layout.setStretch(1, 1)
        self.previous_button.clicked.connect(lambda: self.previous_requested.emit())
        self.play_pause_button.clicked.connect(self._toggle_playback)
        self.first_frame_button.clicked.connect(lambda: self.first_frame_requested.emit())
        self.last_frame_button.clicked.connect(lambda: self.last_frame_requested.emit())
        self.next_button.clicked.connect(lambda: self.next_requested.emit())
        self.mute_toggle.toggled.connect(self._mute_toggled)
        self.volume_slider.valueChanged.connect(self._volume_changed)
        self.progress_slider.valueChanged.connect(self._progress_changed)
        self._paths: tuple[Path, ...] = ()
        self._selected_index = -1
        self.player.playbackStateChanged.connect(self._playback_state_changed)
        self.player.mediaStatusChanged.connect(self._media_status_changed)
        self.player.positionChanged.connect(self._position_changed)
        self.player.durationChanged.connect(self._duration_changed)
        self.player.errorOccurred.connect(self._preview_error)

    @staticmethod
    def _control(glyph: str, label: str, object_name: str, *, muted: bool = False) -> QToolButton:
        """Create an icon-only preview control with native accessibility text."""

        button = QToolButton()
        button.setText(glyph)
        button.setObjectName(object_name)
        button.setAccessibleName(label)
        button.setToolTip(label)
        button.setFixedSize(32, 32)
        # The application-wide text-button padding would otherwise consume the
        # fixed 32 px icon hit area and clip the glyph.
        style = "QToolButton { padding: 0px; }"
        if muted:
            # Keep the same border, radius, background, and hit-area treatment
            # as the other preview controls; only soften the navigation glyphs.
            style = "QToolButton { padding: 0px; color: #b8bcc2; } QToolButton:hover { color: #d4d7dc; } QToolButton:pressed { color: #f1f3f4; }"
        button.setStyleSheet(style)
        glyph_font = button.font()
        glyph_font.setPointSizeF(max(1.0, glyph_font.pointSizeF() * 2))
        button.setFont(glyph_font)
        return button

    def _volume_icon(self, pixmap: QStyle.StandardPixmap, label: str, object_name: str) -> QLabel:
        """Create a fixed native volume indicator with accessible context."""

        icon = QLabel()
        icon.setObjectName(object_name)
        source = self.style().standardIcon(pixmap).pixmap(QSize(20, 20))
        tinted = QPixmap(QSize(24, 24))
        tinted.fill(Qt.GlobalColor.transparent)
        painter = QPainter(tinted)
        painter.drawPixmap(2, 2 + VOLUME_ICON_OPTICAL_OFFSET, source)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(tinted.rect(), QColor(VOLUME_ICON_COLOR))
        painter.end()
        icon.setPixmap(tinted)
        icon.setFixedSize(24, 24)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setAccessibleName(label)
        icon.setToolTip(label)
        return icon

    def set_source(self, path: Path | None) -> None:
        """Show only the selected editor source filename."""

        self.player.stop()
        self._reset_progress()
        self.preview_label.clear()
        self.preview_label.setVisible(False)
        self._set_actual_muted(True)
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
        self.mute_toggle.setEnabled(has_source)
        self.volume_slider.setEnabled(has_source)

    def set_audio_preferences(self, muted: bool, volume: int) -> None:
        """Apply persisted non-safety audio preferences without saving them."""

        self._apply_audio_preferences(muted, volume)

    def _apply_audio_preferences(self, muted: bool, volume: int) -> None:
        self._preferred_muted = muted
        self.audio.setVolume(max(0, min(100, volume)) / 100)
        self._set_actual_muted(muted)
        volume_blocker = QSignalBlocker(self.volume_slider)
        self.volume_slider.setValue(max(0, min(100, volume)))
        del volume_blocker

    def _set_actual_muted(self, muted: bool) -> None:
        self.audio.setMuted(muted)
        mute_blocker = QSignalBlocker(self.mute_toggle)
        self.mute_toggle.setChecked(muted)
        del mute_blocker

    @Slot(bool)
    def _mute_toggled(self, muted: bool) -> None:
        self._preferred_muted = muted
        self.audio.setMuted(muted)
        self.audio_preferences_changed.emit(self._preferred_muted, self.volume_slider.value())

    @Slot(int)
    def _volume_changed(self, volume: int) -> None:
        self.audio.setVolume(volume / 100)
        self.audio_preferences_changed.emit(self._preferred_muted, volume)

    def _reset_progress(self) -> None:
        """Clear timeline state while a new native source loads asynchronously."""

        progress_blocker = QSignalBlocker(self.progress_slider)
        self.progress_slider.setRange(0, 0)
        self.progress_slider.setValue(0)
        del progress_blocker
        self.progress_slider.setEnabled(False)
        self._duration_ms = 0
        self.preview_time_label.setText("0:00 / 0:00")

    @staticmethod
    def _format_time(milliseconds: int) -> str:
        """Format native player milliseconds as a compact media timestamp."""

        total_seconds = max(0, milliseconds) // 1000
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"

    def _update_time_label(self, position: int, duration: int) -> None:
        """Keep the accessible time readout synchronized with the timeline."""

        self.preview_time_label.setText(f"{self._format_time(position)} / {self._format_time(duration)}")

    @Slot(int)
    def _position_changed(self, position: int) -> None:
        """Reflect native playback progress without feeding it back as a seek."""

        progress_blocker = QSignalBlocker(self.progress_slider)
        self.progress_slider.setValue(max(0, position))
        del progress_blocker
        self._update_time_label(position, self._duration_ms)

    @Slot(int)
    def _duration_changed(self, duration: int) -> None:
        """Size and enable the seeking control once media duration is known."""

        duration = max(0, duration)
        self._duration_ms = duration
        progress_blocker = QSignalBlocker(self.progress_slider)
        self.progress_slider.setRange(0, duration)
        self.progress_slider.setValue(min(max(0, self.player.position()), duration))
        del progress_blocker
        self.progress_slider.setEnabled(duration > 0 and bool(self._paths) and 0 <= self._selected_index < len(self._paths))
        self._update_time_label(self.player.position(), self._duration_ms)

    @Slot(int)
    def _progress_changed(self, position: int) -> None:
        """Seek the selected native source when the user moves the timeline."""

        if self.progress_slider.isEnabled():
            self.player.setPosition(position)

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
    def pause_for_processing(self) -> None:
        """Pause preview playback when authoritative processing begins."""

        self.player.pause()

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
        action = "Pause preview" if playing else "Play preview"
        self.play_pause_button.setText("Ⅱ" if playing else "▶")
        self.play_pause_button.setAccessibleName(action)
        self.play_pause_button.setToolTip(action)

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
        self.preview_label.setText(message)
        self.preview_label.setVisible(True)
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
    audio_preferences_changed = Signal(bool, int)
