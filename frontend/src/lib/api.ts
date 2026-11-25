export type { HealthStatusResponse, BackendInfoResponse, HealthCheckResult } from "../types/health";
import type { HealthStatusResponse, HealthCheckResult } from "../types/health";

export function getApiBaseUrl(): string {
  if (typeof window !== "undefined" && window.location.hostname) {
    const hostname = window.location.hostname;
    // On loopback (localhost or 127.0.0.1), always use 127.0.0.1
    // This prevents Linux Firefox from resolving 'localhost' to IPv6 [::1] where Uvicorn (0.0.0.0) is not listening
    if (hostname === "localhost" || hostname === "127.0.0.1") {
      return "http://127.0.0.1:8000";
    }
    const envUrl = process.env.NEXT_PUBLIC_API_BASE_URL;
    if (
      envUrl &&
      !envUrl.includes("localhost") &&
      !envUrl.includes("127.0.0.1") &&
      !envUrl.includes("0.0.0.0")
    ) {
      return envUrl.replace(/\/+$/, "");
    }
    return `http://${hostname}:8000`;
  }
  if (typeof process !== "undefined" && process.env.NEXT_PUBLIC_API_BASE_URL) {
    return process.env.NEXT_PUBLIC_API_BASE_URL.replace(/\/+$/, "");
  }
  return "http://127.0.0.1:8000";
}

export async function checkBackendHealth(
  timeoutMs: number = 5000,
  customBaseUrl?: string
): Promise<HealthCheckResult> {
  const baseUrl = customBaseUrl ? customBaseUrl.replace(/\/+$/, "") : getApiBaseUrl();
  const url = `${baseUrl}/health`;
  const startTime = Date.now();

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(url, {
      method: "GET",
      headers: {
        Accept: "application/json",
      },
      signal: controller.signal,
      cache: "no-store",
    });

    const responseTimeMs = Date.now() - startTime;

    if (!response.ok) {
      return {
        ok: false,
        error: `HTTP ${response.status} (${response.statusText || "Error"})`,
        url,
        responseTimeMs,
      };
    }

    let data: unknown;
    try {
      data = await response.json();
    } catch (parseErr: unknown) {
      if (
        controller.signal.aborted ||
        (parseErr instanceof Error && parseErr.name === "AbortError")
      ) {
        throw parseErr;
      }
      return {
        ok: false,
        error: "Response is not valid JSON",
        url,
        responseTimeMs: Date.now() - startTime,
      };
    }

    if (
      data &&
      typeof data === "object" &&
      "status" in data &&
      (data as { status: unknown }).status === "healthy"
    ) {
      return {
        ok: true,
        data: data as HealthStatusResponse,
        url,
        responseTimeMs: Date.now() - startTime,
      };
    }

    return {
      ok: false,
      error: `Invalid response format: ${JSON.stringify(data)}`,
      url,
      responseTimeMs: Date.now() - startTime,
    };
  } catch (err: unknown) {
    const responseTimeMs = Date.now() - startTime;

    if (
      (err instanceof DOMException && err.name === "AbortError") ||
      (err instanceof Error && err.name === "AbortError") ||
      (err instanceof DOMException && err.name === "TimeoutError")
    ) {
      return {
        ok: false,
        error: `Request timed out (${timeoutMs}ms)`,
        url,
        responseTimeMs,
      };
    }

    if (err instanceof TypeError && err.message.includes("fetch")) {
      return {
        ok: false,
        error: `Unable to connect to Backend at ${baseUrl}. Ensure FastAPI is running and CORS is configured.`,
        url,
        responseTimeMs,
      };
    }

    const message = err instanceof Error ? err.message : String(err);
    return {
      ok: false,
      error: `Connection error: ${message}`,
      url,
      responseTimeMs,
    };
  } finally {
    clearTimeout(timeoutId);
  }
}
