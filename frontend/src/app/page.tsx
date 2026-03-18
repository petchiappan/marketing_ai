"use client";

import { useCallback, useEffect, useState } from "react";
import {
  fetchConnectorStatus,
  submitAndRun,
  pollUntilComplete,
  getResult,
  type ConnectorStatus,
} from "@/lib/api";

type Tab = "profile" | "contacts" | "news" | "finance";

function Pill({
  label,
  ok,
  sub,
}: {
  label: string;
  ok: boolean;
  sub?: string;
}) {
  return (
    <div
      className={`flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-medium backdrop-blur-md border ${
        ok
          ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
          : "border-amber-500/25 bg-amber-500/10 text-amber-200/80"
      }`}
    >
      <span className={`h-2 w-2 rounded-full ${ok ? "bg-emerald-400 animate-pulse" : "bg-amber-400"}`} />
      {label}
      {sub && <span className="text-white/40 font-normal">{sub}</span>}
    </div>
  );
}

export default function Page() {
  const [status, setStatus] = useState<ConnectorStatus | null>(null);
  const [company, setCompany] = useState("");
  const [loading, setLoading] = useState(false);
  const [jobStatus, setJobStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [tab, setTab] = useState<Tab>("profile");

  useEffect(() => {
    fetchConnectorStatus()
      .then(setStatus)
      .catch(() => setStatus({ lusha: false, news: false, finance: false, llm: false }));
  }, []);

  const onSearch = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      const name = company.trim();
      if (!name) return;
      setError(null);
      setResult(null);
      setLoading(true);
      setJobStatus("starting…");
      try {
        const { id } = await submitAndRun(name);
        setJobStatus("processing…");
        await pollUntilComplete(id, (s) => setJobStatus(s.status));
        const data = await getResult(id);
        setResult(data);
        setJobStatus("completed");
      } catch (err) {
        setError(err instanceof Error ? err.message : "Search failed");
        setJobStatus(null);
      } finally {
        setLoading(false);
      }
    },
    [company]
  );

  const contacts = (result?.contacts as unknown[]) || [];
  const news = (result?.recent_news as unknown[]) || [];

  return (
    <div className="min-h-screen p-6 md:p-10 max-w-6xl mx-auto">
      {/* Connector bar */}
      <div className="flex flex-wrap justify-end gap-2 mb-8">
        {status && (
          <>
            <Pill label="Contacts" ok={status.lusha} sub="Lusha/Apollo" />
            <Pill label="News" ok={status.news} />
            <Pill label="Finance" ok={status.finance} />
            <Pill label="LLM" ok={status.llm} />
          </>
        )}
      </div>

      <h1 className="font-display text-4xl md:text-5xl font-semibold tracking-tight text-center mb-2 bg-gradient-to-r from-teal-300 via-cyan-200 to-violet-300 bg-clip-text text-transparent">
        Company Intelligence
      </h1>
      <p className="text-center text-slate-500 text-sm mb-10">
        Powered by Marketing AI — submit a company to run the multi-agent enrichment pipeline
      </p>

      <form onSubmit={onSearch} className="max-w-2xl mx-auto mb-12">
        <div className="glass glow-cyan p-2 flex gap-2 rounded-2xl">
          <input
            type="text"
            value={company}
            onChange={(e) => setCompany(e.target.value)}
            placeholder="Search any company — Microsoft, Tesla, Infosys…"
            className="flex-1 bg-transparent border-0 outline-none px-4 py-3 text-slate-100 placeholder:text-slate-500"
            disabled={loading}
          />
          <button
            type="submit"
            disabled={loading || !company.trim()}
            className="rounded-xl bg-gradient-to-r from-teal-500 to-cyan-600 px-8 py-3 font-semibold text-slate-950 disabled:opacity-40 hover:opacity-95 transition-opacity"
          >
            {loading ? "Running…" : "Search"}
          </button>
        </div>
      </form>

      {error && (
        <div className="max-w-2xl mx-auto mb-6 rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-rose-200 text-sm">
          {error}
        </div>
      )}

      {loading && jobStatus && (
        <p className="text-center text-cyan-400/90 text-sm mb-6 animate-pulse">
          Pipeline: <span className="font-mono">{jobStatus}</span>
        </p>
      )}

      {result && (
        <div className="opacity-100 transition-opacity">
          <div className="glass p-6 mb-6">
            <h2 className="font-display text-2xl font-semibold text-white mb-1">
              {String(result.company_name || "—")}
            </h2>
            <p className="text-slate-400 text-sm">
              {[result.industry, result.headquarters, result.employee_count != null && `${result.employee_count} employees`]
                .filter(Boolean)
                .join(" · ")}
            </p>
            {result.overall_confidence != null && (
              <p className="text-xs text-violet-300/90 mt-2">
                Confidence: {Number(result.overall_confidence).toFixed(2)}
              </p>
            )}
          </div>

          <div className="flex flex-wrap gap-2 mb-4 border-b border-white/10 pb-4">
            {(
              [
                ["profile", "Profile"],
                ["contacts", `Contacts (${contacts.length})`],
                ["news", `News (${news.length})`],
                ["finance", "Financials"],
              ] as const
            ).map(([k, label]) => (
              <button
                key={k}
                type="button"
                onClick={() => setTab(k)}
                className={`rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
                  tab === k
                    ? "bg-cyan-500/20 text-cyan-200 border border-cyan-500/30"
                    : "text-slate-400 hover:text-slate-200"
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          <div className="glass p-6 min-h-[240px]">
            {tab === "profile" && (
              <div className="space-y-4 text-slate-300 text-sm leading-relaxed whitespace-pre-wrap">
                {result.enrichment_summary ? String(result.enrichment_summary) : "No summary yet."}
              </div>
            )}
            {tab === "contacts" && (
              <div className="overflow-x-auto">
                {contacts.length === 0 ? (
                  <p className="text-slate-500">No contacts in this result.</p>
                ) : (
                  <table className="w-full text-left text-sm">
                    <thead>
                      <tr className="border-b border-white/10 text-slate-500">
                        <th className="pb-2 pr-4">Contact</th>
                        <th className="pb-2">Detail</th>
                      </tr>
                    </thead>
                    <tbody>
                      {contacts.map((c, i) => (
                        <tr key={i} className="border-b border-white/5">
                          <td className="py-2 pr-4 font-mono text-xs text-cyan-200/90" colSpan={2}>
                            {typeof c === "object" && c !== null
                              ? JSON.stringify(c, null, 2)
                              : String(c)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            )}
            {tab === "news" && (
              <ul className="space-y-4">
                {news.length === 0 ? (
                  <p className="text-slate-500">No news articles in this result.</p>
                ) : (
                  news.map((n, i) => (
                    <li key={i} className="border-l-2 border-violet-500/40 pl-4 text-sm text-slate-300">
                      {typeof n === "object" && n !== null ? (
                        <pre className="font-mono text-xs overflow-x-auto whitespace-pre-wrap">
                          {JSON.stringify(n, null, 2)}
                        </pre>
                      ) : (
                        String(n)
                      )}
                    </li>
                  ))
                )}
              </ul>
            )}
            {tab === "finance" && (
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 font-mono text-sm">
                <div className="rounded-lg bg-white/5 p-4">
                  <div className="text-slate-500 text-xs mb-1">Revenue</div>
                  <div className="text-emerald-300">
                    {result.revenue != null ? String(result.revenue) : "—"}
                  </div>
                </div>
                <div className="rounded-lg bg-white/5 p-4">
                  <div className="text-slate-500 text-xs mb-1">Funding</div>
                  <div className="text-amber-200/90">
                    {result.funding_total != null ? String(result.funding_total) : "—"}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      <p className="text-center text-slate-600 text-xs mt-16">
        Backend: <code className="text-slate-500">NEXT_PUBLIC_API_URL</code> · Configure tools in{" "}
        <a href="http://localhost:8000/admin/login" className="text-cyan-500/80 hover:underline">
          Admin
        </a>
      </p>
    </div>
  );
}
