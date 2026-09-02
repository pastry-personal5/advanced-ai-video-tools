"""Small shared helpers for one-shot Qt worker threads."""

# PySide6 exposes Qt types dynamically, which Pylint cannot introspect.
# pylint: disable=no-name-in-module

from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Qt


def connect_completion_cleanup(thread: QThread, worker: QObject, succeeded: object, failed: object) -> None:
    """Connect terminal worker signals to the common quit/delete lifecycle."""

    # PySide signal instances are intentionally accepted as objects so this
    # helper supports workers whose terminal signal payloads differ.
    succeeded.connect(thread.quit, Qt.ConnectionType.DirectConnection)  # type: ignore[attr-defined]
    failed.connect(thread.quit, Qt.ConnectionType.DirectConnection)  # type: ignore[attr-defined]
    succeeded.connect(worker.deleteLater)  # type: ignore[attr-defined]
    failed.connect(worker.deleteLater)  # type: ignore[attr-defined]
    thread.finished.connect(thread.deleteLater)


def shutdown_worker_thread(thread: QThread | None) -> None:
    """Stop and join a worker thread before its owning Qt object is destroyed."""

    if thread is not None and thread.isRunning():
        thread.quit()
        thread.wait()
