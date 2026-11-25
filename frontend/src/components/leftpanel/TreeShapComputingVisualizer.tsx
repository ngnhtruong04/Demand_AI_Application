"use client";

import React from "react";
import type { ForecastedItem } from "@/types/forecast";
import { AlertOctagonIcon } from "../common/Icons";

interface TreeShapComputingVisualizerProps {
  item: ForecastedItem;
  language?: "en" | "vi";
  onRetryShap?: () => void;
  onFastInquiry?: (prompt: string) => void;
}

const SKELETON_SLICES = [
  { strokeDasharray: "135 242", strokeDashoffset: "0", color: "rgba(16, 110, 240, 0.45)" },
  { strokeDasharray: "95 282", strokeDashoffset: "-135", color: "rgba(16, 185, 129, 0.45)" },
  { strokeDasharray: "65 312", strokeDashoffset: "-230", color: "rgba(245, 158, 11, 0.45)" },
  { strokeDasharray: "45 332", strokeDashoffset: "-295", color: "rgba(139, 92, 246, 0.45)" },
  { strokeDasharray: "37 340", strokeDashoffset: "-340", color: "rgba(6, 182, 212, 0.45)" },
];

const SKELETON_DRIVERS = [
  { color: "#106ef0", nameWidth: "58%", pctWidth: "26px", barWidth: "68%" },
  { color: "#4da20c", nameWidth: "48%", pctWidth: "24px", barWidth: "50%" },
  { color: "#f59e0b", nameWidth: "64%", pctWidth: "24px", barWidth: "36%" },
  { color: "#8b5cf6", nameWidth: "42%", pctWidth: "22px", barWidth: "24%" },
  { color: "#06b6d4", nameWidth: "52%", pctWidth: "20px", barWidth: "16%" },
];

export default function TreeShapComputingVisualizer({
  item,
  language = "en",
  onRetryShap,
}: TreeShapComputingVisualizerProps) {
  const isFailed = item.shap_status === "failed";
  const isRunning = item.shap_status === "running";

  if (isFailed) {
    return (
      <div className="breakdown-tab-pane is-skeleton">
        <div className="shap-failed-box">
          <div className="shap-failed-icon"><AlertOctagonIcon size={16} /></div>
          <div className="shap-failed-msg">
            <strong>Forecast Driver Analysis Interrupted</strong>
            <p>{item.shap_error || "Unable to compute forecast drivers for this SKU. Please try again."}</p>
          </div>
          {onRetryShap && (
            <button
              type="button"
              className="shap-retry-cta-btn"
              onClick={onRetryShap}
            >
              Retry Analysis
            </button>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="breakdown-tab-pane is-skeleton">
      {/* 1. Header: Mirror of ForecastBreakdownChart header */}
      <div className="breakdown-chart-header">
        <span className="breakdown-chart-title">Forecast Value Drivers</span>
        <span className="breakdown-chart-badge is-computing">
          <span className="shap-status-spinner-badge mini" />
          <span>
            {item.shap_status === "running"
              ? "Calculating Forecast Drivers…"
              : "Queued in Pipeline…"}
          </span>
        </span>
      </div>

      {/* 2. Donut Chart Skeleton: Mirror of ForecastBreakdownChart SVG */}
      <div className="breakdown-donut-wrapper is-skeleton">
        <svg viewBox="0 0 170 170" className="breakdown-donut-svg is-skeleton">
          <g transform="rotate(-90 85 85)">
            <circle
              cx="85"
              cy="85"
              r="60"
              fill="none"
              stroke="#f1f5f9"
              strokeWidth="20"
              pointerEvents="none"
            />
            {SKELETON_SLICES.map((slice, idx) => (
              <circle
                key={idx}
                cx="85"
                cy="85"
                r="60"
                fill="none"
                stroke={slice.color}
                strokeWidth="20"
                strokeDasharray={slice.strokeDasharray}
                strokeDashoffset={slice.strokeDashoffset}
                className="shap-skeleton-donut-slice"
              />
            ))}
          </g>

          <g pointerEvents="none">
            <text
              x="85"
              y="80"
              textAnchor="middle"
              className="breakdown-donut-center-val is-skeleton"
            >
              --%
            </text>
            <text
              x="85"
              y="96"
              textAnchor="middle"
              className="breakdown-donut-center-lbl is-skeleton"
            >
              {isRunning ? "Traversing Trees" : "Awaiting Worker"}
            </text>
          </g>
        </svg>
      </div>

      {/* 3. Driver List Skeleton: Mirror of ForecastBreakdownChart breakdown-list */}
      <div className="breakdown-list is-skeleton">
        {SKELETON_DRIVERS.map((driver, idx) => (
          <div key={idx} className="breakdown-list-item is-skeleton">
            <div className="breakdown-item-header">
              <div className="breakdown-item-name-box">
                <span
                  className="breakdown-item-dot is-skeleton"
                  style={{ backgroundColor: driver.color }}
                />
                <span
                  className="shap-skeleton-line is-name"
                  style={{ width: driver.nameWidth }}
                />
              </div>
              <span
                className="shap-skeleton-line is-pct"
                style={{ width: driver.pctWidth }}
              />
            </div>

            <div className="breakdown-item-track">
              <div
                className="breakdown-item-bar is-skeleton"
                style={{
                  width: driver.barWidth,
                  backgroundColor: driver.color,
                }}
              >
                <div className="shap-bar-glimmer" />
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* 4. Subtle computation status footnote */}
      <div className="shap-skeleton-footnote">
        <span className="shap-status-beacon" />
        <span>139 features across LightGBM, XGBoost & CatBoost</span>
      </div>
    </div>
  );
}

