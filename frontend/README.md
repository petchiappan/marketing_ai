# Company Intelligence Dashboard

Next.js UI for the Marketing AI backend: search a company → `POST /api/enrich/submit-and-run` → poll until complete → show Profile / Contacts / News / Financials.

## Run

1. **Backend** (Docker or local) on port **8000**, with `CORS_ORIGINS` including this app:

   ```env
   CORS_ORIGINS=http://localhost:3000
   ```

2. **Frontend**

   ```bash
   cd frontend
   cp .env.local.example .env.local
   npm install
   npm run dev
   ```

3. Open **http://localhost:3000**

Enable at least one contact tool (Lusha/Apollo/Signal Hire) + news + financial in **Admin → Tool Config**, and set **OPENAI_API_KEY** on the backend.
