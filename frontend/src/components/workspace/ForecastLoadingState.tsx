"use client";

import { useState, useEffect, useRef } from "react";
import { Sparkle } from "../common/Icons";
import { getApiBaseUrl } from "@/lib/api";
import type { ForecastedItem } from "@/types/forecast";
import { fetchLiveForecast, requestForecastJob, FORECAST_SESSION_KEY, type ForecastJob } from "@/lib/forecastApi";

interface ForecastLoadingStateProps {
  onComplete?: (items: ForecastedItem[]) => void;
}

const INITIAL_STEPS: ForecastJob["steps"] = [
  "Fetch Data", "Feature Engineering", "Recursive Ensemble Forecast", "Inventory Analysis & Save",
].map((title, i) => ({ id: i + 1, title, status: "pending", message: "Waiting" }));

function generateSafeUUID(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

export default function ForecastLoadingState({ onComplete }: ForecastLoadingStateProps) {
  const [job, setJob] = useState<ForecastJob | null>(null);
  const [currentLog, setCurrentLog] = useState("Starting forecast job...");
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const onCompleteRef = useRef(onComplete);
  useEffect(() => { onCompleteRef.current = onComplete; }, [onComplete]);

  useEffect(() => {
    let es: EventSource | null = null;
    let disposed = false;
    let terminal = false;
    let sequence = -1;
    let pollTimer: ReturnType<typeof setTimeout> | undefined;
    const controller = new AbortController();

    const fail = (cause: unknown) => {
      if (disposed) return;
      terminal = true;
      es?.close();
      clearTimeout(pollTimer);
      setError(cause instanceof Error ? cause.message : String(cause));
    };
    const accept = (snapshot: ForecastJob) => {
      if (disposed || terminal || snapshot.sequence <= sequence) return;
      sequence = snapshot.sequence;
      setJob(snapshot);
      const active = snapshot.steps.find(step => step.status === "running" || step.status === "failed");
      if (active) setCurrentLog(active.message);
      if (snapshot.status === "failed") {
        sessionStorage.removeItem(FORECAST_SESSION_KEY);
        fail(new Error(`${active?.title || "Forecast"}: ${snapshot.error || active?.message || "Pipeline failed."}`));
      } else if (snapshot.status === "completed") {
        if (!snapshot.run_id || snapshot.steps.some(step => step.status !== "completed")) {
          fail(new Error("Backend reported completion without all stages and saved results."));
          return;
        }
        terminal = true;
        es?.close();
        clearTimeout(pollTimer);
        setCurrentLog("Loading saved forecast results...");
        fetchLiveForecast(undefined, controller.signal, (loaded, total) => {
          if (!disposed) setCurrentLog(`Loading forecast results: ${loaded.toLocaleString()} / ${total.toLocaleString()} items...`);
        }, snapshot.run_id).then(items => {
          if (disposed) return;
          sessionStorage.removeItem(FORECAST_SESSION_KEY);
          onCompleteRef.current?.(items);
        }).catch(fail);
      }
    };

    async function connect() {
      try {
        const saved = sessionStorage.getItem(FORECAST_SESSION_KEY);
        const session: { requestId: string; jobId?: string } = saved ? JSON.parse(saved) : { requestId: generateSafeUUID() };
        sessionStorage.setItem(FORECAST_SESSION_KEY, JSON.stringify(session));
        const initial = await requestForecastJob(
          session.jobId ? `runs/${session.jobId}` : "runs", controller.signal,
          session.jobId ? undefined : session.requestId,
        );
        if (disposed) return;
        session.jobId = initial.job_id;
        sessionStorage.setItem(FORECAST_SESSION_KEY, JSON.stringify(session));
        accept(initial);
        if (terminal) return;
        const path = `runs/${initial.job_id}`;
        es = new EventSource(`${getApiBaseUrl()}/api/v1/forecast/${path}/events`);
        es.onmessage = event => {
          try { accept(JSON.parse(event.data)); } catch (cause) { fail(cause); }
        };
        es.onerror = () => {
          if (!disposed && !terminal) setCurrentLog("Reconnecting to forecast progress...");
          // EventSource reconnects to this same job; polling also recovers final status.
        };
        let failures = 0;
        const poll = async () => {
          if (disposed || terminal) return;
          try {
            accept(await requestForecastJob(path, controller.signal));
            failures = 0;
          } catch (cause) {
            if (++failures >= 3) { fail(cause); return; }
          }
          if (!disposed && !terminal) pollTimer = setTimeout(poll, 5000);
        };
        pollTimer = setTimeout(poll, 5000);
      } catch (cause) {
        if (cause instanceof SyntaxError) sessionStorage.removeItem(FORECAST_SESSION_KEY);
        fail(cause);
      }
    }
    void connect();
    return () => {
      disposed = true;
      es?.close();
      clearTimeout(pollTimer);
      controller.abort();
    };
  }, [attempt]);

  const steps = job?.steps || INITIAL_STEPS;
  const completed = steps.filter(step => step.status === "completed").length;
  const pipelineComplete = job?.status === "completed" && completed === 4 && !!job.run_id;
  const progressPct = pipelineComplete ? 100 : (job?.progress !== undefined ? job.progress : completed * 25);
  return (
    <div className="forecast-loading-container" aria-busy={!error}>
      <div className="loading-hero">
        <div className="loading-pulse-ring"><div className="loading-icon-core"><Sparkle size={26} /></div></div>
        <h3 className="loading-title">{error ? (pipelineComplete ? "Unable to load forecast results" : "Forecast could not finish") : pipelineComplete ? "Loading forecast results..." : "Running 14-day demand forecast..."}</h3>
        <p className="loading-subtitle">Progress reflects backend execution. Each stage completes only after its work succeeds.</p>
        <div className="loading-progress-track-horizontal" role="progressbar" aria-valuenow={Math.round(progressPct)} aria-valuemin={0} aria-valuemax={100} aria-label="Completed pipeline stages" aria-valuetext={`${Math.round(progressPct)}% complete · ${completed} of 4 stages completed`}>
          <div className="loading-progress-bar-horizontal" style={{ width: `${progressPct}%` }} />
        </div>
        <p className="loading-status-text" role="status">{currentLog}</p>
        {error && <div role="alert">
          <p style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{error}</p>
          <button className="run-forecast-cta" type="button" onClick={() => {
            setError(null); setJob(null); setCurrentLog("Connecting to forecast job..."); setAttempt(value => value + 1);
          }}>Try again</button>
        </div>}
      </div>
      <div className="loading-pipeline-card">
        <div className="pipeline-card-header">
          <span className="pipeline-card-title">DATA PIPELINE &amp; FORECAST EXECUTION</span>
          <span className="pipeline-phase-badge">{pipelineComplete ? "✓ Forecast ready · SHAP on demand" : job?.status === "failed" ? "Pipeline failed" : `${completed}/4 stages completed`}</span>
        </div>
        <div className="horizontal-steps-row">
          {steps.map(step => (
            <div key={step.id} className={`horizontal-step-node ${step.status === "completed" ? "is-completed" : step.status === "running" ? "is-current" : ""}`}>
              <div className="step-node-header">
                <div className={`step-node-badge ${step.status === "completed" ? "is-completed" : step.status === "running" ? "is-current" : "is-pending"}`}>
                  {step.status === "completed" ? "✓" : step.status === "failed" ? "!" : step.status === "running" ? <span className="spinner-mini" /> : step.id}
                </div>
                <span className={`step-node-status-pill ${step.status === "completed" ? "pill-done" : step.status === "running" ? "pill-running" : "pill-pending"}`} style={step.status === "failed" ? { color: "#b91c1c", background: "#fee2e2" } : undefined}>{step.status}</span>
              </div>
              <div className="step-node-body">
                <h4 className="step-node-title-vi">{step.id}. {step.title}</h4>
                <p className="step-node-desc">{step.message}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
