import type { ForecastedItem } from "@/types/forecast";
import { getApiBaseUrl } from "./api";

export const FORECAST_TIMEOUT_MS = 30_000;
const FORECAST_PAGE_SIZE = 500;

interface ForecastPage {
  items: ForecastedItem[];
  total_items: number;
  run_id?: string;
}

/** The timeout covers both response headers and the entire response body. */
async function fetchForecastPage(
  offset: number,
  timeoutMs: number,
  signal?: AbortSignal,
  snapshot?: ForecastPage,
  runId?: string,
): Promise<ForecastPage> {
  const pinnedRun = runId || snapshot?.run_id;
  const sourceQuery = pinnedRun
    ? `&source=database&run_id=${encodeURIComponent(pinnedRun)}`
    : !snapshot ? ""
    : "&source=cache";
  const url = `${getApiBaseUrl()}/api/v1/forecast/get_forecast_14d?unique_id=all&limit=${FORECAST_PAGE_SIZE}&offset=${offset}${sourceQuery}`;
  const controller = new AbortController();
  let timedOut = false;
  const cancel = () => controller.abort();
  signal?.addEventListener("abort", cancel, { once: true });
  if (signal?.aborted) cancel();
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);

  try {
    const res = await fetch(url, {
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal: controller.signal,
    });
    const body = await res.text();
    let data;
    try {
      data = JSON.parse(body);
    } catch {
      throw new Error(res.ok
        ? "Backend returned invalid JSON."
        : `HTTP ${res.status} ${res.statusText}: ${body.slice(0, 1000)}`);
    }
    if (!res.ok || data?.status === "error") {
      const detail = data?.detail ?? data?.message ?? res.statusText;
      throw new Error(`HTTP ${res.status}: ${typeof detail === "string" ? detail : JSON.stringify(detail)}`);
    }
    if (!data || !Array.isArray(data.items)) {
      throw new Error("Invalid forecast response: missing items array.");
    }
    if (data.items.length === 0) {
      throw new Error("Backend returned no forecast items.");
    }
    if (!Number.isSafeInteger(data.total_items) || data.total_items < offset + data.items.length
        || data.items.length > FORECAST_PAGE_SIZE) {
      throw new Error("Invalid forecast pagination metadata.");
    }
    return data as ForecastPage;
  } catch (error) {
    const message = timedOut
      ? `Forecast request timed out after ${timeoutMs / 1000} seconds.`
      : error instanceof Error ? error.message : String(error);
    throw new Error(`${message}\nGET ${url}`);
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", cancel);
  }
}

/** Load bounded pages while preserving global search and sorting in the table. */
export async function fetchLiveForecast(
  timeoutMs = FORECAST_TIMEOUT_MS,
  signal?: AbortSignal,
  onProgress?: (loaded: number, total: number) => void,
  runId?: string,
): Promise<ForecastedItem[]> {
  const items: ForecastedItem[] = [];
  const ids = new Set<string>();
  let firstPage: ForecastPage | undefined;
  do {
    signal?.throwIfAborted();
    const page = await fetchForecastPage(items.length, timeoutMs, signal, firstPage, runId);
    if (runId && page.run_id !== runId) throw new Error("Backend returned a different forecast run.");
    if (firstPage && (page.total_items !== firstPage.total_items || page.run_id !== firstPage.run_id)) {
      throw new Error("Forecast data changed while loading. Please try again.");
    }
    firstPage ??= page;
    for (const item of page.items) {
      if (ids.has(item.id)) {
        throw new Error("Backend returned overlapping forecast pages. Please try again.");
      }
      ids.add(item.id);
      items.push({ ...item, run_id: page.run_id });
    }
    onProgress?.(items.length, firstPage.total_items);
  } while (items.length < firstPage.total_items);
  return items;
}

