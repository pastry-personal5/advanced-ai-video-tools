.PHONY: install format format-check lint test check run performance-test gui-capture-test package-dev-dmg

PERFORMANCE_REPORT ?= /private/tmp/advanced-ai-video-tools-performance.xml
PERFORMANCE_UV_CACHE_DIR ?= /private/tmp/advanced-ai-video-tools-uv-cache

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
	UV_CACHE_DIR="$(PERFORMANCE_UV_CACHE_DIR)" UV_LINK_MODE=copy QT_QPA_PLATFORM=cocoa ADVANCED_AI_VIDEO_TOOLS_RUN_NATIVE_ACCEPTANCE=1 uv run pytest -m performance tests/test_native_acceptance.py --junitxml="$(PERFORMANCE_REPORT)"

gui-capture-test:
	QT_QPA_PLATFORM=cocoa ADVANCED_AI_VIDEO_TOOLS_RUN_NATIVE_ACCEPTANCE=1 uv run pytest -m gui_capture tests/test_native_acceptance.py

package-dev-dmg:
	packaging/macos/build_unsigned_dmg.sh
