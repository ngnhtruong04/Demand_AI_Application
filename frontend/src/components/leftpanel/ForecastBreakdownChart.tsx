"use client";

import React, { useState, useMemo, useRef } from "react";
import type { ForecastedItem } from "@/types/forecast";
import { Sparkle } from "../common/Icons";
import { WikiHover } from "@/wiki";

interface ForecastBreakdownChartProps {
  item: ForecastedItem;
  language?: "en" | "vi";
  onFastInquiry?: (prompt: string) => void;
}

const PALETTE = [
  "#106ef0", // Primary blue
  "#4da20c", // Bright lime green
  "#f59e0b", // Amber
  "#8b5cf6", // Purple
  "#06b6d4", // Cyan
  "#ec4899", // Pink
];

export default function ForecastBreakdownChart({
  item,
  language = "en",
  onFastInquiry,
}: ForecastBreakdownChartProps) {
  const isVi = language === "vi";
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null);
  const hoverTimerRef = useRef<NodeJS.Timeout | null>(null);

  // 70ms hover debounce preventing flicker during rapid mouse motion
  const handleHover = (idx: number) => {
    if (hoverTimerRef.current) clearTimeout(hoverTimerRef.current);
    hoverTimerRef.current = setTimeout(() => {
      setHoveredIdx(idx);
    }, 70);
  };

  const handleLeave = () => {
    if (hoverTimerRef.current) clearTimeout(hoverTimerRef.current);
    hoverTimerRef.current = setTimeout(() => {
      setHoveredIdx(null);
    }, 90);
  };

  React.useEffect(() => {
    return () => {
      if (hoverTimerRef.current) clearTimeout(hoverTimerRef.current);
    };
  }, []);

  // Render only computed driver values.
  const { allSlices } = useMemo(() => {
    // 1. If real grouped TreeSHAP drivers are present from backend
    if (item.grouped_drivers && item.grouped_drivers.length > 0) {
      const slices = item.grouped_drivers.map((d, idx) => ({
        id: d.id,
        name: d.name,
        score: d.score,
        color: d.color || PALETTE[idx % PALETTE.length],
      }));
      return { allSlices: slices };
    }

    return { allSlices: [] };
  }, [item.grouped_drivers]);

  // Draw SVG Donut Chart
  // Radius r = 60, circumference = 2 * PI * 60 ≈ 376.99
  const radius = 60;
  const circumference = 2 * Math.PI * radius;
  const slicesWithLayout = useMemo(() => {
    return allSlices.reduce<
      Array<{
        id: string;
        name: string;
        score: number;
        color: string;
        strokeLength: number;
        strokeDasharray: string;
        strokeDashoffset: number;
      }>
    >((acc, slice) => {
      const prevOffset = acc.length > 0 ? -acc[acc.length - 1].strokeDashoffset + acc[acc.length - 1].strokeLength : 0;
      const strokeLength = (slice.score / 100) * circumference;
      acc.push({
        ...slice,
        strokeLength,
        strokeDasharray: `${strokeLength} ${circumference - strokeLength}`,
        strokeDashoffset: -prevOffset,
      });
      return acc;
    }, []);
  }, [allSlices, circumference]);

  const activeSlice = hoveredIdx !== null ? allSlices[hoveredIdx] : null;

  if (allSlices.length === 0) return <p>No non-zero feature contributions were returned.</p>;

  return (
    <div className="breakdown-tab-pane">
      <div className="breakdown-chart-header">
        <WikiHover term="breakdown">
          <span className="breakdown-chart-title">Forecast Value Drivers</span>
        </WikiHover>

      </div>

      {/* SVG Donut Chart */}
      <div className="breakdown-donut-wrapper">
        <svg viewBox="0 0 170 170" className="breakdown-donut-svg">
          <g transform="rotate(-90 85 85)">
            {/* Background ring */}
            <circle
              cx="85"
              cy="85"
              r={radius}
              fill="none"
              stroke="#f1f5f9"
              strokeWidth="20"
              pointerEvents="none"
            />
            {slicesWithLayout.map((slice, idx) => {
              const isHovered = hoveredIdx === idx;
              const isDimmed = hoveredIdx !== null && !isHovered;

              return (
                <circle
                  key={slice.id}
                  cx="85"
                  cy="85"
                  r={radius}
                  fill="none"
                  pointerEvents="stroke"
                  stroke={slice.color}
                  strokeWidth={isHovered ? 27 : isDimmed ? 16 : 20}
                  strokeDasharray={slice.strokeDasharray}
                  strokeDashoffset={slice.strokeDashoffset}
                  opacity={isDimmed ? 0.22 : 1}
                  filter={isHovered ? "drop-shadow(0 2px 6px rgba(0,0,0,0.22))" : undefined}
                  className="breakdown-donut-slice"
                  onMouseEnter={() => handleHover(idx)}
                  onMouseLeave={handleLeave}
                />
              );
            })}
          </g>

          {/* Donut Center Display (pointer-events none to avoid interfering with slice hover) */}
          <g pointerEvents="none">
            <text
              x="85"
              y="80"
              textAnchor="middle"
              className="breakdown-donut-center-val"
              style={{
                fill: activeSlice ? activeSlice.color : "#0f172a",
                transition: "fill 0.2s ease",
              }}
            >
              {activeSlice ? `${activeSlice.score}%` : "100%"}
            </text>
            <text
              x="85"
              y="96"
              textAnchor="middle"
              className="breakdown-donut-center-lbl"
            >
              {activeSlice ? activeSlice.name : "Forecast Value"}
            </text>
          </g>
        </svg>
        {onFastInquiry && (
          <button
            type="button"
            className="chart-fast-inquiry-btn"
            onClick={() =>
              onFastInquiry(
                isVi
                  ? `Giải thích các nhóm nhân tố, khuyến mãi và yếu tố mùa vụ cho ${item.name} (${item.sku}).`
                  : `Explain the forecast drivers, promotions, and seasonality factors for ${item.name} (${item.sku}).`
              )
            }
            title={`Ask Assistant about ${item.name} drivers`}
            aria-label="Ask Assistant about drivers"
          >
            <Sparkle size={14} />
          </button>
        )}
      </div>

      {/* Driver List: All Feature Groups */}
      <div className="breakdown-list">
        {allSlices.map((slice, idx) => {
          const isHovered = hoveredIdx === idx;

          return (
            <div
              key={slice.id}
              className={`breakdown-list-item ${isHovered ? "is-hovered" : ""}`}
              onMouseEnter={() => handleHover(idx)}
              onMouseLeave={handleLeave}
            >
              <div className="breakdown-item-header">
                <div className="breakdown-item-name-box">
                  <span
                    className="breakdown-item-dot"
                    style={{ backgroundColor: slice.color }}
                  />
                  <WikiHover term="breakdown">
                    <span className="breakdown-item-name">{slice.name}</span>
                  </WikiHover>
                </div>
                <WikiHover term="breakdown">
                  <span className="breakdown-item-pct">{slice.score}%</span>
                </WikiHover>
              </div>

              <div className="breakdown-item-track">
                <div
                  className="breakdown-item-bar"
                  style={{
                    width: `${slice.score}%`,
                    backgroundColor: slice.color,
                  }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
