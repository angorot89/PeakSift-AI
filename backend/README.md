# PeakSift AI — Backend

FastAPI service. It currently exposes a single health endpoint, `GET /health`.

## Prerequisites

- Python 3.11+ (check with `python3 --version`)

All commands below are run from the `backend/` directory.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env               # optional; defaults work for local development
```

## Run

```bash
uvicorn app.main:app --reload
```

- API: http://localhost:8000/health returns `{"status": "ok"}`
- Interactive docs: http://localhost:8000/docs

## Test

```bash
pytest
```

## Lint and format (Ruff)

```bash
ruff check .            # lint
ruff format .           # format
```

## Configuration

Settings are read from environment variables, or from `backend/.env` if present (see [.env.example](.env.example)):

| Variable       | Default                 | Purpose                                     |
| -------------- | ----------------------- | ------------------------------------------- |
| `APP_ENV`      | `development`           | Environment name                            |
| `FRONTEND_URL` | `http://localhost:3000` | Origin allowed by CORS                      |
| `DATABASE_URL` | empty                   | Not used yet; reserved for the database     |
| `SECRET_KEY`   | empty                   | Not used yet; reserved for future features  |
