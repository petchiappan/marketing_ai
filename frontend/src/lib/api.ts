const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type ConnectorStatus = {
  lusha: boolean;
  news: boolean;
  finance: boolean;
  llm: boolean;
};

export async function fetchConnectorStatus(): Promise<ConnectorStatus> {
  const r = await fetch(`${API}/api/connectors/status`);
  if (!r.ok) throw new Error("Failed to load connector status");
  return r.json();
}

export async function submitAndRun(companyName: string, requestedBy?: string) {
  const r = await fetch(`${API}/api/enrich/submit-and-run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      company_name: companyName,
      source: "api",
      requested_by: requestedBy || undefined,
    }),
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(err.detail || r.statusText);
  }
  return r.json() as Promise<{ id: string; company_name: string; status: string; message: string }>;
}

export async function getStatus(requestId: string) {
  const r = await fetch(`${API}/api/enrich/${requestId}/status`);
  if (!r.ok) throw new Error("Status failed");
  return r.json() as Promise<{ id: string; company_name: string; status: string; created_at: string }>;
}

export async function getResult(requestId: string) {
  const r = await fetch(`${API}/api/enrich/${requestId}/result`);
  if (!r.ok) {
    if (r.status === 404) return null;
    throw new Error("Result not ready");
  }
  return r.json() as Promise<Record<string, unknown>>;
}

export function pollUntilComplete(
  requestId: string,
  onTick: (s: { status: string }) => void,
  intervalMs = 2500,
  maxWaitMs = 600_000
): Promise<string> {
  const start = Date.now();
  return new Promise((resolve, reject) => {
    const tick = async () => {
      try {
        const s = await getStatus(requestId);
        onTick(s);
        if (s.status === "completed" || s.status === "partial") {
          resolve(s.status);
          return;
        }
        if (s.status === "failed") {
          reject(new Error("Enrichment failed"));
          return;
        }
        if (Date.now() - start > maxWaitMs) {
          reject(new Error("Timeout waiting for enrichment"));
          return;
        }
        setTimeout(tick, intervalMs);
      } catch (e) {
        reject(e);
      }
    };
    tick();
  });
}
