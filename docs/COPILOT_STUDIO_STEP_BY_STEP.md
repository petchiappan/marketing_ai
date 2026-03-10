# Microsoft Copilot Studio + Teams – Step-by-step execution

Use this checklist to get your **localhost (Docker)** Marketing AI visible in **Teams as a plugin**: expose the app with ngrok, then add it as a REST API tool in Copilot Studio and publish to Teams.

---

## Step 1: Run the app (Docker)

Ensure the stack is up and the app is listening on port 8000.

```bash
cd /Users/arun/marketing_ai
docker compose up -d
```

Check: open **http://localhost:8000/health** in a browser → `{"status":"ok"}`.

---

## Step 2 (MANUAL): Expose localhost with ngrok

Copilot Studio runs in the cloud and must call your API over **HTTPS**. Localhost is not reachable, so expose it with ngrok.

1. Install ngrok: https://ngrok.com/download (or `brew install ngrok`).
2. In a terminal, run:
   ```bash
   ngrok http 8000
   ```
3. Copy the **HTTPS** URL ngrok shows (e.g. `https://abc123.ngrok-free.app`).  
   This is your **API base URL** for the next steps.
4. Leave ngrok running whenever you want to test the Teams plugin.

**Optional:** Sign up for a free ngrok account and set an auth token so the URL is stable.

---

## Step 3: Put your API URL into the OpenAPI spec

1. Open **`docs/openapi-copilot-enrichment.json`** in an editor.
2. Replace **`https://YOUR_API_BASE_URL`** with your ngrok URL (no trailing slash).  
   Example:
   ```json
   "servers": [
     { "url": "https://abc123.ngrok-free.app", "description": "Your app via ngrok" }
   ]
   ```
3. Save the file.

**Endpoints in this spec (all under `/api/enrich`):**

| Action | Method + path | Purpose |
|--------|----------------|--------|
| **Submit and run** (use this for “search”) | `POST /api/enrich/submit-and-run` | Create request and start pipeline in one call. |
| Submit only | `POST /api/enrich/` | Create request only (then trigger from UI). |
| List requests | `GET /api/enrich/` | List with optional `limit`, `status_filter`. |
| Get status | `GET /api/enrich/{request_id}/status` | Check status of a request. |
| Get result | `GET /api/enrich/{request_id}/result` | Get enriched lead data when complete. |

---

## Step 4 (MANUAL): Create the agent in Copilot Studio

1. Go to **https://copilotstudio.microsoft.com** and sign in with your work account.
2. **Create** → **New agent** → **Custom agent** (or “Create from scratch”).
3. Name it (e.g. “Marketing AI Enrichment”).
4. Open **Tools** (left rail) → **Add tool** → **New tool** → **REST API**.
5. **Upload** the edited **`openapi-copilot-enrichment.json`** (drag and drop or Browse).
6. **Description** (for the copilot):  
   *“Marketing AI lead enrichment. Use this to submit a company for enrichment (e.g. ‘enrich Microsoft’, ‘search for Acme Corp’), check the status of a request, or get the enriched lead result. For searching/enriching a company, use the action ‘Submit and run enrichment’.”*
7. **Authentication:** choose **None** for MVP (your API is behind ngrok; for production use API key or OAuth).
8. **Select actions** to expose. For “search from Teams” enable at least:
   - **Submit and run enrichment** (`POST /api/enrich/submit-and-run`) – main “search” action.
   - **Get enrichment status** (`GET /api/enrich/{request_id}/status`).
   - **Get enrichment result** (`GET /api/enrich/{request_id}/result`).
9. Configure each action with a short **name** and **description** so the copilot knows when to use it.
10. **Create connection** when prompted (name it e.g. “Marketing AI”), then **Add** the tool to the agent.
11. In the test pane, try: *“Enrich Microsoft”* or *“Search for Stripe”* – the copilot should call your API (with ngrok running and app up).

---

## Step 5 (MANUAL): Publish to Teams (add-in / plugin)

1. In Copilot Studio, open **Publish** (or **Channels**).
2. **Publish** the agent (if not already).
3. Under **Channels**, open **Microsoft Teams**.
4. **Add** the **Teams** channel so the agent is available in Teams.
5. **Share** the agent with your org or a group so users can install it (e.g. via **Apps** in Teams → “Built for your org” or the link Copilot Studio provides).

Users can then open the copilot in Teams (as an add-in/plugin) and say:
- “Enrich Microsoft”
- “What’s the status of my enrichment?”
- “Get the result for request [id]”

---

## Step 6: Test end-to-end

1. **ngrok** is running and **Docker** app is up.
2. Open **Teams** → open your **Marketing AI** copilot (from Apps or the channel you added).
3. Say: **“Enrich Acme Corp”** (or any company name).
4. The copilot should call `POST /api/enrich/submit-and-run` and reply with the request id and that enrichment started.
5. In the **Admin UI** (http://localhost:8000/admin → Job Queue) you should see the new request and its runs.
6. After the job completes, in Teams you can ask: “What’s the status of request [id]?” or “Get the result for request [id].”

---

## Summary

| Step | Who | What |
|------|-----|------|
| 1 | You (terminal) | `docker compose up -d` |
| 2 | You (manual) | Run `ngrok http 8000`, copy HTTPS URL |
| 3 | You (editor) | Replace `YOUR_API_BASE_URL` in `docs/openapi-copilot-enrichment.json` |
| 4 | You (manual) | Copilot Studio: create agent, add REST API tool, upload spec, select actions, create connection |
| 5 | You (manual) | Publish → Teams channel → share with org |
| 6 | You | Test from Teams: “Enrich [company]” |

Your localhost app is then **visible** to Copilot Studio via ngrok and usable in **Teams as a plugin**.
