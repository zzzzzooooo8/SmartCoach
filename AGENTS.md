# Repository Guidelines

## Project Structure & Module Organization
- `backend/` contains the FastAPI service and Python dependencies managed by `uv`.
- `backend/app/main.py` defines the API; `backend/app/agent/` holds the LangGraph agent, tool logic, and shared state.
- `backend/app/data/` documents local knowledge-source conventions and stores ignored runtime data such as SQLite/Chroma persistence files.
- `frontend/` contains the Next.js 16 frontend. App Router files live in `frontend/app/`; static assets live in `frontend/public/`.

## Build, Test, and Development Commands
- Backend setup: `cd backend && uv sync` installs Python dependencies from `pyproject.toml` and `uv.lock`.
- Backend dev server: `cd backend && uv run python main.py` starts FastAPI on `127.0.0.1:8000`.
- Frontend setup: `cd frontend && pnpm install` installs Node dependencies.
- Frontend dev server: `cd frontend && pnpm dev` starts Next.js on `http://localhost:3000`.
- Frontend quality checks: `cd frontend && pnpm lint` runs the configured ESLint rules.
- Production build: `cd frontend && pnpm build` verifies the frontend can compile.

## Coding Style & Naming Conventions
- Follow the existing style in each area: Python uses 4-space indentation; TypeScript/React uses 2 spaces.
- Use `snake_case` for Python modules/functions and `PascalCase` for React component names.
- Keep frontend imports compatible with the `@/*` alias defined in `frontend/tsconfig.json`.
- Prefer small, focused modules under `backend/app/agent/` and keep page-level UI in `frontend/app/`.

## Testing Guidelines
- Run backend tests with `cd backend && uv run python -m unittest discover -s tests -v`.
- Verify frontend code with `cd frontend && pnpm lint && pnpm build`.
- Before opening a PR, smoke-test both apps and confirm the frontend can call `http://127.0.0.1:8000/api/chat`.
- Place new backend tests under `backend/tests/` and frontend tests beside the feature as `*.test.ts(x)`.

## Commit & Pull Request Guidelines
- Git metadata is not present in this workspace, so no repository-specific commit pattern can be derived from history.
- Use short, imperative commit messages such as `feat: add chat history persistence` or `fix: handle missing API key`.
- PRs should include: a clear summary, affected paths, setup or env changes, and screenshots for frontend UI changes.

## Security & Configuration Tips
- Do not commit real API keys or `.env` files. Required backend variables include OpenAI/Silicon model and base URL settings.
- Treat `backend/app/data/chroma_db_storage/` as generated state unless a change is intentional.
