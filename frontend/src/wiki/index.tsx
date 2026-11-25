"use client";

import React, { useState, useRef, useEffect, useId } from "react";
import { createPortal } from "react-dom";
import statusData from "./status.json";
import metricsData from "./metrics.json";

export interface WikiEntry {
  title: string;
  tag?: string;
  summary: string;
  calculation: string;
  details?: string;
  action?: string;
  color?: string;
  badgeClass?: string;
  urgency?: string;
}

const ALIAS_MAP: Record<string, string> = {
  forecast14d: "forecast",
  "14d forecast": "forecast",
  "total 14d forecasted": "forecast",
  forecast_14d: "forecast",
  onhandstock: "stock",
  "on-hand stock": "stock",
  on_hand_stock: "stock",
  reorderpoint: "reorderPoint",
  "reorder point": "reorderPoint",
  reorder_point: "reorderPoint",
  rop: "reorderPoint",
  safetystock: "safetyStock",
  "safety stock": "safetyStock",
  safety_stock: "safetyStock",
  daysofsupply: "daysOfSupply",
  "days of supply": "daysOfSupply",
  days_of_supply: "daysOfSupply",
  dayofsupply: "daysOfSupply",
  "day of supply": "daysOfSupply",
  day_of_supply: "daysOfSupply",
  dos: "daysOfSupply",
  breakdown: "breakdown",
  breakdown_list: "breakdown",
  "breakdown list": "breakdown",
  "breakdown-list": "breakdown",
  breakdownlist: "breakdown",
  forecast_breakdown: "breakdown",
  "forecast breakdown": "breakdown",
  value_drivers: "breakdown",
  "value drivers": "breakdown",
  shap: "shap_mirror",
  shap_mirror: "shap_mirror",
  "shap mirror": "shap_mirror",
  "shap-mirror": "shap_mirror",
  shapmirror: "shap_mirror",
  tree_shap: "shap_mirror",
  "tree shap": "shap_mirror",
  "tree-shap": "shap_mirror",
  treeshap: "shap_mirror",
  "forecast drivers": "shap_mirror",
  "forecast_drivers": "shap_mirror",
  forecastdrivers: "shap_mirror",
  "yếu tố ảnh hưởng dự báo": "shap_mirror",
  "yeu to anh huong du bao": "shap_mirror",
  status: "status_overview",
  statuses: "status_overview",
  base_value: "shap_base_value",
  shap_base_value: "shap_base_value",
  "base value": "shap_base_value",
  sales_1: "sales_lag_1",
  sales_lag_1: "sales_lag_1",
  "sales lag 1": "sales_lag_1",
  sales_7: "sales_lag_7",
  sales_lag_7: "sales_lag_7",
  "sales lag 7": "sales_lag_7",
  sales_14: "sales_lag_14",
  sales_lag_14: "sales_lag_14",
  "sales lag 14": "sales_lag_14",
  sales_order_interaction: "sales_order_interaction",
  sales_order_lag: "sales_order_interaction",
  sales_price_interaction: "sales_price_interaction",
  sales_price_lag: "sales_price_interaction",
  sales_summary_stats: "sales_summary_stats",
  sales_stats: "sales_summary_stats",
  max_discount: "max_discount",
  "max discount": "max_discount",
  discounted_price: "discounted_price",
  "discounted price": "discounted_price",
  discount_lags: "discount_lags",
  "discount lags": "discount_lags",
  discount_lag: "discount_lags",
  weekday: "weekday",
  "day of week": "weekday",
  sin_cos_dayofyear: "sin_cos_dayofyear",
  seasonality: "sin_cos_dayofyear",
  total_orders: "total_orders",
  "total orders": "total_orders",
};

export function getWikiEntry(key: string): WikiEntry | null {
  if (!key) return null;
  const trimmed = key.trim();

  // 1. Direct status lookup from status.json
  const statuses = statusData.statuses as Record<string, {
    name: string;
    badgeClass: string;
    summary: string;
    calculation: string;
    details: string;
    action: string;
    color: string;
    urgency: string;
  }>;

  if (statuses[trimmed]) {
    const s = statuses[trimmed];
    return {
      title: s.name,
      tag: s.urgency,
      summary: s.summary,
      calculation: s.calculation,
      details: s.details,
      action: s.action,
      color: s.color,
      badgeClass: s.badgeClass,
      urgency: s.urgency,
    };
  }

  // Case-insensitive status match
  const statusKeyMatch = Object.keys(statuses).find(
    (k) => k.toLowerCase() === trimmed.toLowerCase()
  );
  if (statusKeyMatch) {
    const s = statuses[statusKeyMatch];
    return {
      title: s.name,
      tag: s.urgency,
      summary: s.summary,
      calculation: s.calculation,
      details: s.details,
      action: s.action,
      color: s.color,
      badgeClass: s.badgeClass,
      urgency: s.urgency,
    };
  }

  // 2. Metrics lookup
  const resolvedMetricKey = ALIAS_MAP[trimmed.toLowerCase()] || trimmed;
  const metrics = metricsData.metrics as Record<string, WikiEntry>;

  if (metrics[resolvedMetricKey]) {
    return metrics[resolvedMetricKey];
  }

  return null;
}

