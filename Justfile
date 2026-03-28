test:
    uv run pytest tests/ -v

test-cov:
    uv run pytest tests/ --cov=tmux_pilot --cov-report=term-missing

lint:
    uv run ruff check src/ tests/

format:
    uv run ruff format src/ tests/

typecheck:
    uv run mypy src/

ci: lint typecheck test

install:
    uv sync

build:
    uv build

publish:
    uv publish
