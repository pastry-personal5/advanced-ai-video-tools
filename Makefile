.PHONY: install format format-check lint test check run performance-test gui-capture-test

install:
	uv sync --dev

format:
	uv run black src tests

format-check:
	uv run black --check src tests

lint:
	PYLINTHOME=.cache/pylint uv run pylint src tests
	uv run pycodestyle src tests

test:
	uv run pytest

check: format-check lint test

run:
	uv run advanced-ai-video-tools gui

performance-test:
	# Native presentation benchmark only; never invokes media processing or upscaling.
	QT_QPA_PLATFORM=cocoa ADVANCED_AI_VIDEO_TOOLS_RUN_NATIVE_ACCEPTANCE=1 uv run pytest -m performance tests/test_native_acceptance.py

gui-capture-test:
	QT_QPA_PLATFORM=cocoa ADVANCED_AI_VIDEO_TOOLS_RUN_NATIVE_ACCEPTANCE=1 uv run pytest -m gui_capture tests/test_native_acceptance.py
