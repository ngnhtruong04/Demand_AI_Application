import React from "react";
import type { ForecastedItem, ForecastState } from "@/types/forecast";
import { PlayIcon, Sparkle } from "../common/Icons";
import ForecastTable from "./ForecastTable";
import ForecastLoadingState from "./ForecastLoadingState";

interface WorkspaceCanvasProps {
  forecastState?: ForecastState;
  forecastItems?: ForecastedItem[];
  onRunForecast?: () => void;
  onRerunForecast?: () => void;
  onForecastComplete?: (items: ForecastedItem[]) => void;
  onOpenAssistant?: () => void;
  selectedItemId?: string | null;
  onSelectItem?: (item: ForecastedItem) => void;
  isRestoringSession?: boolean;
  restoringMessage?: string;
}

export default function WorkspaceCanvas({
  forecastState = "idle",
  forecastItems = [],
  onRunForecast = () => {},
  onRerunForecast,
  onForecastComplete,
  selectedItemId,
  onSelectItem,
  isRestoringSession = false,
  restoringMessage,
}: WorkspaceCanvasProps) {
  return (
    <main className="workspace-main">
      {/* Workspace Canvas: Branch based on forecastState */}
      <section
        className={`workspace-canvas ${forecastState === "completed" ? "has-table" : ""}`}
        aria-label="Forecast workspace canvas"
      >
        {isRestoringSession ? (
          <div className="forecast-loading-container" aria-busy="true">
            <div className="loading-hero">
              <div className="loading-pulse-ring">
                <div className="loading-icon-core">
                  <Sparkle size={26} />
                </div>
              </div>
              <h3 className="loading-title">Restoring forecast session...</h3>
              <p className="loading-subtitle">
                Active session detected. Loading saved forecast results directly without rerunning pipeline.
              </p>
              <p className="loading-status-text" role="status">
                {restoringMessage || "Loading forecast items..."}
              </p>
            </div>
          </div>
        ) : forecastState === "loading" ? (
          <ForecastLoadingState onComplete={onForecastComplete} />
        ) : forecastState === "completed" ? (
          <ForecastTable
            items={forecastItems}
            onRerunForecast={onRerunForecast || onRunForecast}
            isRerunning={false}
            selectedItemId={selectedItemId}
            onSelectItem={onSelectItem}
          />
        ) : (
          /* Idle state: Minimalist, clean and centered hero launchpad */
          <div className="canvas-empty canvas-launchpad">
            {/* Luminous Brand Icon Hero */}
            <div className="launchpad-hero-wrap" aria-hidden="true">
              <div className="launchpad-glow-halo" />
              <div className="launchpad-icon-card">
                <img
                  src="/icon.svg"
                  alt="Demand AI Icon"
                  width={68}
                  height={68}
                  className="launchpad-icon-img"
                />
              </div>
            </div>

            {/* Title */}
            <h2 id="canvas-title" className="launchpad-title">
              Enterprise Demand &amp; Inventory Intelligence
            </h2>

            {/* Primary Call to Action */}
            <div className="launchpad-cta-wrapper">
              <button
                type="button"
                id="run-forecast-hero-btn"
                className="run-forecast-cta launchpad-run-btn"
                onClick={onRunForecast}
              >
                <PlayIcon size={16} />
                <span>Run 14-Day Forecast</span>
              </button>
            </div>
          </div>
        )}
      </section>
    </main>
  );
}
