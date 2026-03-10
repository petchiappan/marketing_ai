# Microsoft Copilot Studio + Teams MVP Plan

**Goal:** Trigger Marketing AI (lead enrichment) from **Microsoft Teams** via a **Microsoft Copilot Studio** agent so users can submit searches and get results in the same place they work.

**→ For a step-by-step checklist (Docker + ngrok + Copilot Studio + Teams), see [COPILOT_STUDIO_STEP_BY_STEP.md](COPILOT_STUDIO_STEP_BY_STEP.md).**

---

## How it fits together

```
Teams (user) → Copilot Studio agent → REST API tool → Your Marketing AI API (FastAPI)
```

- **Copilot Studio:** You create a *custom agent*, add a **REST API** tool that points at your Marketing AI API.
- **Teams:** You publish that agent to the **Teams** channel; users open the copilot in Teams and say things like “Enrich Acme Corp” or “What’s the status of my enrichment for Acme?”
- **Your app:** Already a REST API (FastAPI). Copilot Studio needs a **public URL** and an **OpenAPI** spec to know which actions to call (submit enrichment, get status, get result).

---

## MVP plan (4 steps)

### 1. Make your API reachable

Copilot Studio must call your API over HTTPS.

- **Option A (quick demo):** Run your app locally and expose it with [ngrok](https://ngrok.com):  
  `ngrok http 8000` → use the `https://….ngrok.io` URL as the API base.
- **Option B (proper):** Deploy the app (e.g. Azure App Service, existing Docker host) and use that base URL (e.g. `https://marketing-ai.azurewebsites.net`).

Use the same base URL when you configure the OpenAPI spec in step 3.

---

### 2. Get the OpenAPI spec

Your FastAPI app already exposes OpenAPI:

- **Full spec:** `GET {BASE_URL}/openapi.json`  
  e.g. `https://your-app.ngrok.io/openapi.json` or `https://marketing-ai.azurewebsites.net/openapi.json`
- Copilot Studio accepts **OpenAPI 3.0** (they convert to v2 internally). So you can use this JSON as-is.

For a **cleaner MVP**, use only the enrichment endpoints so the copilot doesn’t see admin/auth. A minimal spec is in `docs/openapi-copilot-enrichment.json` (see below). Replace `https://YOUR_API_BASE_URL` with your real base URL before uploading.

---

### 3. Create the Copilot Studio agent and add your API

1. Go to [Copilot Studio](https://copilotstudio.microsoft.com) (Power Platform / your org tenant).
2. **Create** a new **Custom agent** (not “Copilot agent” unless you want M365 Copilot).
3. **Tools** → **Add tool** → **New tool** → **REST API**.
4. **Upload** the OpenAPI spec (from step 2):
   - Either the full `/openapi.json` saved as a file, or  
   - The trimmed `openapi-copilot-enrichment.json` with `BASE_URL` set.
5. **Describe the API** clearly, e.g.:  
   *“Marketing AI lead enrichment. Use this to submit a new enrichment request for a company, check the status of a request, or get the enriched lead result. Users say things like ‘enrich Acme Corp’ or ‘what’s the status of my enrichment?’.”*
6. **Authentication:**  
   - **MVP:** “None” if your API is open for the demo (or use a tunnel that doesn’t require auth).  
   - **Better:** “API key” (header or query) and configure the key in the connection, or OAuth 2.0 if you add it to your API.
7. **Select actions** to expose as tools. For MVP, pick at least:
   - **Submit and run enrichment** – `POST /api/enrich/submit-and-run` (creates request and starts the pipeline in one call; use this for “search” from Teams).
   - **Get status** – `GET /api/enrich/{request_id}/status`.
   - **Get result** – `GET /api/enrich/{request_id}/result`.
8. **Configure each action** with a short name and description so the copilot knows when to use it (e.g. “Submit company for lead enrichment”, “Get enrichment status”, “Get enriched lead result”).
9. **Create connection** when prompted and test from the Copilot Studio test pane.

---

### 4. Publish to Teams

1. In Copilot Studio, **Publish** the agent (at least once).
2. Go to **Channels** (or **Publish** → **Channels**) → **Microsoft Teams**.
3. **Add** the **Teams** channel so the agent is available in Teams.
4. Optionally add it to **Microsoft 365 Copilot** if your org uses that.
5. **Share** the agent with your org or a security group so users can open it in Teams (e.g. from **Apps** or a dedicated team).

Users can then open the copilot in Teams and say, for example:
- “Enrich Acme Corp”
- “What’s the status of my last enrichment?”
- “Get the enrichment result for request …”

---

## What you need (summary)

| Item | Purpose |
|------|--------|
| Marketing AI app running and reachable at HTTPS | So Copilot Studio can call it |
| OpenAPI spec (from `/openapi.json` or trimmed file) | So Copilot Studio knows which actions exist |
| Copilot Studio (Power Platform) license / access | To create and publish the agent |
| Teams channel enabled for the agent | So users see it in Teams |

---

## API endpoints for the Copilot (no auth for MVP)

| Action | Method + path |
|--------|----------------|
| **Submit and run (search)** | `POST /api/enrich/submit-and-run` – body: `{ "company_name": "Microsoft" }` |
| Get status | `GET /api/enrich/{request_id}/status` |
| Get result | `GET /api/enrich/{request_id}/result` |
| List requests | `GET /api/enrich/?limit=20` |

The trimmed OpenAPI file is **`openapi-copilot-enrichment.json`**. Replace `https://YOUR_API_BASE_URL` with your ngrok or deployed URL before uploading in Copilot Studio.

---

## Optional: trimmed OpenAPI for Copilot

A minimal OpenAPI file that only exposes the enrichment endpoints is in `openapi-copilot-enrichment.json`. Use it so the copilot only sees “submit enrichment”, “get status”, and “get result”, and doesn’t see admin or auth endpoints. Replace `https://YOUR_API_BASE_URL` with your real base URL (e.g. `https://xyz.ngrok.io` or your deployed URL) before uploading in Copilot Studio.

---

## References

- [Extend your agent with tools from a REST API (preview)](https://learn.microsoft.com/en-us/microsoft-copilot-studio/agent-extend-action-rest-api) – add REST API tool, OpenAPI, auth.
- [Connect and configure an agent for Teams](https://learn.microsoft.com/en-us/microsoft-copilot-studio/publication-add-bot-to-microsoft-teams) – publish to Teams.
