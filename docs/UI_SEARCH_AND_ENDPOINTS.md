# Where to search in the UI and which endpoints to use

## In the UI (frontend)

1. **Log in** at **http://localhost:8000/admin/login** (e.g. `admin@localhost` / `changeme123`).

2. **Submit a new enrichment (search for a company)**  
   On the **Dashboard**, use the **“Enrich a company”** card at the top:
   - Enter a **company name** (e.g. *Microsoft*, *Acme Corp*, *Stripe*).
   - Optionally enter **Your name** (requested by).
   - Click **Submit & run**.  
   This creates an enrichment request and starts the pipeline (Contact, News, Financial agents using tools like Apollo, Lusha, SignalHire). You are then taken to **Job Queue**.

3. **Job Queue** (sidebar → **Job Queue**)  
   - Lists all enrichment requests (company, source, status, requested by, created time).  
   - For **pending** or **failed** jobs you can click **Run** to trigger processing.  
   - Use **Traces** to open **Agent Runs** filtered by that request (Contact/News/Financial/Aggregation runs and traces).

4. **Tool Config** (sidebar → **Tool Config**)  
   - Configure **Apollo**, **Lusha**, **SignalHire**, etc.: display name, base URL, API key, which agent uses the tool, enabled/disabled.  
   - This does **not** run a search; it only configures the data sources used when you submit an enrichment from the Dashboard or API.

5. **Agent Runs**  
   - View runs per job (contact, news, financial, aggregation).  
   - **View Trace** opens the **Trace Viewer** for that run (input/output, errors).

6. **Response Evaluation**  
   - Metrics on cache hit, schema compliance, completeness, etc.

---

## API endpoints (to trigger search / get results)

| What you want           | Method + endpoint                         | Body (if POST) |
|-------------------------|-------------------------------------------|----------------|
| **Submit new enrichment** | `POST /api/enrich/`                     | `{ "company_name": "Microsoft", "source": "api", "requested_by": "you@example.com" }` |
| **List requests**       | `GET /api/enrich/?limit=50&status_filter=pending` | — |
| **Get status**          | `GET /api/enrich/{request_id}/status`    | — |
| **Get enriched result** | `GET /api/enrich/{request_id}/result`   | — |
| **Trigger run (admin)** | `POST /admin/api/trigger-enrichment/{request_id}` | — (requires auth cookie) |

- **Submit** creates a request in `pending` state. To actually run the pipeline you either:
  - Use the UI: Dashboard “Submit & run” (which also calls the trigger endpoint), or Job Queue → **Run**, or
  - Call `POST /admin/api/trigger-enrichment/{request_id}` with an authenticated session.
- **Tools** (Apollo, Lusha, SignalHire) are used **inside** the pipeline when a job runs; they are configured under **Tool Config**, not called by a separate “search” endpoint.

---

## Quick flow

1. **UI:** Dashboard → “Enrich a company” → type company name → **Submit & run** → Job Queue shows the job (and it’s already triggered).  
2. **API:** `POST /api/enrich/` with `company_name` → get `id` → `POST /admin/api/trigger-enrichment/{id}` (with auth) → then `GET /api/enrich/{id}/status` and `GET /api/enrich/{id}/result` when complete.
