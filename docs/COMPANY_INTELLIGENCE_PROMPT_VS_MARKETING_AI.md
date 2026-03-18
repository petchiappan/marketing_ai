# Company Intelligence Dashboard prompt vs this repo (`marketing_ai`)

The file **company-intelligence-dashboard-prompt.md** describes a **greenfield** app: `backend/` + `frontend/` (Next.js), **synchronous** `POST /api/search`, and three connectors (Lusha, NewsAPI, Alpha Vantage) with a **premium React dashboard**.

This repository is already a **related but different** product.

---

## What already matches (conceptually)

| Prompt spec | This repo (`marketing_ai`) |
|-------------|----------------------------|
| FastAPI + CrewAI | ✅ `app/main.py`, `app/agents/orchestrator.py`, `pipeline.py` |
| Lusha-style contacts | ✅ Contact agent + `app/tools/lusha.py`, Apollo, SignalHire |
| News intelligence | ✅ News agent + `app/tools/news_search.py` |
| Financial data | ✅ Financial agent + `app/tools/financial_data.py` |
| Multi-agent orchestration | ✅ Sequential crew: contact → news → financial → aggregation |
| API keys / env | ✅ `.env`, Tool Config in admin UI |

---

## What is different

| Area | Prompt | This repo |
|------|--------|-----------|
| **Frontend** | Next.js 14, Tailwind, Framer Motion, “Dark Observatory” | HTML admin (`app/admin/`) — no React app |
| **Search API** | `POST /api/search` → **immediate** JSON (crew result in one response) | `POST /api/enrich/submit-and-run` → **async** job; result via `GET /api/enrich/{id}/result` |
| **Layout** | `backend/` + `frontend/` folders | Single Python package `app/` |
| **Connectors** | Dedicated `connectors/` + NewsAPI + Alpha Vantage | Tools wired via DB + CrewAI tools (may use different APIs) |
| **Connector status** | `GET /api/connectors/status` | Partially: Tool Config + health checks; no single 3-pill endpoint |
| **CORS** | Explicit for `localhost:3000` | Not configured for a separate SPA origin |

---

## If you want the prompt “as written”

1. **New Next.js app** under `frontend/` (or a sibling repo) with the UI spec (SearchBar, tabs, agent feed, etc.).
2. **Either:**
   - **A)** Build a **new** `backend/` per the prompt (duplicate of agents/connectors), or  
   - **B)** **Extend this API** with:
     - `POST /api/intelligence/search` — run crew synchronously (risk: long timeouts; use only for demos or increase worker timeout), **or**
     - **Recommended:** keep async flow — frontend calls `submit-and-run` + polls `status`/`result`, then maps JSON into Lusha / News / Finance tabs.
3. **`GET /api/connectors/status`** — map to whether Lusha, news, financial tools have keys enabled (small new endpoint).
4. **CORS** — allow `http://localhost:3000` (and prod origin) on FastAPI.

---

## Suggested order of work

1. **MVP dashboard on top of existing API** (fastest): Next.js app that calls `POST /api/enrich/submit-and-run`, polls until `completed`, then splits `GET /api/enrich/{id}/result` into three tab views (contacts, news, financials from one payload).
2. **Polish**: Add `/api/connectors/status`, CORS, then iterate UI toward the “Dark Observatory” spec.
3. **Full prompt parity**: Add dedicated NewsAPI / Alpha Vantage connectors only if current tools don’t meet data needs.

---

## Deliverables table (from prompt) — status in this repo

| # | Deliverable | In `marketing_ai` today |
|---|-------------|-------------------------|
| 1 | Backend API + CrewAI | ✅ (different paths & async model) |
| 2–4 | Lusha / News / Finance connectors | ✅ as CrewAI tools (not identical APIs) |
| 5 | React dashboard | ❌ — admin HTML only |
| 6–12 | Search bar, status bar, tabs, animations, etc. | ❌ — would be new `frontend/` |

---

*Use this doc to decide: extend `marketing_ai` with a Next.js front + thin API glue, or fork a new repo that follows the prompt’s folder layout.*

---

## Implemented in this repo (MVP path)

| Item | Location |
|------|----------|
| **CORS** for `http://localhost:3000` (configurable) | `CORS_ORIGINS` in `.env` → `app/main.py` |
| **`GET /api/connectors/status`** | `app/api/intelligence_routes.py` — `lusha` (contacts), `news`, `finance`, `llm` |
| **Next.js dashboard** | `frontend/` — search bar, status pills, tabs, async poll after `submit-and-run` |

Run: backend on `:8000`, then `cd frontend && npm install && npm run dev` → **http://localhost:3000**. See **`frontend/README.md`**.
