# Marketing AI – Lead Enrichment Agent

Multi-agent lead enrichment system (FastAPI) with admin control center. Uses **Docker** for local development and deployment (AWS Fargate–ready).

---

## See the UI (quick start)

The **frontend is the Admin Control Center**: login page + dashboard (tool config, rate limits, token usage, agent runs, etc.). It’s served by the same FastAPI app (no separate frontend repo).

1. **Using Docker (recommended)**  
   From the project root:
   ```bash
   cp .env.example .env
   # Edit .env: set OPENAI_API_KEY if you’ll use LLM features
   docker compose up -d --build
   ```
   Then open: **http://localhost:8000/admin/login**  
   Login: `admin@localhost` / `changeme123` (from `.env`).

2. **Without Docker**  
   You need Postgres and Redis running. Set `DATABASE_URL` and `REDIS_URL` in `.env`, then:
   ```bash
   pip install -e .
   uvicorn app.main:app --reload --port 8000
   ```
   Open **http://localhost:8000/admin/login**.

- **API docs:** http://localhost:8000/docs  
- **Health:** http://localhost:8000/health  

**Where to search in the UI:** On the Dashboard you’ll see **“Enrich a company”** — enter a company name (e.g. Microsoft, Acme Corp) and click **Submit & run**. Then use **Job Queue** to see status and **Traces**. Full flow and API endpoints: **[docs/UI_SEARCH_AND_ENDPOINTS.md](docs/UI_SEARCH_AND_ENDPOINTS.md)**.

**Teams + Copilot Studio (plugin/add-in):** To make the app searchable from Teams: expose localhost with **ngrok**, then add the API in Copilot Studio and publish to Teams. **Step-by-step:** [docs/COPILOT_STUDIO_STEP_BY_STEP.md](docs/COPILOT_STUDIO_STEP_BY_STEP.md). Overview: [docs/COPILOT_STUDIO_TEAMS_MVP.md](docs/COPILOT_STUDIO_TEAMS_MVP.md). Use `docs/openapi-copilot-enrichment.json` (set your API base URL) when adding the REST API tool.

---

## Folder structure

```
marketing_ai/
├── app/
│   ├── main.py              # FastAPI app, /health, /docs, static
│   ├── api/
│   │   ├── enrichment_routes.py
│   │   └── admin_routes.py
│   ├── agents/              # Contact, news, financial, orchestrator, pipeline
│   ├── auth/                # Local + OIDC (Azure AD)
│   ├── config/              # settings, logging
│   ├── db/                  # SQLAlchemy models, session, repository
│   ├── infrastructure/      # cache, rate limiter, LLM cache, evaluation
│   ├── schemas/             # Pydantic schemas per agent
│   ├── tools/               # Apollo, Lusha, SignalHire, Salesforce, news, financial
│   └── admin/               # Dashboard templates, static (CSS/JS)
├── alembic/                 # DB migrations
├── deploy/
│   ├── buildspec.yml        # AWS CodeBuild – build & push image to ECR
│   └── ecs-task-definition.json  # Fargate task (secrets from SSM)
├── Dockerfile               # Multi-stage, non-root, health check
├── docker-compose.yml       # Local stack: app + Postgres 16 + Redis 7
├── pyproject.toml           # Python deps (FastAPI, CrewAI, etc.)
└── .env.example             # Copy to .env and fill secrets
```

---

## Run locally with Docker (recommended, free)

Uses **Docker** only (no AWS needed). Postgres and Redis run in containers.

**If you see `command not found: docker`:** install [Docker Desktop for Mac](https://www.docker.com/products/docker-desktop/), then run the commands below. Run each line separately (do not paste the `#` comment lines).

1. **Create env file**
   ```bash
   cp .env.example .env
   ```
   Edit `.env` and set `OPENAI_API_KEY` (and others if needed).

2. **Start the stack**
   ```bash
   cd /Users/arun/marketing_ai
   docker compose up -d --build
   ```

3. **Open**
   - App: http://localhost:8000  
   - API docs: http://localhost:8000/docs  
   - Health: http://localhost:8000/health  
   - Admin: http://localhost:8000/admin/login  
     - Default: `admin@localhost` / `changeme123`

4. **Logs**
   ```bash
   docker compose logs -f app
   ```

5. **Stop**
   ```bash
   docker compose down
   ```

---

## Run without Docker (optional)

- Start Postgres and Redis locally (or use cloud instances).
- Set `DATABASE_URL` and `REDIS_URL` in `.env` to point to them.
- Then:
  ```bash
  python -m venv .venv && source .venv/bin/activate   # or .venv\Scripts\activate on Windows
  pip install -e .
  uvicorn app.main:app --reload --port 8000
  ```

---

## Deployment (Docker → AWS Fargate)

Deployment is **Docker-based**: the same image built by the Dockerfile is pushed to ECR and run on Fargate.

- **Build/push**: `deploy/buildspec.yml` (CodeBuild) builds the image and pushes to ECR.
- **Run**: `deploy/ecs-task-definition.json` defines the Fargate task; secrets (e.g. `DATABASE_URL`, `OPENAI_API_KEY`) come from AWS SSM.
- Replace `<ACCOUNT_ID>` and `<REGION>` in the task definition and wire CodePipeline to use `imagedefinitions.json` for ECS deployment.

---

## Docker build failing with I/O errors?

If you see **`Input/output error`** or **`Could not open file ... open (5: Input/output error)`** during `docker compose up -d --build`, it’s usually Docker Desktop or disk, not the app.

1. **Restart Docker Desktop** (quit fully, then start again).
2. **Prune build cache** (removes possibly corrupted cache):
   ```bash
   docker builder prune -af
   ```
3. **Rebuild without cache**:
   ```bash
   cd /Users/arun/marketing_ai
   docker compose build --no-cache
   docker compose up -d
   ```
4. **Check disk**: Ensure you have several GB free. On Mac, Docker uses a VM; in Docker Desktop → Settings → Resources you can increase disk image size if needed.
5. If it still fails, try **Reset to factory defaults** in Docker Desktop (Settings → Troubleshoot), then run the build again.

---

## Checklist – things that are easy to miss

| Item | What to do |
|------|------------|
| **`.env`** | Copy from `.env.example`. Without it, the app may use wrong DB/Redis or missing keys. |
| **`OPENAI_API_KEY`** | Required for LLM/agents. Set in `.env` (or use another provider and its key). |
| **Postgres port conflict** | If 5432 is in use, `docker-compose.yml` maps DB to host **5434**; app inside Docker still uses `db:5432`. |
| **Admin login** | First run seeds user from `DEFAULT_ADMIN_EMAIL` / `DEFAULT_ADMIN_PASSWORD` in `.env`. |
| **Azure AD** | Optional. Leave `AZURE_AD_TENANT_ID` etc. empty to use local login only. |
| **Template paths** | Admin login/dashboard templates are loaded from `app/admin/templates/` (path is resolved from code, not cwd). |

---

## Environment variables (see `.env.example`)

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | PostgreSQL (async: `postgresql+asyncpg://...`) |
| `REDIS_URL` | Redis URL |
| `OPENAI_API_KEY` | LLM (or set `LLM_PROVIDER` / other provider keys) |
| `JWT_SECRET_KEY` | Admin auth |
| `DEFAULT_ADMIN_EMAIL` / `DEFAULT_ADMIN_PASSWORD` | First-run admin seed |
