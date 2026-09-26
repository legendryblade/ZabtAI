# Contributing to zabt.ai

Thanks for your interest in improving zabt.ai! This guide covers local setup, style, tests,
and the PR process.

## Contributor License Agreement (required)

Before your first pull request can be merged you must sign the
[Contributor License Agreement](./CLA.md). This is automated: a bot will comment on your PR
with a one-line sign-off you paste back. You keep ownership of your contribution; the CLA lets
the project be offered under both the AGPL-3.0 and a commercial license. See [CLA.md](./CLA.md)
for the plain-English summary.

## Development setup

zabt.ai is a monorepo: `backend/` (FastAPI + Celery), `frontend-2/` (Next.js), plus GPU/bot/
vision workers and a shared TS package.

### Prerequisites
- Python 3.11+
- Node.js 20+ and npm
- PostgreSQL, Redis, and MinIO for native development
- Docker + Docker Compose for the containerized full stack

### Fastest path: run the stack in Docker
```bash
cp .env.example .env      # fill the REQUIRED values (see README)
docker compose up -d
```

### Native development

For Windows-native installation and startup, see [docs/native-development.md](docs/native-development.md). The backend can also be installed from `backend/requirements-dev.txt`:

```powershell
py -3.11 -m venv C:\Users\abdul\.venvs\zabt-backend
& C:\Users\abdul\.venvs\zabt-backend\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
```

### Running services directly (for active development)
```bash
# Start PostgreSQL, Redis, and MinIO separately, then:
cd backend && uv run uvicorn app.main:app --reload --port 8000
cd backend && uv run celery -A app.worker.celery_app worker --loglevel=info
npm install
npm run build:shared
npm run dev:web
```

## Code style

- **Python** (`backend/`, workers): formatted and linted with [ruff](https://docs.astral.sh/ruff/).
  Run `uv run ruff check .` and `uv run ruff format .`. Use the Repository Pattern
  (`BaseService`) for data access — see existing services.
- **TypeScript** (`frontend-2/`): follow the existing components and the design system in
  [DESIGN.md](./DESIGN.md). Lint with `npm run lint --workspace=frontend-2`. Type-check with
  `npx tsc --noEmit`.
- **License headers:** new source files need an SPDX header. Run
  `uv run python scripts/add_spdx_headers.py` (idempotent) before committing.

## Tests

```bash
# Backend
cd backend && uv run pytest

# Frontend type-check
cd frontend-2 && npx tsc --noEmit
```

Please add or update tests for behavior changes.

## Pull request process

1. Fork and branch from `main` (`feat/...`, `fix/...`, `docs/...`).
2. Keep PRs focused; write a clear description of the change and why.
3. Ensure lint, type-check, and tests pass locally.
4. Make sure new files carry SPDX headers.
5. Open the PR and sign the CLA when the bot asks.
6. A maintainer will review. CI (lint + tests + secret scan + compose build) must be green.

## Good first issues

Look for issues labeled [`good first issue`](https://github.com/afeef/zabt-ai/labels/good%20first%20issue).
New to the codebase? Documentation fixes, small UI polish, and test coverage are great entry
points.

## Reporting bugs / requesting features

Use the issue templates. For **security vulnerabilities**, do **not** open a public issue —
follow [SECURITY.md](./SECURITY.md).
