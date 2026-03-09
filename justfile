# TypeWirePy development commands

test:
    uv run pytest

lint:
    uv run ruff check src/ tests/

format:
    uv run ruff format src/ tests/

type-check:
    uv run mypy src/typewirepy/ && uv run pyright src/typewirepy/

check: lint format type-check test
