"""Presentation-only source preview boundary for the job editor."""

# PySide6 exposes Qt types dynamically, which Pylint cannot introspect. The
# tightly coupled source, fullscreen, and queue presentation widgets remain in
# one explicit preview boundary to preserve their shared player lifecycle.
# pylint: disable=no-name-in-module,too-many-lines,unnecessary-lambda

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPoint, QSignalBlocker, QSize, QThread, QUrl, Qt, Signal, Slot
from PySide6.QtGui import QColor, QFont, QImage, QImageReader, QKeyEvent, QPainter, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QApplication, QCheckBox, QDialog, QGroupBox, QHBoxLayout, QLabel, QSlider, QSizePolicy, QStyle, QTabWidget, QToolButton, QVBoxLayout, QWidget

from advanced_ai_video_tools.gui.theme import SPACE_2, SPACE_3
from advanced_ai_video_tools.gui.clip_resolution import DimensionProbeController

VOLUME_ICON_COLOR = "#b8bcc2"
VOLUME_ICON_OPTICAL_OFFSET = 0
FULLSCREEN_HELP_MARGIN = 24
PREVIEW_PANE_MINIMUM_WIDTH = 520
VOLUME_SLIDER_MINIMUM_WIDTH = 48


class FullscreenCommand(Enum):
    """Actions available from the fullscreen preview keyboard."""

    FIRST_FRAME = "first_frame"
    LAST_FRAME = "last_frame"
    PREVIOUS_CLIP = "previous_clip"
    NEXT_CLIP = "next_clip"
    PLAY_PAUSE = "play_pause"
    PLAY_PREVIOUS_CLIP = "play_previous_clip"
    PLAY_NEXT_CLIP = "play_next_clip"
    CLOSE = "close"
    TOGGLE_HELP = "toggle_help"


@dataclass(frozen=True)
class FullscreenShortcut:
    """One documented action and all equivalent Qt key bindings."""

    command: FullscreenCommand
    display: str
    description: str
    bindings: tuple[tuple[Qt.Key, Qt.KeyboardModifier], ...]


FULLSCREEN_SHORTCUTS = (
    FullscreenShortcut(FullscreenCommand.FIRST_FRAME, "0", "Go to first frame", ((Qt.Key.Key_0, Qt.KeyboardModifier.NoModifier),)),
    FullscreenShortcut(FullscreenCommand.LAST_FRAME, "9", "Go to last frame", ((Qt.Key.Key_9, Qt.KeyboardModifier.NoModifier),)),
    FullscreenShortcut(FullscreenCommand.PREVIOUS_CLIP, "j", "Previous clip (autoplay)", ((Qt.Key.Key_J, Qt.KeyboardModifier.NoModifier),)),
    FullscreenShortcut(FullscreenCommand.NEXT_CLIP, "l", "Next clip (autoplay)", ((Qt.Key.Key_L, Qt.KeyboardModifier.NoModifier),)),
    FullscreenShortcut(FullscreenCommand.PLAY_PAUSE, "Space / k", "Play or pause", ((Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier), (Qt.Key.Key_K, Qt.KeyboardModifier.NoModifier))),
    FullscreenShortcut(FullscreenCommand.PLAY_PREVIOUS_CLIP, "Shift-P", "Play previous clip from start", ((Qt.Key.Key_P, Qt.KeyboardModifier.ShiftModifier),)),
    FullscreenShortcut(FullscreenCommand.PLAY_NEXT_CLIP, "Shift-N", "Play next clip from start", ((Qt.Key.Key_N, Qt.KeyboardModifier.ShiftModifier),)),
    FullscreenShortcut(FullscreenCommand.CLOSE, "Esc", "Close help or fullscreen", ((Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier),)),
    FullscreenShortcut(
        FullscreenCommand.TOGGLE_HELP,
        "? / Shift+/",
        "Show or hide shortcut help",
        (
            (Qt.Key.Key_Question, Qt.KeyboardModifier.NoModifier),
            (Qt.Key.Key_Question, Qt.KeyboardModifier.ShiftModifier),
            (Qt.Key.Key_Slash, Qt.KeyboardModifier.ShiftModifier),
        ),
    ),
)

_SHORTCUT_LOOKUP = {binding: shortcut.command for shortcut in FULLSCREEN_SHORTCUTS for binding in shortcut.bindings}
_SHORTCUT_MODIFIERS = Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier
_MODIFIER_KEYS = frozenset({Qt.Key.Key_Shift, Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_Meta, Qt.Key.Key_AltGr})
SHORTCUT_HELP = "\n".join(f"{shortcut.display:<12} {shortcut.description}" for shortcut in FULLSCREEN_SHORTCUTS)


