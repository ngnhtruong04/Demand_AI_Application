"use client";

import React, { useState, useEffect, useRef } from "react";
import Link from "next/link";
import DemandAIHeader from "@/components/DemandAIHeader";
import { getApiBaseUrl, checkBackendHealth } from "@/lib/api";
import fallbackSchema from "@/lib/openapi-fallback.json";
import "@/styles/demand-ai.css";
import "swagger-ui-dist/swagger-ui.css";

interface SwaggerUiInstance {
  layoutActions?: {
    updateFilter?: (val: string) => void;
    show?: (thing: string[], shown?: boolean) => void;
  };
  getSystem?: () => {
    layoutActions?: {
      updateFilter?: (val: string) => void;
    };
  };
}

interface CustomWindow extends Window {
  swaggerUi?: SwaggerUiInstance;
}

export default function ApiManagementPage() {
  const [targetUrl, setTargetUrl] = useState<string>(() =>
    typeof window !== "undefined" ? getApiBaseUrl() : "http://127.0.0.1:8000"
  );
  const [customUrlInput, setCustomUrlInput] = useState<string>(() =>
    typeof window !== "undefined" ? getApiBaseUrl() : "http://127.0.0.1:8000"
  );
  const [isLive, setIsLive] = useState<boolean>(false);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [healthInfo, setHealthInfo] = useState<{ status: string; latency?: number; error?: string } | null>(null);
  const [reloadKey, setReloadKey] = useState<number>(0);
  const [activeFilter, setActiveFilter] = useState<string>("all");
  const swaggerUiRef = useRef<SwaggerUiInstance | null>(null);
  const activeFilterRef = useRef<string>(activeFilter);

  useEffect(() => {
    activeFilterRef.current = activeFilter;
  }, [activeFilter]);

  // Check health of the selected targetUrl asynchronously
  useEffect(() => {
    let cancelled = false;
    if (!targetUrl) return;

    async function runCheck() {
      const start = Date.now();
      try {
        const res = await checkBackendHealth(2500, targetUrl);
        if (cancelled) return;
        const latency = Date.now() - start;
        if (res.ok) {
          setIsLive(true);
          setHealthInfo({ status: "Operational", latency });
        } else {
          setIsLive(false);
          setHealthInfo({ status: "Offline", error: res.error });
        }
      } catch (err) {
        if (cancelled) return;
        setIsLive(false);
        setHealthInfo({ status: "Offline", error: String(err) });
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }

    runCheck();
    return () => {
      cancelled = true;
    };
  }, [targetUrl, reloadKey]);

  // Initialize Swagger UI instance
  useEffect(() => {
    if (!targetUrl) return;

    let isMounted = true;
    let originalError: typeof console.error | null = null;

    async function loadSwagger() {
      try {
        const { SwaggerUIBundle, SwaggerUIStandalonePreset } = await import("swagger-ui-dist");
        if (!isMounted) return;

        // Suppress Swagger UI internal false-positive deprecation warning for deep-link hash underscores
        if (!originalError) {
          originalError = console.error;
          console.error = (...args: unknown[]) => {
            if (
              typeof args[0] === "string" &&
              args[0].includes("escaping deep link whitespace with ")
            ) {
              return;
            }
            originalError?.apply(console, args);
          };
        }

        // Try fetching live openapi.json from targetUrl first
        let specToUse: unknown = null;
        let useDirectUrl = false;

        try {
          const controller = new AbortController();
          const timer = setTimeout(() => controller.abort(), 2000);
          const response = await fetch(`${targetUrl}/openapi.json`, { signal: controller.signal });
          clearTimeout(timer);
          if (response.ok) {
            useDirectUrl = true;
          }
        } catch {
          useDirectUrl = false;
        }

        if (!useDirectUrl) {
          specToUse = fallbackSchema;
        }

        const config: Record<string, unknown> = {
          dom_id: "#swagger-ui-mount",
          deepLinking: true,
          presets: [
            SwaggerUIBundle.presets.apis,
            SwaggerUIStandalonePreset,
          ],
          layout: "BaseLayout",
          displayRequestDuration: true,
          docExpansion: "none",
          filter: true,
          showExtensions: false,
          showCommonExtensions: false,
          defaultModelsExpandDepth: 0,
          defaultModelExpandDepth: 0,
        };

        if (useDirectUrl) {
          config.url = `${targetUrl}/openapi.json`;
        } else {
          config.spec = specToUse;
        }

        const uiInstance = SwaggerUIBundle(config) as SwaggerUiInstance;
        swaggerUiRef.current = uiInstance;
        if (typeof window !== "undefined") {
          (window as unknown as CustomWindow).swaggerUi = uiInstance;
        }

        // Re-apply filter if user already selected a category
        if (activeFilterRef.current !== "all") {
          try {
            uiInstance.layoutActions?.updateFilter?.(activeFilterRef.current);
          } catch (e) {
            console.warn("Initial Swagger filter apply failed:", e);
          }
        }
      } catch (err) {
        console.error("Error mounting Swagger UI:", err);
      }
    }

    loadSwagger();

    return () => {
      isMounted = false;
      if (originalError) {
        console.error = originalError;
      }
    };
  }, [targetUrl, reloadKey]);

  function handleSwitchTarget(newUrl: string) {
    setTargetUrl(newUrl);
    setCustomUrlInput(newUrl);
    setIsLoading(true);
    setReloadKey((prev) => prev + 1);
  }

  function handleCustomSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (customUrlInput.trim()) {
      let formatted = customUrlInput.trim();
      if (!formatted.startsWith("http://") && !formatted.startsWith("https://")) {
        formatted = `http://${formatted}`;
      }
      handleSwitchTarget(formatted);
    }
  }

  function handleFilterChange(tagName: string) {
    setActiveFilter(tagName);
    const filterQuery = tagName === "all" ? "" : tagName;

    // 1. Direct Redux action in Swagger UI system
    try {
      const ui =
        swaggerUiRef.current ||
        (typeof window !== "undefined" ? (window as unknown as CustomWindow).swaggerUi : undefined);
      if (ui?.layoutActions?.updateFilter) {
        ui.layoutActions.updateFilter(filterQuery);
      } else if (ui?.getSystem?.()?.layoutActions?.updateFilter) {
        ui.getSystem?.()?.layoutActions?.updateFilter?.(filterQuery);
      }
    } catch (e) {
      console.warn("Direct Swagger UI filter update failed:", e);
    }

    // 2. Also update DOM search input using React native value setter
    if (typeof document !== "undefined") {
      const searchInput = document.querySelector(
        ".swagger-ui .operation-filter-input"
      ) as HTMLInputElement | null;
      if (searchInput) {
        const nativeSetter = Object.getOwnPropertyDescriptor(
          window.HTMLInputElement.prototype,
          "value"
        )?.set;
        if (nativeSetter) {
          nativeSetter.call(searchInput, filterQuery);
        } else {
          searchInput.value = filterQuery;
        }
        searchInput.dispatchEvent(new Event("input", { bubbles: true }));
        searchInput.dispatchEvent(new Event("change", { bubbles: true }));
      }

      // 3. Auto-expand filtered tag sections if collapsed so endpoints are visible
      if (filterQuery) {
        setTimeout(() => {
          const tagSections = document.querySelectorAll(
            ".swagger-ui .opblock-tag-section"
          );
          tagSections.forEach((section) => {
            const btn = section.querySelector("h3 button, h4 button");
            if (btn && !section.classList.contains("is-open")) {
              (btn as HTMLElement).click();
            }
          });
        }, 120);
      }
    }
  }

  const tags = [
    { name: "all", label: "All Endpoints (27)" },
    { name: "forecast", label: "Demand Forecasting (14)" },
    { name: "chat", label: "AI Assistant (4)" },
    { name: "wiki", label: "Inventory Wiki (4)" },
    { name: "feature-engineering", label: "Feature Store (2)" },
    { name: "pipeline", label: "ETL Pipeline (1)" },
    { name: "health", label: "Database Health (1)" },
    { name: "system", label: "System Probes (2)" },
  ];

  return (
    <div className="api-management-shell">
      <DemandAIHeader />

      <main className="api-management-main">
        {/* Top Header Banner */}
        <section className="api-header-banner">
          <div className="api-banner-content">
            <div className="api-breadcrumbs">
              <Link href="/" className="api-breadcrumb-link">Home</Link>
              <span className="api-breadcrumb-sep">/</span>
              <span className="api-breadcrumb-current">API Management</span>
            </div>
            <h1 className="api-page-title">FastAPI Service Management &amp; Swagger Docs</h1>
            <p className="api-page-subtitle">
              Interactive OpenAPI documentation, schema inspector, and live request sandbox for DemandAI retail demand forecasting platform.
            </p>
          </div>

          {/* Target URL and Status Panel */}
          <div className="api-control-panel">
            <div className="api-control-top">
              <div className="api-status-badge-wrap">
                <span className={`api-status-dot ${isLive ? "is-live" : isLoading ? "is-loading" : "is-offline"}`} />
                <span className="api-status-text">
                  {isLoading
                    ? "Verifying Connection..."
                    : isLive
                    ? "FastAPI Online (Live Mode)"
                    : "FastAPI Offline (Fallback Mode)"}
                </span>
                {healthInfo?.latency !== undefined && (
                  <span className="api-latency-chip">{healthInfo.latency}ms</span>
                )}
              </div>

              <div className="api-quick-links">
                <a
                  href={`${targetUrl || "http://127.0.0.1:8000"}/openapi.json`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="api-secondary-link"
                  title="Download or inspect raw OpenAPI 3.1 JSON schema"
                >
                  raw openapi.json ↗
                </a>
                <a
                  href={`${targetUrl || "http://127.0.0.1:8000"}/redoc`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="api-secondary-link"
                  title="View ReDoc alternative documentation"
                >
                  ReDoc ↗
                </a>
                <button
                  type="button"
                  onClick={() => {
                    setIsLoading(true);
                    setReloadKey((prev) => prev + 1);
                  }}
                  className="api-reload-btn"
                  title="Reload schema and re-run connection probe"
                >
                  ↻ Refresh
                </button>
              </div>
            </div>

            {/* Target URL Selector */}
            <form onSubmit={handleCustomSubmit} className="api-url-form">
              <label htmlFor="target-url-input" className="api-url-label">
                Backend Server:
              </label>
              <div className="api-url-input-wrap">
                <input
                  id="target-url-input"
                  type="text"
                  className="api-url-input"
                  value={customUrlInput}
                  onChange={(e) => setCustomUrlInput(e.target.value)}
                  placeholder="http://127.0.0.1:8000"
                />
                <button type="submit" className="api-url-apply-btn">
                  Connect
                </button>
              </div>

              {/* Preset quick buttons */}
              <div className="api-url-presets">
                <span className="api-preset-label">Presets:</span>
                <button
                  type="button"
                  className={`api-preset-btn ${targetUrl === "http://127.0.0.1:8000" ? "is-active" : ""}`}
                  onClick={() => handleSwitchTarget("http://127.0.0.1:8000")}
                >
                  127.0.0.1:8000
                </button>
                <button
                  type="button"
                  className={`api-preset-btn ${targetUrl === "http://localhost:8000" ? "is-active" : ""}`}
                  onClick={() => handleSwitchTarget("http://localhost:8000")}
                >
                  localhost:8000
                </button>
              </div>
            </form>

            {!isLive && !isLoading && (
              <div className="api-offline-banner" role="alert">
                <span className="api-offline-icon">ℹ</span>
                <span>
                  <strong>Offline Fallback Active:</strong> FastAPI is currently not reachable at <code>{targetUrl}</code>.
                  Showing cached OpenAPI 3.1 specifications. Start the backend with <code>make dev-backend</code> to enable live &quot;Try it out&quot; requests.
                </span>
              </div>
            )}
          </div>
        </section>

        {/* API Tag Navigation Pills */}
        <section className="api-tags-nav" aria-label="API Endpoint Categories">
          <div className="api-tags-scroll">
            {tags.map((tag) => (
              <button
                key={tag.name}
                type="button"
                className={`api-tag-pill ${activeFilter === tag.name ? "is-active" : ""}`}
                onClick={() => handleFilterChange(tag.name)}
              >
                {tag.label}
              </button>
            ))}
          </div>
        </section>

        {/* Swagger UI Mount Container */}
        <section className="api-swagger-card">
          <div id="swagger-ui-mount" className="swagger-ui-wrapper" />
        </section>
      </main>

      <footer className="api-management-footer">
        <span>DemandAI Platform &copy; 2026 &bull; FastAPI + OpenAPI 3.1 + Swagger UI</span>
        <div className="api-footer-links">
          <Link href="/health" className="api-footer-link">System Status</Link>
          <span className="api-footer-sep">&bull;</span>
          <Link href="/" className="api-footer-link">Forecast Workspace</Link>
        </div>
      </footer>
    </div>
  );
}
