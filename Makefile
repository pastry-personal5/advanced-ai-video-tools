.PHONY: install format format-check lint test check run

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