def resolve_fullscreen_shortcut(key: Qt.Key, modifiers: Qt.KeyboardModifier, text: str = "") -> FullscreenCommand | None:
    """Resolve one normalized Qt key event to its fullscreen command."""

    normalized_modifiers = modifiers & _SHORTCUT_MODIFIERS
    if text == "?" and not normalized_modifiers & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier):
        return FullscreenCommand.TOGGLE_HELP
    return _SHORTCUT_LOOKUP.get((key, normalized_modifiers))


class FullscreenShortcutHelpDialog(QDialog):
    """Non-activating translucent shortcut reference above native video."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("fullscreenPreviewHelpPanel")
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAccessibleName("Fullscreen preview keyboard shortcuts")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        title = QLabel("Preview Keyboard Shortcuts")
        title.setObjectName("fullscreenPreviewHelpTitle")
        layout.addWidget(title)
        help_text = QLabel(SHORTCUT_HELP)
        help_text.setObjectName("fullscreenPreviewHelpText")
        layout.addWidget(help_text)
        self.hide()


class FullscreenPreviewDialog(QDialog):
    """Fullscreen presentation surface using the pane's existing video widget."""

    def __init__(self, pane: "SourcePreviewPane") -> None:
        # Declarative fullscreen-surface construction is intentionally kept together.
        # pylint: disable=too-many-statements
        super().__init__(pane)
        self._pane = pane
        self._application = QApplication.instance()
        self.setObjectName("fullscreenPreviewDialog")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setStyleSheet("QDialog#fullscreenPreviewDialog { background: #101113; }")
        # Native macOS video reparenting can synchronously deliver resizeEvent.
        # Build every object used by that handler before changing video parent.
        self.help_panel = FullscreenShortcutHelpDialog(self)

        self.video = pane.video
        self.video.setObjectName("fullscreenPreviewVideo")
        pane.layout().removeWidget(self.video)
        self.video.setParent(self)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.addWidget(self.video, 1)
        self._command_handlers: dict[FullscreenCommand, Callable[[], None]] = {
            FullscreenCommand.FIRST_FRAME: lambda: self._pane.go_to_first_frame(),
            FullscreenCommand.LAST_FRAME: lambda: self._pane.go_to_last_frame(),
            FullscreenCommand.PREVIOUS_CLIP: lambda: self._navigate_clip(-1, play_from_start=False),
            FullscreenCommand.NEXT_CLIP: lambda: self._navigate_clip(1, play_from_start=False),
            FullscreenCommand.PLAY_PAUSE: lambda: self._pane._toggle_playback(),  # pylint: disable=protected-access
            FullscreenCommand.PLAY_PREVIOUS_CLIP: lambda: self._navigate_clip(-1, play_from_start=True),
            FullscreenCommand.PLAY_NEXT_CLIP: lambda: self._navigate_clip(1, play_from_start=True),
            FullscreenCommand.CLOSE: self._close_help_or_fullscreen,
            FullscreenCommand.TOGGLE_HELP: self.toggle_help,
        }
        if self._application is not None:
            self._application.installEventFilter(self)

    def toggle_help(self) -> None:
        """Toggle the keyboard-help panel without changing playback."""

        if self.help_panel.isVisible():
            self.help_panel.hide()
            return
        self.help_panel.adjustSize()
        self._position_help_panel()
        self.help_panel.show()
        self.help_panel.raise_()

    def _position_help_panel(self) -> None:
        """Place help at the right edge and vertical center of fullscreen."""

        self.help_panel.move(self.mapToGlobal(self._help_panel_local_position()))

    def _help_panel_local_position(self) -> QPoint:
        """Calculate the help anchor in fullscreen-local coordinates."""

        x_position = max(0, self.width() - self.help_panel.width() - FULLSCREEN_HELP_MARGIN)
        y_position = max(0, (self.height() - self.help_panel.height()) // 2)
        return QPoint(x_position, y_position)

    def resizeEvent(self, event: object) -> None:  # pylint: disable=invalid-name
        """Keep overlays anchored as the fullscreen surface changes size."""

        super().resizeEvent(event)  # type: ignore[arg-type]
        self.help_panel.adjustSize()
        self._position_help_panel()

    def _event_targets_fullscreen(self, watched: object) -> bool:
        """Return whether an application key event belongs to this dialog."""

        if watched in (self, self.help_panel):
            return True
        if isinstance(watched, QWidget) and (self.isAncestorOf(watched) or self.help_panel.isAncestorOf(watched)):
            return True
        return QApplication.activeWindow() is self

    def _execute_command(self, command: FullscreenCommand) -> None:
        """Execute one resolved fullscreen command."""

        self._command_handlers[command]()

    def _close_help_or_fullscreen(self) -> None:
        """Close help first, then the fullscreen dialog."""

        if self.help_panel.isVisible():
            self.help_panel.hide()
        else:
            self.close()

    def _navigate_clip(self, offset: int, *, play_from_start: bool) -> None:
        """Navigate without wrapping and optionally enforce playback from zero."""

        destination = self._pane._selected_index + offset  # pylint: disable=protected-access
        if destination < 0 or destination >= len(self._pane._paths):  # pylint: disable=protected-access
            return
        signal = self._pane.previous_requested if offset < 0 else self._pane.next_requested
        signal.emit()
        if play_from_start:
            self._pane.player.setPosition(0)
            self._pane._request_playback(True)  # pylint: disable=protected-access

    def _dispatch_key_press(self, event: QKeyEvent) -> None:
        """Resolve and dispatch one fullscreen key press exactly once."""

        if event.isAutoRepeat() or event.key() in _MODIFIER_KEYS:
            return
        command = resolve_fullscreen_shortcut(event.key(), event.modifiers(), event.text())
        if command is not None:
            self._execute_command(command)

    def eventFilter(self, watched: object, event: object) -> bool:  # pylint: disable=invalid-name
        """Route fullscreen keyboard input independently of child focus."""

        if self.isVisible() and self._event_targets_fullscreen(watched):
            if event.type() == QEvent.Type.ShortcutOverride:  # type: ignore[attr-defined]
                event.accept()  # type: ignore[attr-defined]
                return True
            if event.type() == QEvent.Type.KeyPress and isinstance(event, QKeyEvent):  # type: ignore[attr-defined]
                self._dispatch_key_press(event)
                return True
            if event.type() == QEvent.Type.KeyRelease and isinstance(event, QKeyEvent):  # type: ignore[attr-defined]
                return True
        return super().eventFilter(watched, event)  # type: ignore[arg-type]

    def keyPressEvent(self, event: QKeyEvent) -> None:  # pylint: disable=invalid-name
        """Dispatch approved fullscreen preview keyboard shortcuts."""

        self._dispatch_key_press(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:  # pylint: disable=invalid-name
        """Consume key releases so focused controls cannot activate twice."""

        event.accept()

    def closeEvent(self, event: object) -> None:  # pylint: disable=invalid-name
        """Return the shared video widget to the embedded preview pane."""

        self.help_panel.close()
        self._layout.removeWidget(self.video)
        self.video.setParent(self._pane)
        self._pane.layout().insertWidget(1, self.video, 1)
        self._pane.player.setVideoOutput(self.video)
        self.video.setObjectName("sourcePreviewVideo")
        if self._application is not None:
            self._application.removeEventFilter(self)
        self._pane._fullscreen = None  # pylint: disable=protected-access
        super().closeEvent(event)  # type: ignore[arg-type]


class SourcePreviewPane(QGroupBox):
    """Display the selected local source identity without affecting processing."""

    def __init__(self, parent: QWidget | None = None, *, muted: bool = True, volume: int = 100, ffprobe_override: Path | None = None) -> None:
        # Declarative widget construction is intentionally kept together.
        # pylint: disable=too-many-statements
        super().__init__("Preview", parent)
        self.setObjectName("sourcePreviewPane")
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.setMinimumWidth(PREVIEW_PANE_MINIMUM_WIDTH)
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
        self.fullscreen_button = self._control("⛶", "Start fullscreen preview", "previewFullscreenButton")
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
        self.volume_label.setFixedWidth(self.volume_label.sizeHint().width())
        self.dimension_label = QLabel()
        self.dimension_label.setObjectName("previewDimensionInfo")
        self.dimension_label.setAccessibleName("Focused clip dimensions")
        self.dimension_label.setToolTip("Focused clip coded dimensions")
        self.dimension_label.setFixedHeight(24)
        self.dimension_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
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
        navigation_controls.addWidget(self.fullscreen_button)
        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.addLayout(playback_controls)
        controls.addStretch(1)
        controls.addLayout(navigation_controls)
        self._buttons = (self.play_pause_button, self.first_frame_button, self.last_frame_button, self.previous_button, self.next_button)
        self.dimension_info_and_volume_control_row = QWidget()
        self.dimension_info_and_volume_control_row.setObjectName("previewDimensionInfoAndVolumeControlRow")
        self.dimension_info_and_volume_control_row.setFixedHeight(24)
        self.dimension_info_and_volume_control_row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        volume_controls = QHBoxLayout(self.dimension_info_and_volume_control_row)
        volume_controls.setContentsMargins(0, 0, 0, 0)
        volume_controls.setSpacing(SPACE_2)
        volume_controls.addWidget(self.dimension_label, alignment=Qt.AlignmentFlag.AlignVCenter)
        volume_controls.addWidget(self.volume_label, alignment=Qt.AlignmentFlag.AlignVCenter)
        volume_controls.addWidget(self.minimum_volume_icon, alignment=Qt.AlignmentFlag.AlignVCenter)
        self.volume_slider.setMinimumWidth(VOLUME_SLIDER_MINIMUM_WIDTH)
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
        audio_controls.addWidget(self.dimension_info_and_volume_control_row)
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
        self.fullscreen_button.clicked.connect(self.open_fullscreen)
        self.mute_toggle.toggled.connect(self._mute_toggled)
        self.volume_slider.valueChanged.connect(self._volume_changed)
        self.progress_slider.valueChanged.connect(self._progress_changed)
        self._paths: tuple[Path, ...] = ()
        self._selected_index = -1
        self._dimension_probe = DimensionProbeController(ffprobe_override, self)
        self._dimension_probe.status_changed.connect(self._dimension_status_changed)
        self._dimension_probe.dimensions_changed.connect(self._dimension_result_changed)
        self._fullscreen: FullscreenPreviewDialog | None = None
        self._playback_requested = False
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

        self._playback_requested = False
        self._update_playback_controls(False)
        self.player.stop()
        self._reset_progress()
        self.preview_label.clear()
        self.preview_label.setVisible(False)
        self._set_actual_muted(True)
        if path is None:
            self.player.setSource(QUrl())
        else:
            self.player.setSource(QUrl.fromLocalFile(str(path)))
            self._request_playback(True)

    def set_sources(self, paths: tuple[Path, ...], selected_index: int) -> None:
        """Update navigation state from the editor's ordered source list."""

        self._paths = paths
        self._selected_index = selected_index
        self._dimension_probe.set_sources(paths, selected_index)
        self.set_source(paths[selected_index] if 0 <= selected_index < len(paths) else None)
        has_source = bool(paths) and 0 <= selected_index < len(paths)
        self.play_pause_button.setEnabled(has_source)
        self.first_frame_button.setEnabled(has_source)
        self.last_frame_button.setEnabled(has_source)
        self.previous_button.setEnabled(has_source and selected_index > 0)
        self.next_button.setEnabled(has_source and selected_index < len(paths) - 1)
        self.mute_toggle.setEnabled(has_source)
        self.volume_slider.setEnabled(has_source)
        self.fullscreen_button.setEnabled(has_source)

    def set_ffprobe_override(self, path: Path | None) -> None:
        """Apply a future FFprobe setting without starting a new probe."""

        self._dimension_probe.reconfigure(path)

    @Slot(str)
    def _dimension_status_changed(self, status: str) -> None:
        """Render non-success probe states without owning probe logic."""

        if status:
            self.dimension_label.setText(status)

    @Slot(object)
    def _dimension_result_changed(self, dimensions: object) -> None:
        """Render a successful result or clear the no-selection state."""

        if dimensions is None:
            self.dimension_label.clear()
        elif isinstance(dimensions, tuple) and len(dimensions) == 2:
            self.dimension_label.setText(f"{dimensions[0]}×{dimensions[1]}")

    @Slot()
    def open_fullscreen(self) -> None:
        """Open the selected source in a focused fullscreen presentation."""

        if not self._paths or not 0 <= self._selected_index < len(self._paths):
            return
        if self._fullscreen is not None:
            self._fullscreen.raise_()
            self._fullscreen.activateWindow()
            return
        self._fullscreen = FullscreenPreviewDialog(self)
        self._fullscreen.showFullScreen()
        self._fullscreen.activateWindow()
        self._fullscreen.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

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

    @Slot()
    def _toggle_playback(self) -> None:
        self._request_playback(not self._playback_requested)

    def _request_playback(self, playing: bool) -> None:
        """Apply playback intent immediately without waiting for Qt state."""

        self._playback_requested = playing
        self._update_playback_controls(playing)
        if playing:
            self.player.play()
        else:
            self.player.pause()

    @Slot()
    def pause_for_processing(self) -> None:
        """Pause preview playback when authoritative processing begins."""

        self._request_playback(False)
        if self._fullscreen is not None:
            self._fullscreen.close()

    @Slot()
    def go_to_first_frame(self) -> None:
        """Pause and seek the active source to its first frame."""

        self._request_playback(False)
        self.player.setPosition(0)

    @Slot()
    def go_to_last_frame(self) -> None:
        """Pause and seek the active source to its last available frame."""

        self._request_playback(False)
        self.player.setPosition(max(0, self.player.duration() - 1))

    @Slot(QMediaPlayer.PlaybackState)
    def _playback_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        self._update_playback_controls(state == QMediaPlayer.PlaybackState.PlayingState)

    def _update_playback_controls(self, playing: bool) -> None:
        """Synchronize embedded play-control feedback."""

        action = "Pause preview" if playing else "Play preview"
        self.play_pause_button.setText("Ⅱ" if playing else "▶")
        self.play_pause_button.setAccessibleName(action)
        self.play_pause_button.setToolTip(action)

    @Slot(QMediaPlayer.MediaStatus)
    def _media_status_changed(self, status: QMediaPlayer.MediaStatus) -> None:
        """Keep the final decoded frame visible when native playback ends."""

        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self._request_playback(False)
            if self.player.duration() > 0:
                self.player.setPosition(max(0, self.player.duration() - 1))

    @Slot(QMediaPlayer.Error, str)
    def _preview_error(self, _error: QMediaPlayer.Error, _error_string: str) -> None:
        self._request_playback(False)
        message = "Preview unavailable; preflight can still inspect this clip."
        self.preview_label.setText(message)
        self.preview_label.setVisible(True)
        self.preview_error.emit(message)

    def shutdown(self) -> None:
        """Stop playback and release native preview outputs during window close."""

        self._request_playback(False)
        if self._fullscreen is not None:
            self._fullscreen.close()
        self.player.stop()
        self.player.setVideoOutput(None)
        self.player.setAudioOutput(None)
        self._dimension_probe.shutdown()

    previous_requested = Signal()
    play_pause_requested = Signal()
    first_frame_requested = Signal()
    last_frame_requested = Signal()
    next_requested = Signal()
    fullscreen_requested = Signal()
    preview_error = Signal(str)
    audio_preferences_changed = Signal(bool, int)


class SampledFrameLoader(QObject):
    """Decode one sampled original or upscaled PNG away from the GUI thread."""

    frame_loaded = Signal(object, str, int)

    @Slot(object, str, int, QSize)
    def load(self, path: object, kind: str, generation: int, target_size: QSize) -> None:
        """Read one local image and return a thread-safe QImage."""

        image = QImage()
        if isinstance(path, Path):
            reader = QImageReader(str(path))
            source_size = reader.size()
            if source_size.isValid() and target_size.isValid():
                reader.setScaledSize(source_size.scaled(target_size, Qt.AspectRatioMode.KeepAspectRatio))
            image = reader.read()
        self.frame_loaded.emit(image, kind, generation)


class QueuePreviewLastFrameWaitDialog(QDialog):
    """Non-activating wait surface kept above the native queue video widget."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("queuePreviewLastFrameWait")
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAccessibleName("Loading final video last frame")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 18)
        self.indicator = QLabel("⌛\nLoading last frame…")
        self.indicator.setObjectName("queuePreviewLastFrameWaitText")
        self.indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.indicator)
        self.hide()

    def set_message(self, message: str) -> None:
        """Update the active first- or last-frame seek message."""

        self.indicator.setText(f"⌛\n{message}")


class QueuePreviewPane(QGroupBox):
    """Show live sampled upscale frames or a looping published final video."""

    @staticmethod
    def _frame_label(object_name: str, accessible_name: str) -> QLabel:
        """Create one tab-local image surface for sampled queue frames."""

        label = QLabel()
        label.setObjectName(object_name)
        label.setAccessibleName(accessible_name)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setScaledContents(False)
        return label

    @staticmethod
    def _frame_tab(label: QLabel) -> QWidget:
        """Place one sampled-frame surface in a zero-margin tab page."""

        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(label, 1)
        return tab

    def __init__(self, parent: QWidget | None = None, *, muted: bool = True, volume: int = 100) -> None:
        # Declarative widget construction is intentionally kept together.
        # pylint: disable=too-many-statements
        super().__init__("Queue Preview", parent)
        self.setObjectName("queuePreviewPane")
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.setMinimumWidth(PREVIEW_PANE_MINIMUM_WIDTH)
        self.video = QVideoWidget()
        self.video.setObjectName("queuePreviewVideo")
        self.video.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.video.setMinimumSize(0, 0)
        self.video.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setMuted(bool(muted))
        self.audio.setVolume(max(0, min(100, volume)) / 100)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video)
        self.original_frame_preview = self._frame_label("queuePreviewOriginalFrame", "Latest original frame")
        self.upscaled_frame_preview = self._frame_label("queuePreviewUpscaledFrame", "Latest upscaled frame")
        self.progress_slider = QSlider(Qt.Orientation.Horizontal)
        self.progress_slider.setObjectName("queuePreviewProgressSlider")
        self.progress_slider.setAccessibleName("Final video preview progress")
        self.progress_slider.setToolTip("Seek final video preview")
        self.progress_slider.setRange(0, 0)
        self.progress_slider.setEnabled(False)
        self.progress_slider.setTracking(True)
        self.progress_slider.setFixedHeight(24)
        self.time_label = QLabel("0:00 / 0:00")
        self.time_label.setObjectName("queuePreviewTimeLabel")
        self.time_label.setAccessibleName("Final video preview time")
        self.time_label.setMinimumWidth(84)
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.play_pause_button = SourcePreviewPane._control("▶", "Play final video preview", "queuePreviewPlayPauseButton")  # pylint: disable=protected-access
        self.first_frame_button = SourcePreviewPane._control("⏮", "Go to first frame", "queuePreviewFirstFrameButton")  # pylint: disable=protected-access
        self.last_frame_button = SourcePreviewPane._control("⏭", "Go to last frame", "queuePreviewLastFrameButton")  # pylint: disable=protected-access
        progress_row = QHBoxLayout()
        progress_row.setContentsMargins(0, 0, 0, 0)
        progress_row.setSpacing(SPACE_2)
        progress_row.addWidget(self.progress_slider, 1)
        progress_row.addWidget(self.time_label)
        self.controls = QWidget()
        controls = QHBoxLayout(self.controls)
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(SPACE_2)
        controls.addWidget(self.play_pause_button)
        controls.addWidget(self.first_frame_button)
        controls.addWidget(self.last_frame_button)
        controls.addStretch(1)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("queuePreviewTabs")
        self.tabs.setAccessibleName("Queue preview type")
        self.original_tab = self._frame_tab(self.original_frame_preview)
        self.upscaled_tab = self._frame_tab(self.upscaled_frame_preview)
        self.final_video_tab = QWidget()
        final_layout = QVBoxLayout(self.final_video_tab)
        final_layout.setContentsMargins(0, 0, 0, 0)
        final_layout.setSpacing(SPACE_2)
        final_layout.addWidget(self.video, 1)
        final_layout.addLayout(progress_row)
        final_layout.addWidget(self.controls)
        self.tabs.addTab(self.original_tab, "Original")
        self.tabs.addTab(self.upscaled_tab, "Upscaled")
        self.tabs.addTab(self.final_video_tab, "Final Video")
        self.last_frame_wait = QueuePreviewLastFrameWaitDialog(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACE_3, SPACE_3 + SPACE_2, SPACE_3, SPACE_3)
        layout.setSpacing(SPACE_2)
        layout.addWidget(self.tabs, 1)
        layout.setStretch(0, 1)
        self._path: Path | None = None
        self._sample_paths: dict[str, Path | None] = {"original": None, "upscaled": None}
        self._decoded_sample_paths: dict[str, Path | None] = {"original": None, "upscaled": None}
        self._mode = "empty"
        self._duration_ms = 0
        self._playback_requested = False
        self._pending_last_frame_position: int | None = None
        self._pending_first_frame = False
        self._hold_last_frame = False
        self._frame_generations: dict[str, int] = {"original": 0, "upscaled": 0}
        self._frame_loader_thread = QThread(self)
        self._frame_loader = SampledFrameLoader()
        self._frame_loader.moveToThread(self._frame_loader_thread)
        self.frame_load_requested.connect(self._frame_loader.load, Qt.ConnectionType.QueuedConnection)
        self._frame_loader.frame_loaded.connect(self._frame_loaded)
        self._frame_loader_thread.finished.connect(self._frame_loader.deleteLater)
        self._frame_loader_thread.start()
        self.player.setLoops(QMediaPlayer.Loops.Infinite)
        self._set_controls_enabled(False)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.play_pause_button.clicked.connect(self._toggle_playback)
        self.first_frame_button.clicked.connect(self.go_to_first_frame)
        self.last_frame_button.clicked.connect(self.go_to_last_frame)
        self.progress_slider.valueChanged.connect(self._progress_changed)
        self.player.playbackStateChanged.connect(self._playback_state_changed)
        self.player.mediaStatusChanged.connect(self._media_status_changed)
        self.player.positionChanged.connect(self._position_changed)
        self.player.durationChanged.connect(self._duration_changed)
        self.player.errorOccurred.connect(self._preview_error)

    def show_final_output(self, path: Path | None) -> None:
        """Autoplay and loop one completed local output."""

        if path is None:
            self.clear("Select a completed job to preview its final video.")
            return
        if not path.is_file():
            self.clear("The selected job's final output file is unavailable.")
            return
        if path == self._path and self._mode == "video":
            self._request_playback(True)
            return
        self._clear_sample_frames()
        self._mode = "video"
        self._hold_last_frame = False
        self._hide_last_frame_wait()
        self._set_final_controls_visible(True)
        self.tabs.setCurrentWidget(self.final_video_tab)
        self._request_playback(False)
        self.player.stop()
        self._reset_progress()
        self._path = path
        self.player.setSource(QUrl.fromLocalFile(str(path)))
        self._set_controls_enabled(True)
        self._request_playback(True)

    def show_sampled_frames(self, original_path: Path | None, upscaled_path: Path | None) -> None:
        """Store the latest paired live samples and refresh the selected frame tab."""

        if self._mode != "frame":
            self._request_playback(False)
            self.player.stop()
            self.player.setSource(QUrl())
            self._reset_progress()
        self._mode = "frame"
        self._hold_last_frame = False
        self._path = None
        self._set_final_controls_visible(False)
        self._set_controls_enabled(False)
        self._set_sample_path("original", original_path)
        self._set_sample_path("upscaled", upscaled_path)
        self._refresh_active_frame()

    def clear(self, _message: str) -> None:
        """Clear published-output playback without reserving panel text space."""

        self._request_playback(False)
        self._hide_last_frame_wait()
        self._hold_last_frame = False
        self.player.stop()
        self.player.setSource(QUrl())
        self._path = None
        self._clear_sample_frames()
        self._mode = "empty"
        self._reset_progress()
        self._set_controls_enabled(False)
        self._set_final_controls_visible(False)

    def set_audio_preferences(self, muted: bool, volume: int) -> None:
        """Mirror the existing non-safety preview audio preferences."""

        self.audio.setMuted(bool(muted))
        self.audio.setVolume(max(0, min(100, volume)) / 100)

    @property
    def has_live_samples(self) -> bool:
        """Return whether this surface retains either sampled running-job frame."""

        return self._mode == "frame" and any(self._sample_paths.values())

    def _set_final_controls_visible(self, visible: bool) -> None:
        """Keep video controls absent while Final Video has no completed media."""

        self.progress_slider.setVisible(visible)
        self.time_label.setVisible(visible)
        self.controls.setVisible(visible)

    def _set_controls_enabled(self, enabled: bool) -> None:
        for button in (self.play_pause_button, self.first_frame_button, self.last_frame_button):
            button.setEnabled(enabled)

    def _reset_progress(self) -> None:
        blocker = QSignalBlocker(self.progress_slider)
        self.progress_slider.setRange(0, 0)
        self.progress_slider.setValue(0)
        del blocker
        self.progress_slider.setEnabled(False)
        self._duration_ms = 0
        self.time_label.setText("0:00 / 0:00")

    @Slot()
    def _toggle_playback(self) -> None:
        self._hold_last_frame = False
        self._request_playback(not self._playback_requested)

    def _request_playback(self, playing: bool) -> None:
        self._playback_requested = playing
        self._update_playback_control(playing)
        if playing:
            self.player.play()
        else:
            self.player.pause()

    def _update_playback_control(self, playing: bool) -> None:
        action = "Pause final video preview" if playing else "Play final video preview"
        self.play_pause_button.setText("Ⅱ" if playing else "▶")
        self.play_pause_button.setAccessibleName(action)
        self.play_pause_button.setToolTip(action)

    @Slot()
    def go_to_first_frame(self) -> None:
        """Pause and seek the published output to its first frame."""

        if self.player.duration() <= 0:
            return
        self._hold_last_frame = False
        self._request_playback(False)
        self._pending_last_frame_position = 0
        self._pending_first_frame = True
        self.last_frame_wait.set_message("Loading first frame…")
        self._show_last_frame_wait()
        self.player.setPosition(0)

    @Slot()
    def go_to_last_frame(self) -> None:
        """Pause and seek the published output to its last available frame."""

        target = max(0, self.player.duration() - 1)
        if self.player.duration() <= 0:
            return
        self._request_playback(False)
        self._hold_last_frame = True
        self._pending_last_frame_position = target
        self._pending_first_frame = False
        self.last_frame_wait.set_message("Loading last frame…")
        self._show_last_frame_wait()
        self.player.setPosition(target)

    @Slot(int)
    def _position_changed(self, position: int) -> None:
        blocker = QSignalBlocker(self.progress_slider)
        self.progress_slider.setValue(max(0, position))
        del blocker
        self._update_time_label(position)
        if self._pending_last_frame_position is not None and ((self._pending_first_frame and position <= self._pending_last_frame_position) or (not self._pending_first_frame and position >= self._pending_last_frame_position)):
            self._hide_last_frame_wait()

    @Slot(int)
    def _duration_changed(self, duration: int) -> None:
        duration = max(0, duration)
        self._duration_ms = duration
        blocker = QSignalBlocker(self.progress_slider)
        self.progress_slider.setRange(0, duration)
        self.progress_slider.setValue(min(max(0, self.player.position()), duration))
        del blocker
        self.progress_slider.setEnabled(duration > 0 and self._path is not None)
        self._update_time_label(self.player.position())

    def _update_time_label(self, position: int) -> None:
        self.time_label.setText(f"{SourcePreviewPane._format_time(position)} / {SourcePreviewPane._format_time(self._duration_ms)}")  # pylint: disable=protected-access

    def _show_last_frame_wait(self) -> None:
        """Center a native-surface-safe loading hint over Queue Preview."""

        self.last_frame_wait.adjustSize()
        center = self.video.mapToGlobal(self.video.rect().center())
        self.last_frame_wait.move(center - self.last_frame_wait.rect().center())
        self.last_frame_wait.show()
        self.last_frame_wait.raise_()

    def _hide_last_frame_wait(self) -> None:
        """Dismiss the wait hint once the requested final frame arrives."""

        self._pending_last_frame_position = None
        self._pending_first_frame = False
        self.last_frame_wait.hide()

    def _set_sample_path(self, kind: str, path: Path | None) -> None:
        """Replace one measured frame identity and invalidate stale decoded data."""

        if path == self._sample_paths[kind]:
            return
        self._sample_paths[kind] = path
        self._decoded_sample_paths[kind] = None
        self._frame_generations[kind] += 1
        if path is None:
            self._frame_label_for(kind).clear()

    def _clear_sample_frames(self) -> None:
        """Discard all temporary-frame identities and visible pixmaps."""

        for kind in ("original", "upscaled"):
            self._sample_paths[kind] = None
            self._decoded_sample_paths[kind] = None
            self._frame_generations[kind] += 1
            self._frame_label_for(kind).clear()

    def _frame_label_for(self, kind: str) -> QLabel:
        """Return the tab-local display surface for one approved sample kind."""

        return self.original_frame_preview if kind == "original" else self.upscaled_frame_preview

    def _active_frame_kind(self) -> str | None:
        """Return the selected live-frame tab, if any."""

        return ("original", "upscaled", None)[self.tabs.currentIndex()]

    @Slot(int)
    def _tab_changed(self, _index: int) -> None:
        """Load the latest retained frame only for the user-selected tab."""

        self._refresh_active_frame()

    def _refresh_active_frame(self) -> None:
        """Queue a decode for the active Original or Upscaled tab."""

        if self._mode != "frame":
            return
        kind = self._active_frame_kind()
        if kind is not None:
            self._request_frame_load(kind)

    def _request_frame_load(self, kind: str) -> None:
        """Queue one active-tab decode scaled to the visible frame canvas."""

        path = self._sample_paths[kind]
        if path is None:
            return
        self._frame_generations[kind] += 1
        self.frame_load_requested.emit(path, kind, self._frame_generations[kind], self._frame_label_for(kind).size())

    @Slot(object, str, int)
    def _frame_loaded(self, image: object, kind: str, generation: int) -> None:
        """Present only the latest successfully decoded active-tab frame."""

        if kind not in self._sample_paths or generation != self._frame_generations[kind] or self._mode != "frame" or not isinstance(image, QImage) or image.isNull():
            return
        self._frame_label_for(kind).setPixmap(QPixmap.fromImage(image))
        self._decoded_sample_paths[kind] = self._sample_paths[kind]

    def resizeEvent(self, event: object) -> None:  # pylint: disable=invalid-name
        """Reload the visible sampled frame at the new presentation size."""

        super().resizeEvent(event)  # type: ignore[arg-type]
        if self.has_live_samples:
            kind = self._active_frame_kind()
            if kind is not None:
                self._frame_generations[kind] += 1
                self._request_frame_load(kind)
        if self._pending_last_frame_position is not None:
            self._show_last_frame_wait()

    @Slot(int)
    def _progress_changed(self, position: int) -> None:
        if self.progress_slider.isEnabled():
            self._hold_last_frame = False
            self.player.setPosition(position)

    @Slot(QMediaPlayer.PlaybackState)
    def _playback_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        self._update_playback_control(state == QMediaPlayer.PlaybackState.PlayingState)

    @Slot(QMediaPlayer.MediaStatus)
    def _media_status_changed(self, status: QMediaPlayer.MediaStatus) -> None:
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            if self._hold_last_frame:
                self._hide_last_frame_wait()
                return
            self.player.setPosition(0)
            self._request_playback(True)

    @Slot(QMediaPlayer.Error, str)
    def _preview_error(self, _error: QMediaPlayer.Error, _error_string: str) -> None:
        self._hide_last_frame_wait()
        self._request_playback(False)

    def shutdown(self) -> None:
        """Stop playback and release native output-preview resources."""

        self._request_playback(False)
        self._hide_last_frame_wait()
        self.last_frame_wait.close()
        self.player.stop()
        self.player.setVideoOutput(None)
        self.player.setAudioOutput(None)
        self._frame_loader_thread.quit()
        self._frame_loader_thread.wait()

    frame_load_requested = Signal(object, str, int, QSize)
