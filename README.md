# Homelab Dashboard

Web-based management panel for homelab servers. Provides system monitoring, Docker container management, app marketplace, and automated SSL with reverse proxy.

## Tech Stack
- **Backend:** FastAPI, SQLite (async), Docker SDK for Python, PyJWT
- **Frontend:** React, TypeScript, Vite, TanStack Query
- **Infrastructure:** Caddy (Reverse Proxy + Auto SSL), Docker Compose

## Quickstart (Development)

1. **Backend**
   ```bash
   cd backend
   cp .env.example .env
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt -r requirements-dev.txt
   
   # Run migrations
   alembic upgrade head
   
   # Start dev server
   uvicorn app.main:app --reload
   ```

2. **Frontend**
   ```bash
   cd frontend
   npm ci
   npm run dev
   ```

## Production Deployment

```bash
# Clone the repository
git clone https://github.com/user/homelab-dashboard.git
cd homelab-dashboard

# Setup backend environment
cp backend/.env.example backend/.env
# Edit backend/.env and set a strong JWT_SECRET and correct DOMAIN

# Start the stack
docker compose up -d
```

## Available Scripts

### Backend (`/backend`)
- `pytest` — Run unit and integration tests
- `ruff check .` — Lint Python code
- `mypy app/` — Static type checking
- `alembic revision --autogenerate -m "msg"` — Create a new database migration

### Frontend (`/frontend`)
- `npm run dev` — Start Vite dev server on port 5173
- `npm run test` — Run Vitest tests
- `npm run lint` — Lint TS/React code
- `npm run build` — Create production build

## Project Status
- [x] Phase 1: Project Scaffolding
- [ ] Phase 2: Monitoring & Dashboard
- [ ] Phase 3: Container Management
- [ ] Phase 4: Marketplace & SSL
- [ ] Phase 5: Security & Backup
