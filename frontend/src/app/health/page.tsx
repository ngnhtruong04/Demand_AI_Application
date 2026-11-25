"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { checkBackendHealth, getApiBaseUrl } from "@/lib/api";
import type { HealthCheckResult } from "@/types/health";

export default function Home() {
  const [result, setResult] = useState<HealthCheckResult | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [lastChecked, setLastChecked] = useState<Date | null>(null);

  const fetchHealth = useCallback(async () => {
    setIsLoading(true);
    try {
      const res = await checkBackendHealth();
      setResult(res);
      setLastChecked(new Date());
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    let ignore = false;
    checkBackendHealth().then((res) => {
      if (!ignore) {
        setResult(res);
        setLastChecked(new Date());
        setIsLoading(false);
      }
    });
    return () => {
      ignore = true;
    };
  }, []);

  const apiUrl = getApiBaseUrl();

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col items-center justify-between p-6 sm:p-12 font-sans selection:bg-indigo-500 selection:text-white">
      {/* Background glow effects */}
      <div className="fixed inset-0 pointer-events-none overflow-hidden">
        <div className="absolute -top-40 -left-40 w-96 h-96 bg-indigo-600/15 rounded-full blur-3xl" />
        <div className="absolute top-1/3 -right-40 w-96 h-96 bg-emerald-600/10 rounded-full blur-3xl" />
        <div className="absolute -bottom-40 left-1/3 w-96 h-96 bg-blue-600/10 rounded-full blur-3xl" />
      </div>

      <header className="relative w-full max-w-4xl flex items-center justify-between border-b border-slate-800/80 pb-6 mb-8">
        <div className="flex items-center space-x-3">
          <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-indigo-600 to-violet-500 flex items-center justify-center shadow-lg shadow-indigo-500/20 font-bold text-white text-lg tracking-wider">
            AI
          </div>
          <div>
            <h1 className="text-xl sm:text-2xl font-bold tracking-tight bg-gradient-to-r from-white via-slate-100 to-slate-400 bg-clip-text text-transparent">
              DemandAI Application
            </h1>
            <p className="text-xs text-slate-400">
              Retail Demand Forecasting System & Ingestion Pipeline
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-400 hidden sm:inline-block">
            Environment:
          </span>
          <span className="px-2.5 py-1 text-xs font-semibold rounded-full bg-slate-800 text-slate-300 border border-slate-700">
            Fullstack Refactored
          </span>
        </div>
      </header>

      <main className="relative w-full max-w-4xl flex-1 flex flex-col justify-center items-center py-6">
        <div className="w-full grid grid-cols-1 md:grid-cols-3 gap-6">
          {/* Main Status Panel */}
          <div className="md:col-span-2 bg-slate-900/80 backdrop-blur-xl border border-slate-800 rounded-2xl p-6 sm:p-8 shadow-2xl flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between mb-4">
                <span className="text-xs font-mono uppercase tracking-wider text-slate-400">
                  Backend Connection Status
                </span>

                {isLoading ? (
                  <span
                    id="status-badge"
                    className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium bg-amber-500/10 text-amber-400 border border-amber-500/30"
                  >
                    <span className="w-2 h-2 rounded-full bg-amber-400 animate-ping" />
                    Connecting...
                  </span>
                ) : result?.ok ? (
                  <span
                    id="status-badge"
                    className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/30"
                  >
                    <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
                    Operational (Healthy)
                  </span>
                ) : (
                  <span
                    id="status-badge"
                    className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium bg-rose-500/10 text-rose-400 border border-rose-500/30"
                  >
                    <span className="w-2 h-2 rounded-full bg-rose-400" />
                    Disconnected
                  </span>
                )}
              </div>

              <h2 className="text-2xl sm:text-3xl font-bold tracking-tight text-white mb-2">
                FastAPI Connection Status
              </h2>
              <p className="text-sm text-slate-400 mb-6">
                Next.js frontend directly calls the liveness endpoint{" "}
                <code className="px-1.5 py-0.5 rounded bg-slate-800 text-indigo-300 font-mono text-xs">
                  GET /health
                </code>{" "}
                from the browser via CORS.
              </p>

              {/* Status Details Card */}
              <div className="bg-slate-950/60 rounded-xl p-4 border border-slate-800/80 mb-6 font-mono text-xs space-y-2">
                <div className="flex justify-between items-center py-1 border-b border-slate-800/60">
                  <span className="text-slate-400">Target Endpoint:</span>
                  <span
                    id="api-target-url"
                    className="text-indigo-400 font-semibold truncate max-w-[240px]"
                  >
                    {result?.url || `${apiUrl}/health`}
                  </span>
                </div>
                <div className="flex justify-between items-center py-1 border-b border-slate-800/60">
                  <span className="text-slate-400">Response Time:</span>
                  <span
                    id="response-time"
                    className="text-slate-200 font-semibold"
                  >
                    {result?.responseTimeMs !== undefined
                      ? `${result.responseTimeMs} ms`
                      : "—"}
                  </span>
                </div>
                <div className="flex justify-between items-center py-1 border-b border-slate-800/60">
                  <span className="text-slate-400">Last Checked:</span>
                  <span className="text-slate-200">
                    {lastChecked
                      ? lastChecked.toLocaleTimeString("en-US")
                      : "Not checked"}
                  </span>
                </div>
                <div className="flex justify-between items-center py-1">
                  <span className="text-slate-400">Payload:</span>
                  <span
                    id="health-payload"
                    className={
                      result?.ok ? "text-emerald-400" : "text-rose-400"
                    }
                  >
                    {isLoading
                      ? "Loading..."
                      : result?.ok
                      ? JSON.stringify(result.data)
                      : result?.error || "Unknown error"}
                  </span>
                </div>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-3 pt-4 border-t border-slate-800/60">
              <button
                id="retry-health-btn"
                onClick={fetchHealth}
                disabled={isLoading}
                className="px-5 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-800 disabled:text-slate-600 text-white text-sm font-semibold transition-all duration-200 flex items-center gap-2 shadow-lg shadow-indigo-600/20 active:scale-95 cursor-pointer"
              >
                <svg
                  className={`w-4 h-4 ${isLoading ? "animate-spin" : ""}`}
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
                  />
                </svg>
                {isLoading ? "Checking..." : "Retry Connection"}
              </button>

              <Link
                id="swagger-docs-link"
                href="/docs"
                className="px-4 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white text-sm font-medium transition-colors duration-200 flex items-center gap-2 border border-slate-700"
              >
                <span>API Docs (Swagger UI)</span>
                <svg
                  className="w-3.5 h-3.5 text-slate-400"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"
                  />
                </svg>
              </Link>
            </div>
          </div>

          {/* Architecture Side Card */}
          <div className="bg-slate-900/60 backdrop-blur-xl border border-slate-800 rounded-2xl p-6 flex flex-col justify-between">
            <div>
              <h3 className="text-base font-semibold text-white mb-3 flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full bg-indigo-500" />
                Architecture Overview
              </h3>
              <p className="text-xs text-slate-400 leading-relaxed mb-4">
                Project has been refactored into an independent fullstack architecture:
              </p>
              <ul className="text-xs text-slate-300 space-y-3 font-mono">
                <li className="p-2.5 rounded-lg bg-slate-950/60 border border-slate-800/80">
                  <div className="font-semibold text-indigo-400">frontend/</div>
                  <div className="text-slate-400 text-[11px] mt-0.5">
                    Next.js App Router, Tailwind CSS, TypeScript
                  </div>
                </li>
                <li className="p-2.5 rounded-lg bg-slate-950/60 border border-slate-800/80">
                  <div className="font-semibold text-emerald-400">backend/</div>
                  <div className="text-slate-400 text-[11px] mt-0.5">
                    FastAPI, SQLAlchemy, Alembic, Ingestion Pipeline
                  </div>
                </li>
                <li className="p-2.5 rounded-lg bg-slate-950/60 border border-slate-800/80">
                  <div className="font-semibold text-violet-400">Root CLI</div>
                  <div className="text-slate-400 text-[11px] mt-0.5">
                    Root Makefile & documentation orchestrating both services
                  </div>
                </li>
              </ul>
            </div>

            <div className="mt-6 pt-4 border-t border-slate-800 text-[11px] text-slate-500">
              DemandAI Retail Demand Forecasting Platform
            </div>
          </div>
        </div>
      </main>

      <footer className="relative w-full max-w-4xl text-center text-xs text-slate-500 border-t border-slate-800/80 pt-6 mt-8">
        DemandAI Application &copy; 2026 — Fullstack retail demand forecasting platform.
      </footer>
    </div>
  );
}