const DISABLE_WIKI_HOVER = true; // ponytail: set to false to re-enable wiki hover tooltips

interface WikiHoverProps {
  term: string;
  children: React.ReactNode;
  className?: string;
  placement?: "auto" | "top" | "bottom";
}

export function WikiHover({
  term,
  children,
  className = "",
  placement = "auto",
}: WikiHoverProps) {
  if (DISABLE_WIKI_HOVER) {
    return <>{children}</>;
  }

  const [isOpen, setIsOpen] = useState(false);
  const [coords, setCoords] = useState<{ top: number; left: number; placeAbove: boolean } | null>(null);
  const [mounted, setMounted] = useState(false);
  const triggerRef = useRef<HTMLSpanElement>(null);
  const timerRef = useRef<NodeJS.Timeout | null>(null);
  const tooltipId = useId();

  const entry: WikiEntry | null = getWikiEntry(term);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setMounted(true);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  if (!entry) {
    return <>{children}</>;
  }

  const handleMouseEnter = () => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      if (!triggerRef.current) return;
      const rect = triggerRef.current.getBoundingClientRect();
      const placeAbove =
        placement === "top"
          ? true
          : placement === "bottom"
          ? false
          : rect.top > 250;

      const popupWidth = 320;
      let left = rect.left + rect.width / 2 - popupWidth / 2;
      const padding = 12;

      if (typeof window !== "undefined") {
        if (left < padding) left = padding;
        if (left + popupWidth > window.innerWidth - padding) {
          left = window.innerWidth - popupWidth - padding;
        }
      }

      setCoords({
        top: placeAbove ? rect.top - 8 : rect.bottom + 8,
        left,
        placeAbove,
      });
      setIsOpen(true);
    }, 120);
  };

  const handleMouseLeave = () => {
    if (timerRef.current) clearTimeout(timerRef.current);
    setIsOpen(false);
  };

  return (
    <>
      <span
        ref={triggerRef}
        className={`wiki-hover-trigger ${className}`}
        onMouseEnter={handleMouseEnter}
        onMouseLeave={handleMouseLeave}
        onFocus={handleMouseEnter}
        onBlur={handleMouseLeave}
        aria-describedby={isOpen ? tooltipId : undefined}
      >
        {children}
      </span>

      {mounted &&
        isOpen &&
        coords &&
        createPortal(
          <div
            id={tooltipId}
            role="tooltip"
            className={`wiki-popup-card ${coords.placeAbove ? "is-above" : "is-below"}`}
            style={{
              position: "fixed",
              top: coords.placeAbove ? undefined : `${coords.top}px`,
              bottom: coords.placeAbove ? `${window.innerHeight - coords.top}px` : undefined,
              left: `${coords.left}px`,
              width: "320px",
              zIndex: 99999,
              pointerEvents: "none",
            }}
          >
            <div className="wiki-popup-header">
              <div className="wiki-popup-title-row">
                <span className="wiki-popup-badge-icon" />
                <h4 className="wiki-popup-title">{entry.title}</h4>
              </div>
              {entry.tag && (
                <span
                  className="wiki-popup-tag"
                  style={
                    entry.color
                      ? { color: entry.color, borderColor: `${entry.color}40`, background: `${entry.color}15` }
                      : undefined
                  }
                >
                  {entry.tag}
                </span>
              )}
            </div>

            <p className="wiki-popup-summary">{entry.summary}</p>

            {entry.calculation && (
              <div className="wiki-popup-calc-section">
                <div className="wiki-popup-label">CALCULATION / FORMULA</div>
                <code className="wiki-popup-code">{entry.calculation}</code>
              </div>
            )}

            {entry.details && (
              <div className="wiki-popup-details-section">
                <div className="wiki-popup-label">HOW IT WORKS</div>
                <p className="wiki-popup-details-text">{entry.details}</p>
              </div>
            )}

            {entry.action && (
              <div className="wiki-popup-action-section">
                <div className="wiki-popup-label">RECOMMENDED ACTION</div>
                <p className="wiki-popup-action-text">{entry.action}</p>
              </div>
            )}
          </div>,
          document.body
        )}
    </>
  );
}

export default WikiHover;
