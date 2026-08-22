"""Session-only, typed message presentation for the native GUI."""

# PySide6 exposes Qt types dynamically, which Pylint cannot introspect.
# pylint: disable=no-name-in-module

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtWidgets import QPlainTextEdit, QTabWidget, QVBoxLayout, QWidget


@dataclass(frozen=True)
class MessageEvent:
    """One concise presentation event delivered on the Qt thread."""

    text: str
    job_id: str | None = None


class MessageHistory(QObject):
    """Own non-persistent message history for one application run."""

    changed = Signal()

    def __init__(self, *, clock: Callable[[], datetime] | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._clock = clock or datetime.now
        self._global: deque[str] = deque()
        self._jobs: defaultdict[str, deque[str]] = defaultdict(deque)

    def append(self, event: MessageEvent) -> None:
        """Append one typed event with a local timestamp and notify the view."""

        line = f"[{self._clock().strftime('%Y-%m-%d %H:%M:%S')}] {event.text}"
        (self._jobs[event.job_id] if event.job_id is not None else self._global).append(line)
        self.changed.emit()

    def global_lines(self) -> tuple[str, ...]:
        """Return all current global lines in display order."""
        return tuple(self._global)

    def job_lines(self, job_id: str | None) -> tuple[str, ...]:
        """Return all current selected-job lines in display order."""
        return tuple(self._jobs[job_id]) if job_id is not None else ()


class MessageWidget(QWidget):
    """Integrated two-tab read-only message history."""

    def __init__(self, history: MessageHistory | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.history = history or MessageHistory(parent=self)
        self._selected_job_id: str | None = None
        self.tabs = QTabWidget()
        self.tabs.setObjectName("messageTabs")
        self.global_messages = self._log("globalMessages")
        self.job_messages = self._log("jobMessages")
        self.tabs.addTab(self.global_messages, "Global Messages")
        self.tabs.addTab(self.job_messages, "Job Messages")
        self.setMinimumHeight(self.global_messages.minimumHeight() + self.tabs.tabBar().sizeHint().height())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tabs)
        self.history.changed.connect(self._render)
        self._render()

    @staticmethod
    def _log(name: str) -> QPlainTextEdit:
        log = QPlainTextEdit()
        log.setObjectName(name)
        log.setReadOnly(True)
        log.setUndoRedoEnabled(False)
        log.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        log.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        log.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        log.setMinimumHeight(log.fontMetrics().lineSpacing() * 5 + 12)
        return log

    @Slot(str)
    def select_job(self, job_id: str | None, *, activate: bool = True) -> None:
        """Select a job and activate its message tab."""
        self._selected_job_id = job_id
        if job_id is not None and activate:
            self.tabs.setCurrentWidget(self.job_messages)
        self._render()

    def append(self, event: MessageEvent) -> None:
        """Append one typed event to the session history."""
        self.history.append(event)

    @Slot()
    def _render(self) -> None:
        """Render session history; no backend work occurs here."""
        self.global_messages.setPlainText("\n".join(self.history.global_lines()))
        lines = self.history.job_lines(self._selected_job_id)
        self.job_messages.setPlainText("\n".join(lines) if lines else "No job is selected." if self._selected_job_id is None else "")
        for log in (self.global_messages, self.job_messages):
            log.verticalScrollBar().setValue(log.verticalScrollBar().maximum())
