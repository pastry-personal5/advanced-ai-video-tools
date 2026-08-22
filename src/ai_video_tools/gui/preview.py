"""Presentation-only source preview boundary for the job editor."""

# PySide6 exposes Qt types dynamically, which Pylint cannot introspect.
# pylint: disable=no-name-in-module

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QSizePolicy, QVBoxLayout, QWidget


class SourcePreviewPane(QFrame):
    """Display the selected local source identity without affecting processing."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sourcePreviewPane")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.setMinimumWidth(240)
        self.title = QLabel("Source Preview")
        self.title.setObjectName("sourcePreviewTitle")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.source = QLabel("Select a source clip to preview it.")
        self.source.setObjectName("sourcePreviewSource")
        self.source.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.source.setWordWrap(True)
        self.disclaimer = QLabel("Convenience preview; not color-accurate or authoritative for processing.")
        self.disclaimer.setObjectName("sourcePreviewDisclaimer")
        self.disclaimer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.disclaimer.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addWidget(self.title)
        layout.addStretch(1)
        layout.addWidget(self.source)
        layout.addStretch(1)
        layout.addWidget(self.disclaimer)

    def set_source(self, path: Path | None) -> None:
        """Show only the selected editor source filename."""

        self.source.setText(path.name if path is not None else "Select a source clip to preview it.")

    def heightForWidth(self, width: int) -> int:  # pylint: disable=invalid-name
        """Return the approved 3:4 preview geometry for a given width."""

        return max(1, width * 4 // 3)

    def hasHeightForWidth(self) -> bool:  # pylint: disable=invalid-name
        """Declare the width-driven preview geometry to Qt layouts."""

        return True
