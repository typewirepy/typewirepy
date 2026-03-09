# Contributing to TypeWirePy

## Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) (package manager)

## Development setup

```bash
git clone https://github.com/typewirepy/typewirepy.git
cd typewirepy
uv sync
```

## Running tests

```bash
uv run pytest
```

## Linting & formatting

```bash
uv run ruff check src/ tests/
uv run ruff format src/ tests/
```

## Type checking

```bash
uv run mypy src/typewirepy/
uv run pyright src/typewirepy/
```

## Pull request guidelines

1. Branch from `main`
2. Ensure all CI checks pass (tests, lint, format, type-check)
3. Keep changes focused — one feature or fix per PR
