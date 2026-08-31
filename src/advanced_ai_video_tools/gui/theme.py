"""Application-owned GUI theme configuration."""

# PySide6 exposes Qt types dynamically, which Pylint cannot introspect.
# pylint: disable=no-name-in-module

from __future__ import annotations

from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QPainter, QPalette, QPolygon
from PySide6.QtWidgets import QApplication, QProxyStyle, QSpinBox, QStyle

# Phase 1 visual-system metrics.  Keeping these values here prevents individual
# presentation surfaces from drifting into subtly different densities.
SPACE_1 = 4
SPACE_2 = 8
SPACE_3 = 16
SPACE_4 = 24
MAJOR_REGION_GAP = 32
CONTROL_HEIGHT = 32
CONTROL_RADIUS = 6
SURFACE_RADIUS = 8


class _ReadableSpinBoxStyle(QProxyStyle):
    """Draw larger, crisp stepper glyphs without changing the control geometry."""

    def drawPrimitive(self, element: QStyle.PrimitiveElement, option: object, painter: QPainter, widget: object = None) -> None:  # pylint: disable=invalid-name
        """Paint enlarged spinbox arrows and delegate every other primitive."""

        if element in (QStyle.PrimitiveElement.PE_IndicatorSpinUp, QStyle.PrimitiveElement.PE_IndicatorSpinDown) and isinstance(widget, QSpinBox):
            rect = option.rect  # type: ignore[attr-defined]
            center_x = rect.center().x()
            center_y = rect.center().y()
            half_width = 4
            half_height = 3
            if element == QStyle.PrimitiveElement.PE_IndicatorSpinUp:
                points = ((center_x, center_y - half_height), (center_x - half_width, center_y + half_height), (center_x + half_width, center_y + half_height))
            else:
                points = ((center_x - half_width, center_y - half_height), (center_x + half_width, center_y - half_height), (center_x, center_y + half_height))
            color_group = QPalette.ColorGroup.Active
            if not option.state & QStyle.StateFlag.State_Enabled:  # type: ignore[attr-defined]
                color_group = QPalette.ColorGroup.Disabled
            color = option.palette.color(color_group, QPalette.ColorRole.ButtonText)  # type: ignore[attr-defined]
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setOpacity(0.72)
            painter.setPen(color)
            painter.setBrush(color)
            painter.drawPolygon(QPolygon([QPoint(x, y) for x, y in points]))
            painter.restore()
            return
        super().drawPrimitive(element, option, painter, widget)


