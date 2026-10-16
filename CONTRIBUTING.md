# Contributing

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install '.[dev]'
cp config.example.yaml config.yaml
```

## Before opening a PR

```bash
npm run rag:verify
# ruff check + ruff format --check + pytest
```

## Guidelines

- Keep changes focused; ask before large refactors.
- Match existing code style and patterns.
- Add or update tests when behavior changes.
- Do not commit `.venv/`, `config.yaml`, `qdrant_data/`, or secrets.
