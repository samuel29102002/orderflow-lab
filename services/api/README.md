# orderflow-api

FastAPI gateway for Orderflow Lab. Python 3.12, Pydantic v2.

## Layout

```
app/
├── main.py          # FastAPI app factory
├── api/             # HTTP transport (routers)
├── services/        # use-cases
├── domain/          # pure models
├── infra/           # repos, clients, adapters
└── core/            # settings, logging, etc.
```

This split is defined in `PROJECT_DESIGN.md` Phase 8 §4.

## Dev

```bash
# Create a venv (use python3.12 explicitly)
python3.12 -m venv .venv && source .venv/bin/activate

# Install (editable) with dev extras
pip install -e ".[dev]"

# Run
uvicorn app.main:app --reload

# Test
pytest
```

Env variables are prefixed `ORDERFLOW_` (see `app/core/config.py`).