export interface ForecastJob {
  job_id: string;
  status: "queued" | "running" | "completed" | "failed";
  run_id: string | null;
  error: string | null;
  sequence: number;
  progress?: number;
  steps: { id: number; title: string; status: "pending" | "running" | "completed" | "failed"; message: string }[];
}

export const FORECAST_SESSION_KEY = "demandai.forecastJob";

export async function requestForecastJob(path: string, signal: AbortSignal, requestId?: string): Promise<ForecastJob> {
  const url = `${getApiBaseUrl()}/api/v1/forecast/${path}`;
  const response = await fetch(url, {
    method: requestId ? "POST" : "GET",
    headers: { "Content-Type": "application/json" },
    body: requestId ? JSON.stringify({ request_id: requestId }) : undefined,
    signal: AbortSignal.any([signal, AbortSignal.timeout(FORECAST_TIMEOUT_MS)]),
    cache: "no-store",
  });
  const data = await response.json();
  if (!response.ok) {
    if (response.status === 404) sessionStorage.removeItem(FORECAST_SESSION_KEY);
    throw new Error(`HTTP ${response.status}: ${data.detail || response.statusText}\n${url}`);
  }
  if (!data.job_id || !Array.isArray(data.steps)) throw new Error("Invalid forecast job response.");
  return data as ForecastJob;
}

export type ShapStatus = "not_requested" | "queued" | "running" | "completed" | "failed";
export interface ItemShapResponse {
  status: ShapStatus;
  run_id: string;
  item_id: string;
  item?: ForecastedItem;
  error?: string;
  active_item_id?: string | null;
  queued_item_ids?: string[];
  completed_item_ids?: string[];
}

export async function loadItemShap(
  runId: string, itemId: string, signal: AbortSignal,
  onStatus: (status: ShapStatus, queuedIds?: string[], activeId?: string | null, completedIds?: string[]) => void,
): Promise<ForecastedItem> {
  const url = `${getApiBaseUrl()}/api/v1/forecast/runs/${encodeURIComponent(runId)}/items/${encodeURIComponent(itemId)}/shap`;
  let method = "POST";
  while (true) {
    signal.throwIfAborted();
    const response = await fetch(url, { method, cache: "no-store",
      signal: AbortSignal.any([signal, AbortSignal.timeout(FORECAST_TIMEOUT_MS)]),
    });
    const data = await response.json() as ItemShapResponse & { detail?: string };
    if (!response.ok) throw new Error(`HTTP ${response.status}: ${data.detail || response.statusText}`);
    if (data.run_id !== runId || data.item_id !== itemId) throw new Error("SHAP response belongs to a different forecast item.");
    onStatus(data.status, data.queued_item_ids, data.active_item_id, data.completed_item_ids);
    if (data.status === "failed") throw new Error(data.error || "SHAP calculation failed.");
    if (data.status === "completed") {
      if (!data.item || data.item.id !== itemId) throw new Error("SHAP response is missing the selected item.");
      return { ...data.item, run_id: runId, shap_status: "completed" };
    }
    if (!["not_requested", "queued", "running"].includes(data.status)) throw new Error("Invalid SHAP job status.");
    method = data.status === "not_requested" ? "POST" : "GET";
    await new Promise<void>((resolve, reject) => {
      const cancel = () => { clearTimeout(timer); reject(signal.reason); };
      const timer = setTimeout(() => { signal.removeEventListener("abort", cancel); resolve(); }, 400);
      signal.addEventListener("abort", cancel, { once: true });
      if (signal.aborted) { signal.removeEventListener("abort", cancel); cancel(); }
    });
  }
}

export async function fetchShapStatus(runId: string, itemId: string): Promise<ItemShapResponse> {
  const url = `${getApiBaseUrl()}/api/v1/forecast/runs/${encodeURIComponent(runId)}/items/${encodeURIComponent(itemId)}/shap`;
  const response = await fetch(url, { method: "GET", cache: "no-store" });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return (await response.json()) as ItemShapResponse;
}