_DARK_STYLE_SHEET = f"""
QMainWindow, QDialog {{
    background: #202124;
}}

QWidget {{
    color: #f1f3f4;
}}

QLabel {{
    color: #e8eaed;
}}

QLabel#outputDirectoryExplanation,
QLabel#targetHeightExplanation,
QLabel#aiUpscalerExplanation {{
    color: #b8bcc2;
    font-size: 12pt;
}}

QLabel#modelLabel {{
    color: #d4d7dc;
    font-size: 13pt;
}}

QLabel#previewLabel {{
    color: #f1f3f4;
    font-size: 13pt;
    font-weight: 600;
    padding: 0 4px;
}}

QGroupBox {{
    background: #252629;
    border: 1px solid #45474b;
    border-radius: {SURFACE_RADIUS}px;
    font-weight: 600;
    margin-top: 12px;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    left: {SPACE_3}px;
    padding: 0 {SPACE_1}px;
    color: #f1f3f4;
    font-size: 13pt;
}}

QGroupBox#basicSettings {{
    background: #2a2b2e;
    border-color: #5a5d63;
    border-radius: 10px;
}}

QGroupBox#basicSettings::title {{
    font-size: 17pt;
    font-weight: 600;
}}

QGroupBox#outputDirectoryGroup,
QGroupBox#targetHeightGroup,
QGroupBox#aiUpscalerGroup {{
    background: #202124;
    border-color: #3c4043;
}}

QGroupBox#sourceClipListGroup,
QGroupBox#selectedJobDetails {{
    background: #252629;
    border-color: #50535a;
}}

QGroupBox#selectedJobDetails::title {{
    left: {SPACE_2}px;
    font-size: 10pt;
    font-weight: 600;
}}

QGroupBox#selectedJobDetails QLabel {{
    font-size: 10pt;
}}

QGroupBox#sourcePreviewPane,
QGroupBox#queuePreviewPane,
QGroupBox#queueActiveGroup,
QGroupBox#queueUpNextGroup,
QGroupBox#queueHistoryGroup {{
    background: #252629;
    border: 1px solid #50535a;
    border-radius: {SURFACE_RADIUS}px;
}}

QGroupBox#sourcePreviewPane::title,
QGroupBox#queuePreviewPane::title,
QGroupBox#queueActiveGroup::title,
QGroupBox#queueUpNextGroup::title,
QGroupBox#queueHistoryGroup::title {{
    subcontrol-origin: margin;
    left: {SPACE_3}px;
    padding: 0 {SPACE_1}px;
    color: #f1f3f4;
    font-size: 13pt;
    font-weight: 600;
}}

QVideoWidget#sourcePreviewVideo,
QVideoWidget#queuePreviewVideo,
QLabel#queuePreviewOriginalFrame,
QLabel#queuePreviewUpscaledFrame {{
    background: #17181a;
    border: 1px solid #3c4043;
    border-radius: {CONTROL_RADIUS}px;
}}

QVideoWidget#sourcePreviewVideo,
QVideoWidget#queuePreviewVideo,
QVideoWidget#fullscreenPreviewVideo {{
    background: #17181a;
}}

QDialog#fullscreenPreviewHelpPanel {{
    background: rgba(37, 38, 41, 128);
    border: none;
    border-radius: {SURFACE_RADIUS}px;
}}

QLabel#fullscreenPreviewHelpTitle {{
    color: #ffffff;
    font-size: 15pt;
    font-weight: 600;
}}

QLabel#fullscreenPreviewHelpText {{
    color: #ffffff;
    font-family: monospace;
}}

QDialog#queuePreviewLastFrameWait {{
    background: rgba(37, 38, 41, 224);
    border: 1px solid #5f6368;
    border-radius: {SURFACE_RADIUS}px;
}}

QLabel#queuePreviewLastFrameWaitText {{
    color: #d4d7dc;
    font-size: 13pt;
    font-weight: 600;
}}

QLineEdit,
QSpinBox,
QAbstractItemView,
QTextEdit,
QPlainTextEdit {{
    background: #17181a;
    border: 1px solid #5f6368;
    border-radius: {CONTROL_RADIUS}px;
    padding: 0 {SPACE_2}px;
    selection-background-color: #5f8dd3;
    selection-color: #ffffff;
}}

QLineEdit:focus,
QSpinBox:focus,
QAbstractItemView:focus,
QTextEdit:focus,
QPlainTextEdit:focus {{
    border-color: #8ab4f8;
}}

QLineEdit:disabled,
QSpinBox:disabled,
QAbstractItemView:disabled {{
    background: #1d1e20;
    border-color: #35363a;
    color: #8a8d91;
}}

QPushButton,
QToolButton {{
    min-height: {CONTROL_HEIGHT - 2}px;
    border: 1px solid #5f6368;
    border-radius: {CONTROL_RADIUS}px;
    background: #303134;
    color: #f1f3f4;
    padding: 0 {SPACE_3 - 2}px;
}}

QPushButton:hover,
QToolButton:hover {{
    background: #3c4043;
    border-color: #8ab4f8;
}}

QPushButton:pressed,
QToolButton:pressed {{
    background: #474a4f;
}}

QPushButton:disabled,
QToolButton:disabled {{
    background: #292a2d;
    border-color: #3c4043;
    color: #8a8d91;
}}

QPushButton#submitJobButton {{
    background: #8ab4f8;
    border-color: #a8c7fa;
    color: #202124;
    font-weight: 700;
}}

QPushButton#submitJobButton:hover {{
    background: #a8c7fa;
}}

QPushButton#submitJobButton:disabled {{
    background: #4f5967;
    border-color: #4f5967;
    color: #c7c9cc;
}}

QPushButton#moveJobUpButton,
QPushButton#moveJobDownButton {{
    min-height: 26px;
    max-height: 26px;
    font-size: 9pt;
    padding: 0 10px;
}}

QToolButton#chooseOutputButton,
QToolButton#sourceClipFullscreenButton,
QToolButton#sourceClipRemoveButton,
QToolButton#sourceClipMenuButton {{
    min-width: {CONTROL_HEIGHT - 2}px;
    max-width: {CONTROL_HEIGHT - 2}px;
    padding: 0;
}}

QToolButton#sourceClipFullscreenButton,
QToolButton#sourceClipRemoveButton,
QToolButton#sourceClipMenuButton {{
    background: transparent;
    border-color: transparent;
}}

QToolButton#sourceClipFullscreenButton:hover,
QToolButton#sourceClipRemoveButton:hover,
QToolButton#sourceClipMenuButton:hover {{
    background: #3c4043;
    border-color: #8ab4f8;
}}

QListWidget {{
    padding: {SPACE_1}px;
}}

QListWidget::item {{
    border-radius: {CONTROL_RADIUS}px;
    margin: 0;
}}

QListWidget::item:selected {{
    background: #39485f;
    color: #ffffff;
}}

QTableView#queueTable {{
    padding: 0;
    background: #17181a;
}}

QTableView#queueTable::item {{
    padding: 0 {SPACE_2}px;
}}

QTableView#queueActiveView,
QTableView#queueUpNextView,
QTableView#queueHistoryView {{
    padding: 0;
    background: #17181a;
    font-size: 10pt;
    border: 1px solid #45474b;
    border-radius: 0px;
}}

QTableView#queueActiveView:focus,
QTableView#queueUpNextView:focus,
QTableView#queueHistoryView:focus {{
    border: 1px solid #45474b;
    border-radius: 0px;
}}

QTableView#queueActiveView::item,
QTableView#queueUpNextView::item,
QTableView#queueHistoryView::item {{
    padding: 0 {SPACE_1}px;
}}

QTableView#queueActiveView QHeaderView::section,
QTableView#queueUpNextView QHeaderView::section,
QTableView#queueHistoryView QHeaderView::section {{
    background: #2a2b2e;
    padding: {SPACE_1}px;
    font-size: 9pt;
}}

QHeaderView {{
    background: #2a2b2e;
    border: none;
    border-bottom: 1px solid #5f6368;
    border-radius: 0px;
}}

QHeaderView::section {{
    background: #2a2b2e;
    border: none;
    border-right: 1px solid #45474b;
    border-radius: 0px;
    padding: {SPACE_2}px;
    color: #e8eaed;
    font-weight: 600;
}}

QHeaderView::section:first {{
    padding-left: 0;
}}

QHeaderView::section:last {{
    padding-right: 0;
    border-right: none;
}}

QProgressBar {{
    min-height: {CONTROL_HEIGHT - 8}px;
    border: 1px solid #5f6368;
    border-radius: {CONTROL_RADIUS}px;
    background: #17181a;
    color: #f1f3f4;
    text-align: center;
}}

QProgressBar::chunk {{
    /* Keep the fill flush with the track so no background sliver appears at
       the right edge as progress approaches the end. */
    border-radius: 0px;
    background: #8ab4f8;
}}

QTabWidget::pane {{
    border: 1px solid #45474b;
    border-radius: {SURFACE_RADIUS}px;
    top: -1px;
}}

QTabBar::tab {{
    background: #303134;
    border: 1px solid #45474b;
    border-bottom: none;
    border-top-left-radius: {CONTROL_RADIUS}px;
    border-top-right-radius: {CONTROL_RADIUS}px;
    margin-right: {SPACE_1}px;
    padding: {SPACE_2}px {SPACE_3}px;
}}

QTabBar::tab:selected {{
    background: #252629;
    color: #ffffff;
}}

QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: {SPACE_1}px 0;
}}

QScrollBar::handle:vertical {{
    background: #5f6368;
    border-radius: {SPACE_1}px;
    min-height: {SPACE_4}px;
}}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {{
    height: 0;
}}

QSplitter#contentMessageSplitter {{
    background: transparent;
}}
"""


def apply_dark_theme(application: QApplication) -> None:
    """Force the application palette to the approved dark presentation."""

    application.setStyle("Fusion")
    application.setStyle(_ReadableSpinBoxStyle(application.style()))
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#202124"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#f1f3f4"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#17181a"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#252629"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#303134"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#f1f3f4"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#f1f3f4"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#303134"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#f1f3f4"))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Link, QColor("#8ab4f8"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#5f8dd3"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor("#8a8d91"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#8a8d91"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#8a8d91"))
    application.setPalette(palette)
    application.setStyleSheet(_DARK_STYLE_SHEET)
