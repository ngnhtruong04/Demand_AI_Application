"use client";

import React, { useState, useMemo, useRef } from "react";
import type { ForecastedItem, DayForecastPoint } from "@/types/forecast";
import { Sparkle, CalendarIcon, AlertOctagonIcon, AlertTriangleIcon, CheckIcon } from "../common/Icons";
import { WikiHover } from "@/wiki";

interface DailyForecastLineChartProps {
  item: ForecastedItem;
  language?: "en" | "vi";
  onFastInquiry?: (prompt: string) => void;
}

interface DayPoint {
  day: number; // 1 - 14
  dateLabel: string;
  weekday: string;
  predicted: number;
  remainingStock: number;
  top_positive_features?: Array<{
    feature: string;
    feature_label: string;
    feature_group?: string;
    shap_value: number;
    direction: string;
  }>;
  top_negative_features?: Array<{
    feature: string;
    feature_label: string;
    feature_group?: string;
    shap_value: number;
    direction: string;
  }>;
  other_positive_shap?: number;
  other_negative_shap?: number;
}


export default function DailyForecastLineChart({
  item,
  language = "en",
  onFastInquiry,
}: DailyForecastLineChartProps) {
  const isVi = language === "vi";
  // Line-chart slider state: default set day is Day 0 (index 0)
  // Default to Day 1 (first forecast day) so trajectory and fast-inquiry button are active immediately
  const [setDayIdx, setSetDayIdx] = useState<number>(1);
  const [hoverDayIdx, setHoverDayIdx] = useState<number | null>(null);
  const isDraggingRef = useRef<boolean>(false);
  const svgRef = useRef<SVGSVGElement>(null);

  const rop = item.reorderPoint !== undefined && item.reorderPoint !== null
    ? Math.ceil(item.reorderPoint)
    : (item.status === "Reorder" ? Math.ceil(item.onHandStock * 1.5) : Math.ceil(item.onHandStock * 0.7));
  const safetyStock = item.safetyStock !== undefined && item.safetyStock !== null
    ? Math.ceil(item.safetyStock)
    : Math.ceil(rop * 0.4);

  // Generate guaranteed 14-day projection sequence and stock depletion
  const dailyData: DayPoint[] = useMemo(() => {
    let runningStock = item.onHandStock;
    const now = new Date();
    const weekdays = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
    const baseDaily = Math.max(0.01, Number((item.forecast14d / 14).toFixed(2)));

    // Map existing backend daily points by day number (1..14)
    const existingMap = new Map<number, DayForecastPoint>();
    if (item.daily_points && item.daily_points.length > 0) {
      item.daily_points.forEach((pt) => existingMap.set(pt.day, pt));
    }

    const points: DayPoint[] = [];
    for (let dayNum = 1; dayNum <= 14; dayNum++) {
      const existing = existingMap.get(dayNum);
      const predicted = existing ? Math.ceil(existing.predicted) : baseDaily;
      runningStock = Math.max(0, runningStock - predicted);

      let dateLabel = `Day ${dayNum}`;
      let weekday = "";
      if (existing?.date) {
        const d = new Date(existing.date);
        if (!isNaN(d.getTime())) {
          dateLabel = d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
          weekday = weekdays[d.getDay()];
        }
      } else {
        const d = new Date(now);
        d.setDate(now.getDate() + dayNum);
        dateLabel = d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
        weekday = weekdays[d.getDay()];
      }

      points.push({
        day: dayNum,
        dateLabel,
        weekday,
        predicted,
        remainingStock: Math.max(0, Math.ceil(runningStock)),
        top_positive_features: existing?.top_positive_features,
        top_negative_features: existing?.top_negative_features,
        other_positive_shap: existing?.other_positive_shap,
        other_negative_shap: existing?.other_negative_shap,
      });
    }

    return points;
  }, [item.forecast14d, item.onHandStock, item.daily_points]);

  // Summary statistics
  const stats = useMemo(() => {
    const vals = dailyData.map((d) => d.predicted);
    const maxVal = vals.length > 0 ? Math.max(...vals) : 0;
    const minVal = vals.length > 0 ? Math.min(...vals) : 0;
    const maxDay = dailyData.find((d) => d.predicted === maxVal) || dailyData[0];
    const minDay = dailyData.find((d) => d.predicted === minVal) || dailyData[0];
    const dailyAvg = item.forecast14d / 14;
    const avg = Number(dailyAvg.toFixed(2)).toLocaleString();
    let dosLabel = "0d";
    if (dailyAvg > 0) {
      const days = item.onHandStock / dailyAvg;
      dosLabel = days >= 365 ? ">365d" : `${days >= 10 ? Math.round(days) : days.toFixed(1)}d`;
    } else if (item.onHandStock > 0) {
      dosLabel = ">365d";
    }

    return { maxVal, maxDay, minVal, minDay, avg, dosLabel };
  }, [dailyData, item.forecast14d, item.onHandStock]);

  // SVG dimensions
  const width = 320;
  const height = 110;
  const padLeft = 28;
  const padRight = 12;
  const padTop = 14;
  const padBottom = 20;

  const chartW = width - padLeft - padRight;
  const chartH = height - padTop - padBottom;

  // Demand Y Scale
  const minDemand = Math.floor(stats.minVal * 0.75);
  const maxDemand = Math.ceil(stats.maxVal * 1.2) || 1;
  const demandRange = maxDemand - minDemand || 1;

  // 15-day sequence: Day 0 (Current on-hand stock & baseline pace) + Day 1..14 (14-day forecast)
  const chartPoints: DayPoint[] = useMemo(() => {
    const day0: DayPoint = {
      day: 0,
      dateLabel: "Today",
      weekday: "Now",
      predicted: Number((item.forecast14d / 14).toFixed(2)),
      remainingStock: item.onHandStock,
    };
    return [day0, ...dailyData];
  }, [dailyData, item.forecast14d, item.onHandStock]);

  // Stock Y Scale (for depletion line & thresholds)
  const maxStockVal = Math.max(item.onHandStock, rop * 1.15, safetyStock * 1.3, 10);
  const getYDemand = (val: number) => padTop + chartH - ((val - minDemand) / demandRange) * chartH;
  const getYStock = (val: number) => padTop + chartH - (Math.max(0, val) / maxStockVal) * chartH;

  const getX = (idx: number) => padLeft + (idx / 14) * chartW;

  // Curves (15 points: Day 0 at idx 0, Day 1..14 at idx 1..14)
  const demandCoords = chartPoints.map((d, i) => ({ x: getX(i), y: getYDemand(d.predicted) }));
  const stockCoords = chartPoints.map((d, i) => ({ x: getX(i), y: getYStock(d.remainingStock) }));

  const buildBezierPath = (points: Array<{ x: number; y: number }>) => {
    if (points.length === 0) return "";
    let d = `M ${points[0].x},${points[0].y}`;
    for (let i = 0; i < points.length - 1; i++) {
      const p0 = points[i === 0 ? 0 : i - 1];
      const p1 = points[i];
      const p2 = points[i + 1];
      const p3 = points[i + 2] || p2;

      const cp1x = p1.x + (p2.x - p0.x) / 6;
      const cp1y = p1.y + (p2.y - p0.y) / 6;
      const cp2x = p2.x - (p3.x - p1.x) / 6;
      const cp2y = p2.y - (p3.y - p1.y) / 6;

      d += ` C ${cp1x},${cp1y} ${cp2x},${cp2y} ${p2.x},${p2.y}`;
    }
    return d;
  };

  const demandPathD = useMemo(() => buildBezierPath(demandCoords), [demandCoords]);
  const stockPathD = useMemo(() => buildBezierPath(stockCoords), [stockCoords]);

  const demandAreaD = useMemo(() => {
    if (demandCoords.length === 0) return "";
    const bottomY = padTop + chartH;
    return `${demandPathD} L ${demandCoords[demandCoords.length - 1].x},${bottomY} L ${demandCoords[0].x},${bottomY} Z`;
  }, [demandPathD, demandCoords, padTop, chartH]);

  const yRop = getYStock(rop);
  const ySafety = getYStock(safetyStock);

  // Active day index: previews hovered day when hovering, otherwise jumps back to set day (defaults to Day 0)
  const activeDayIdx = hoverDayIdx !== null ? hoverDayIdx : setDayIdx;
  const activePoint = chartPoints[activeDayIdx];

  const getIndexFromMouseEvent = (e: React.MouseEvent<SVGElement>) => {
    if (!svgRef.current) return setDayIdx;
    const rect = svgRef.current.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const svgX = (mouseX / rect.width) * width;

    let closestIdx = 0;
    let minDiff = Infinity;
    demandCoords.forEach((pt, idx) => {
      const diff = Math.abs(pt.x - svgX);
      if (diff < minDiff) {
        minDiff = diff;
        closestIdx = idx;
      }
    });
    return closestIdx;
  };

  const handleMouseMove = (e: React.MouseEvent<SVGElement>) => {
    const idx = getIndexFromMouseEvent(e);
    setHoverDayIdx(idx);
    if (isDraggingRef.current) {
      setSetDayIdx(idx);
    }
  };

  const handleMouseDown = (e: React.MouseEvent<SVGElement>) => {
    isDraggingRef.current = true;
    const idx = getIndexFromMouseEvent(e);
    setSetDayIdx(idx);
  };

  const handleMouseUp = () => {
    isDraggingRef.current = false;
  };

  const handleClick = (e: React.MouseEvent<SVGElement>) => {
    const idx = getIndexFromMouseEvent(e);
    setSetDayIdx(idx);
  };

  const handleMouseLeave = () => {
    isDraggingRef.current = false;
    setHoverDayIdx(null);
  };

  const safeSetDayIdx = Math.min(Math.max(0, setDayIdx), Math.max(0, chartPoints.length - 1));
  const setDemandCoord = demandCoords[safeSetDayIdx];
  const setStockCoord = stockCoords[safeSetDayIdx];
  const hoverDemandCoord =
    hoverDayIdx !== null && hoverDayIdx < demandCoords.length ? demandCoords[hoverDayIdx] : null;
  const hoverStockCoord =
    hoverDayIdx !== null && hoverDayIdx < stockCoords.length ? stockCoords[hoverDayIdx] : null;

  return (
    <div className="detail-tab-pane">
      {/* Unified Compact Header: Day info, Status & Metrics inline */}
      <div className={`detail-hover-unified-card ${hoverDayIdx !== null && hoverDayIdx !== setDayIdx ? "is-preview" : "is-active"}`}>
        <div className="detail-hover-header">
          <span className="detail-hover-date">
            <span style={{ display: "inline-flex", alignItems: "center" }}><CalendarIcon size={12} /></span>
            <span>
              {hoverDayIdx !== null && hoverDayIdx !== setDayIdx
                ? activePoint.day === 0
                  ? "Preview Day 0, Current (click to set)"
                  : `Preview Day ${activePoint.day}, ${activePoint.weekday}, ${activePoint.dateLabel} (click to set)`
                : activePoint.day === 0
                ? "Day 0, Current"
                : `Day ${activePoint.day}, ${activePoint.weekday}, ${activePoint.dateLabel}`}
            </span>
          </span>
        </div>

        <div className="detail-hover-metrics">
          <div className="detail-metric-item is-demand">
            <span className="detail-metric-label">{activePoint.day === 0 ? "Base:" : "Demand:"}</span>
            <span className="detail-metric-value">{Math.ceil(activePoint.predicted).toLocaleString()}</span>
            {activePoint.day > 0 && onFastInquiry && (
              <button
                type="button"
                className="chart-fast-inquiry-btn"
                onClick={(e) => {
                  e.stopPropagation();
                  const prompt =
                    language === "vi"
                      ? `Tại sao ${item.sku} lại dự báo bán được tới ${Math.ceil(activePoint.predicted).toLocaleString()} cái trong ngày ${activePoint.day}?`
                      : `Why is ${item.sku} forecasted to sell ${Math.ceil(activePoint.predicted).toLocaleString()} units on Day ${activePoint.day}?`;
                  onFastInquiry(prompt);
                }}
                title={`Ask Assistant about Day ${activePoint.day} forecast`}
                aria-label={`Ask Assistant about Day ${activePoint.day} forecast`}
              >
                <Sparkle size={12} />
              </button>
            )}
          </div>
          <div className="detail-metric-item is-stock">
            <span className="detail-metric-label">Stock:</span>
            <span className="detail-metric-value">{activePoint.remainingStock.toLocaleString()}</span>
            {activePoint.remainingStock <= safetyStock ? (
              <span className="detail-status-pill is-critical" style={{ display: "inline-flex", alignItems: "center", gap: 3 }}>
                <AlertOctagonIcon size={12} /> Critical
              </span>
            ) : activePoint.remainingStock <= rop ? (
              <span className="detail-status-pill is-reorder" style={{ display: "inline-flex", alignItems: "center", gap: 3 }}>
                <AlertTriangleIcon size={12} /> Reorder
              </span>
            ) : (
              <span className="detail-status-pill is-instock" style={{ display: "inline-flex", alignItems: "center", gap: 3 }}>
                <CheckIcon size={12} /> In Stock
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Interactive SVG Chart */}
      <div className="detail-chart-wrapper">
        <svg
          ref={svgRef}
          viewBox={`0 0 ${width} ${height}`}
          className="detail-line-svg"
          onMouseMove={handleMouseMove}
          onMouseLeave={handleMouseLeave}
        >
          <defs>
            <linearGradient id="demandAreaGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#106ef0" stopOpacity="0.22" />
              <stop offset="100%" stopColor="#106ef0" stopOpacity="0.0" />
            </linearGradient>
          </defs>



          {/* Grid lines */}
          {[0, 0.5, 1].map((ratio, i) => {
            const y = padTop + chartH * ratio;
            return (
              <line
                key={i}
                x1={padLeft}
                y1={y}
                x2={width - padRight}
                y2={y}
                stroke="#edf3f9"
                strokeDasharray="3 3"
              />
            );
          })}

          {/* Dotted Straight Line: Reorder Point (Amber) */}
          {yRop >= padTop && yRop <= padTop + chartH && (
            <g>
              <line
                x1={padLeft}
                y1={yRop}
                x2={width - padRight}
                y2={yRop}
                stroke="#eab308"
                strokeWidth="1.5"
                strokeDasharray="4 3"
                opacity="0.85"
              />
              <text x={width - padRight} y={yRop - 3} textAnchor="end" fill="#ca8a04" fontSize="8.2" fontWeight="700">
                ROP ({rop})
              </text>
            </g>
          )}

          {/* Dotted Straight Line: Safety Stock / Critical (Rose) */}
          {ySafety >= padTop && ySafety <= padTop + chartH && (
            <g>
              <line
                x1={padLeft}
                y1={ySafety}
                x2={width - padRight}
                y2={ySafety}
                stroke="#d21d0a"
                strokeWidth="1.5"
                strokeDasharray="4 3"
                opacity="0.85"
              />
              <text x={width - padRight} y={ySafety - 3} textAnchor="end" fill="#d21d0a" fontSize="8.2" fontWeight="700">
                Critical ({safetyStock})
              </text>
            </g>
          )}

          {/* Demand Area Fill & Curve */}
          <path d={demandAreaD} fill="url(#demandAreaGrad)" />
          <path
            d={demandPathD}
            fill="none"
            stroke="#106ef0"
            strokeWidth="2.2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />

          {/* Stock Depletion Curve (Teal) */}
          <path
            d={stockPathD}
            fill="none"
            stroke="#0ea5e9"
            strokeWidth="2.0"
            strokeDasharray="5 2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />

          {/* Data Points on Demand Curve for D0 to D14 */}
          {demandCoords.map((coord, idx) => {
            const isSelected = idx === safeSetDayIdx;
            const isHovered = idx === hoverDayIdx;
            return (
              <circle
                key={`demand-pt-${idx}`}
                cx={coord.x}
                cy={coord.y}
                r={isSelected ? 3.5 : isHovered ? 3 : 1.8}
                fill={isSelected ? "#106ef0" : isHovered ? "#3b82f6" : "#ffffff"}
                stroke="#106ef0"
                strokeWidth={isSelected ? 1.8 : 1.0}
                style={{ cursor: "pointer", transition: "r 0.15s ease" }}
                onClick={(e) => {
                  e.stopPropagation();
                  setSetDayIdx(idx);
                }}
                onMouseEnter={() => setHoverDayIdx(idx)}
              >
                <title>
                  {idx === 0
                    ? `D0 (Current): Stock ${chartPoints[0].remainingStock.toLocaleString()} units`
                    : `D${idx} (Forecast Day ${idx}): Demand ${Math.ceil(chartPoints[idx]?.predicted || 0).toLocaleString()} units`}
                </title>
              </circle>
            );
          })}

          {/* X Axis Tick Marks & Day Labels: Full D0 to D14 (D0 - Hiện tại, D1-D14 - Dự báo 14 ngày) */}
          {chartPoints.map((pt, idx) => {
            const coord = demandCoords[idx];
            if (!coord) return null;
            const isSelected = idx === safeSetDayIdx;
            const isHovered = idx === hoverDayIdx;

            return (
              <g key={`axis-tick-${idx}`} className="detail-axis-tick-group">
                {/* Small Tick Mark at bottom axis */}
                <line
                  x1={coord.x}
                  y1={padTop + chartH}
                  x2={coord.x}
                  y2={padTop + chartH + 3}
                  stroke={isSelected ? "#106ef0" : isHovered ? "#64748b" : "#cbd5e1"}
                  strokeWidth={isSelected ? 1.5 : 1}
                />

                {/* Day Label: D0 - D14 */}
                <text
                  x={coord.x}
                  y={height - 6}
                  textAnchor="middle"
                  className={`detail-axis-label ${isSelected ? "is-selected" : ""} ${isHovered ? "is-hovered" : ""}`}
                  style={{
                    fontSize: "8px",
                    fontWeight: isSelected ? "700" : isHovered ? "600" : "500",
                    fill: isSelected ? "#106ef0" : isHovered ? "#0ea5e9" : "#94a3b8",
                    cursor: "pointer",
                  }}
                  onClick={(e) => {
                    e.stopPropagation();
                    setSetDayIdx(idx);
                  }}
                  onMouseEnter={() => setHoverDayIdx(idx)}
                >
                  <title>
                    {idx === 0
                      ? `D0 (Current) - Stock: ${pt.remainingStock.toLocaleString()}`
                      : `D${pt.day} (Forecast Day ${pt.day}) - Demand: ${Math.ceil(pt.predicted).toLocaleString()}`}
                  </title>
                  D{pt.day}
                </text>
              </g>
            );
          })}

          {/* Set Day Indicator (Always visible: line + markers + flag) */}
          {setDemandCoord && setStockCoord && (
            <g className="detail-set-marker">
              <line
                x1={setDemandCoord.x}
                y1={padTop}
                x2={setDemandCoord.x}
                y2={padTop + chartH}
                stroke="#106ef0"
                strokeWidth="1.8"
                opacity="0.9"
              />
              <circle
                cx={setDemandCoord.x}
                cy={setDemandCoord.y}
                r="4"
                fill="#106ef0"
                stroke="#ffffff"
                strokeWidth="2.2"
              />
              <circle
                cx={setStockCoord.x}
                cy={setStockCoord.y}
                r="4"
                fill="#0ea5e9"
                stroke="#ffffff"
                strokeWidth="2.2"
              />
              <g transform={`translate(${setDemandCoord.x}, ${padTop - 4})`}>
                <rect
                  x="-13"
                  y="-12"
                  width="26"
                  height="13"
                  rx="3"
                  fill="#106ef0"
                />
                <text
                  x="0"
                  y="-2.5"
                  textAnchor="middle"
                  fill="#ffffff"
                  fontSize="8"
                  fontWeight="700"
                >
                  D{chartPoints[safeSetDayIdx]?.day}
                </text>
              </g>
            </g>
          )}

          {/* Hover Shadow Point & Preview (when hovering a different day) */}
          {hoverDemandCoord && hoverStockCoord && hoverDayIdx !== null && hoverDayIdx !== setDayIdx && (
            <g className="detail-hover-shadow-marker">
              <line
                x1={hoverDemandCoord.x}
                y1={padTop}
                x2={hoverDemandCoord.x}
                y2={padTop + chartH}
                stroke="#64748b"
                strokeWidth="1.2"
                strokeDasharray="2 2"
                opacity="0.75"
              />
              {/* Demand Shadow Point */}
              <circle
                cx={hoverDemandCoord.x}
                cy={hoverDemandCoord.y}
                r="7"
                fill="rgba(16, 110, 240, 0.2)"
                stroke="#106ef0"
                strokeWidth="1.5"
                strokeDasharray="2 2"
              />
              <circle
                cx={hoverDemandCoord.x}
                cy={hoverDemandCoord.y}
                r="3"
                fill="#ffffff"
                stroke="#106ef0"
                strokeWidth="2"
              />

              {/* Stock Shadow Point */}
              <circle
                cx={hoverStockCoord.x}
                cy={hoverStockCoord.y}
                r="7"
                fill="rgba(14, 165, 233, 0.2)"
                stroke="#0ea5e9"
                strokeWidth="1.5"
                strokeDasharray="2 2"
              />
              <circle
                cx={hoverStockCoord.x}
                cy={hoverStockCoord.y}
                r="3"
                fill="#ffffff"
                stroke="#0ea5e9"
                strokeWidth="2"
              />

              {/* Hover Tag */}
              <g transform={`translate(${hoverDemandCoord.x}, ${padTop - 4})`}>
                <rect
                  x="-13"
                  y="-12"
                  width="26"
                  height="13"
                  rx="3"
                  fill="#64748b"
                  opacity="0.9"
                />
                <text
                  x="0"
                  y="-2.5"
                  textAnchor="middle"
                  fill="#ffffff"
                  fontSize="8"
                  fontWeight="600"
                >
                  D{chartPoints[hoverDayIdx]?.day}
                </text>
              </g>
            </g>
          )}

          {/* Interactive Click/Scrub Overlay */}
          <rect
            x={padLeft}
            y={padTop}
            width={chartW}
            height={chartH}
            fill="transparent"
            style={{ cursor: "pointer" }}
            onMouseDown={handleMouseDown}
            onMouseUp={handleMouseUp}
            onClick={handleClick}
          />
        </svg>
      </div>

      {/* Chart Color Legend */}
      <div className="detail-legend-row">
        <div className="detail-legend-items">
          <span style={{ display: "inline-flex", alignItems: "center", gap: "4px" }}>
            <span style={{ width: "12px", height: "2px", backgroundColor: "#106ef0", display: "inline-block" }} /> Demand
          </span>
          <span style={{ display: "inline-flex", alignItems: "center", gap: "4px" }}>
            <span style={{ width: "12px", height: "2px", backgroundColor: "#0ea5e9", borderBottom: "1px dashed #0ea5e9", display: "inline-block" }} /> Stock Remaining
          </span>
          <span style={{ display: "inline-flex", alignItems: "center", gap: "4px" }}>
            <span style={{ width: "12px", borderBottom: "2px dotted #eab308", display: "inline-block" }} /> ROP
          </span>
          <span style={{ display: "inline-flex", alignItems: "center", gap: "4px" }}>
            <span style={{ width: "12px", borderBottom: "2px dotted #d21d0a", display: "inline-block" }} /> Critical
          </span>
        </div>

        {onFastInquiry && (
          <button
            type="button"
            className="chart-fast-inquiry-btn"
            onClick={() =>
              onFastInquiry(
                `Analyze the 14-day demand curve, stock depletion trajectory, and ROP/safety-stock breach risk for ${item.name} (${item.sku}).`
              )
            }
            title={`Ask Assistant about ${item.name} trajectory`}
            aria-label="Ask Assistant about trajectory"
          >
            <Sparkle size={14} />
          </button>
        )}
      </div>

      {/* Summary Stat Badges */}
      <div className="detail-stat-row">
        <div className="detail-stat-card">
          <WikiHover term="forecast">
            <span className="detail-stat-label">Daily Avg</span>
            <span className="detail-stat-value">{stats.avg} units</span>
          </WikiHover>
        </div>
        <div className="detail-stat-card">
          <span className="detail-stat-label">Peak (Day {stats.maxDay?.day})</span>
          <span className="detail-stat-value is-peak">{stats.maxVal} units</span>
        </div>
        <div className="detail-stat-card">
          <span className="detail-stat-label">Min (Day {stats.minDay?.day})</span>
          <span className="detail-stat-value is-min">{stats.minVal} units</span>
        </div>
        <div className="detail-stat-card">
          <WikiHover term="daysOfSupply">
            <span className="detail-stat-label">Day of Supply</span>
            <span className="detail-stat-value">{stats.dosLabel}</span>
          </WikiHover>
        </div>
        <div className="detail-stat-card">
          <span className="detail-stat-label">Lead Time</span>
          <span className="detail-stat-value">{item.leadTimeDays != null ? `${item.leadTimeDays}d` : "N/A"}</span>
        </div>
      </div>

      {/* Prediction Per Day Breakdown — TreeSHAP Mirror Bar Chart */}
      {(() => {
        const currentDayPoint = chartPoints[activeDayIdx];
        // Day 0 is the current benchmark point, so TreeSHAP drivers are not applicable
        if (!currentDayPoint || currentDayPoint.day === 0) {
          return null;
        }

        const currentDayIdx = Math.max(
          0,
          Math.min(dailyData.length - 1, currentDayPoint.day - 1)
        );
        const currentDay = dailyData[currentDayIdx] || dailyData[0];
        // Filter out any synthetic 'other_features' from the individual drivers list
        const rawPos = (currentDay?.top_positive_features || []).filter((d) => d.feature !== "other_features");
        const rawNeg = (currentDay?.top_negative_features || []).filter((d) => d.feature !== "other_features");

        // Guarantee Top 5 positive and negative drivers from real data
        const posDrivers = rawPos.slice(0, 5);
        const negDrivers = rawNeg.slice(0, 5);
        const maxTop5Val = Math.max(
          ...posDrivers.map((d) => Math.abs(d.shap_value)),
          ...negDrivers.map((d) => Math.abs(d.shap_value)),
          0.01
        );

        // Sum of other values strictly below top 5
        let otherPosVal = currentDay?.other_positive_shap;
        let otherNegVal = currentDay?.other_negative_shap;

        if (otherPosVal === undefined || otherPosVal === null) {
          if (rawPos.length > 5) {
            otherPosVal = Math.round(rawPos.slice(5).reduce((acc, d) => acc + Math.abs(d.shap_value), 0) * 100) / 100;
          } else {
            const foundOther = currentDay?.top_positive_features?.find((d) => d.feature === "other_features");
            otherPosVal = foundOther ? Math.abs(foundOther.shap_value) : 0;
          }
        }

        if (otherNegVal === undefined || otherNegVal === null) {
          if (rawNeg.length > 5) {
            otherNegVal = Math.round(rawNeg.slice(5).reduce((acc, d) => acc + Math.abs(d.shap_value), 0) * 100) / 100;
          } else {
            const foundOther = currentDay?.top_negative_features?.find((d) => d.feature === "other_features");
            otherNegVal = foundOther ? Math.abs(foundOther.shap_value) : 0;
          }
        }
        const otherPosPct = Math.min(100, Math.round((otherPosVal / maxTop5Val) * 100));
        const otherNegPct = Math.min(100, Math.round((otherNegVal / maxTop5Val) * 100));

        // Check previous day (day before) to localize animations: only newly popup or moved up/down
        const prevDay = currentDayIdx > 0 ? dailyData[currentDayIdx - 1] : null;
        const prevRawPos = (prevDay?.top_positive_features || []).filter((d) => d.feature !== "other_features");
        const prevRawNeg = (prevDay?.top_negative_features || []).filter((d) => d.feature !== "other_features");
        const prevPosDrivers = prevDay ? prevRawPos.slice(0, 5) : null;
        const prevNegDrivers = prevDay ? prevRawNeg.slice(0, 5) : null;
        const prevPosFeatures = prevPosDrivers?.map((d) => d.feature) ?? [];
        const prevNegFeatures = prevNegDrivers?.map((d) => d.feature) ?? [];

        const hasSpecificDate = currentDayPoint.dateLabel && !currentDayPoint.dateLabel.startsWith("Day ");
        const dateSubtitle = hasSpecificDate
          ? `${currentDayPoint.dateLabel}${currentDayPoint.weekday ? ` · ${currentDayPoint.weekday}` : ""}`
          : currentDayPoint.weekday || "";

        const getMotionInfo = (feature: string, currIdx: number, prevList: string[]) => {
          if (!prevDay) return { motionClass: "", motionType: "same" };
          const prevIdx = prevList.indexOf(feature);
          if (prevIdx === -1) {
            return { motionClass: "is-new-popup", motionType: "new" };
          }
          if (prevIdx > currIdx) {
            return { motionClass: "is-moved-up", motionType: "up" };
          }
          if (prevIdx < currIdx) {
            return { motionClass: "is-moved-down", motionType: "down" };
          }
          return { motionClass: "", motionType: "same" };
        };

        if (posDrivers.length === 0 && negDrivers.length === 0) {
          const SKELETON_NEG_BARS = [
            { nameWidth: "55%", valWidth: "24px", barWidth: "82%" },
            { nameWidth: "48%", valWidth: "22px", barWidth: "64%" },
            { nameWidth: "62%", valWidth: "26px", barWidth: "48%" },
            { nameWidth: "42%", valWidth: "20px", barWidth: "34%" },
            { nameWidth: "50%", valWidth: "22px", barWidth: "22%" },
          ];
          const SKELETON_POS_BARS = [
            { nameWidth: "58%", valWidth: "26px", barWidth: "86%" },
            { nameWidth: "46%", valWidth: "22px", barWidth: "68%" },
            { nameWidth: "64%", valWidth: "24px", barWidth: "52%" },
            { nameWidth: "40%", valWidth: "20px", barWidth: "36%" },
            { nameWidth: "52%", valWidth: "22px", barWidth: "20%" },
          ];

          return (
            <div className="shap-mirror-section is-computing">
              <div className="shap-mirror-top">
                <div className="shap-mirror-title-group">
                  <WikiHover term="shap_mirror">
                    <span className="shap-mirror-title">{`Day ${currentDayPoint.day} Forecast Drivers`}</span>
                  </WikiHover>
                  {dateSubtitle && (
                    <span className="shap-mirror-date-badge">{dateSubtitle}</span>
                  )}
                </div>
                <span className="shap-mirror-computing-tag">
                  <span className="shap-status-spinner-badge mini" />
                  <span>Computing Day {currentDayPoint.day} attributions…</span>
                </span>
              </div>

              <div className="shap-mirror-grid is-skeleton">
                <div className="shap-mirror-col is-negative">
                  <div className="shap-col-header">
                    <WikiHover term="shap_mirror">
                      <span className="shap-col-pill is-neg">▼ Decreases Demand</span>
                    </WikiHover>
                  </div>
                  <div className="shap-drivers-list is-skeleton">
                    {SKELETON_NEG_BARS.map((bar, i) => (
                      <div key={i} className="shap-mirror-card is-neg is-skeleton">
                        <div className="shap-card-header">
                          <span className="shap-skeleton-line title" style={{ width: bar.nameWidth }} />
                          <span className="shap-skeleton-line val" style={{ width: bar.valWidth }} />
                        </div>
                        <div className="shap-bar-track is-neg">
                          <div className="shap-bar-fill is-neg is-skeleton" style={{ width: bar.barWidth }}>
                            <div className="shap-bar-glimmer" />
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="shap-mirror-spine" aria-hidden="true" />

                <div className="shap-mirror-col is-positive">
                  <div className="shap-col-header">
                    <WikiHover term="shap_mirror">
                      <span className="shap-col-pill is-pos">▲ Increases Demand</span>
                    </WikiHover>
                  </div>
                  <div className="shap-drivers-list is-skeleton">
                    {SKELETON_POS_BARS.map((bar, i) => (
                      <div key={i} className="shap-mirror-card is-pos is-skeleton">
                        <div className="shap-card-header">
                          <span className="shap-skeleton-line title" style={{ width: bar.nameWidth }} />
                          <span className="shap-skeleton-line val" style={{ width: bar.valWidth }} />
                        </div>
                        <div className="shap-bar-track is-pos">
                          <div className="shap-bar-fill is-pos is-skeleton" style={{ width: bar.barWidth }}>
                            <div className="shap-bar-glimmer" />
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              <div className="shap-mirror-computing-footnote">
                <span className="shap-status-beacon" />
                <span>Forecast drivers for Day {currentDay.day} will populate automatically when calculation finishes.</span>
              </div>
            </div>
          );
        }

        return (
          <div className="shap-mirror-section">
            <div className="shap-mirror-top">
              <div className="shap-mirror-title-group">
                <WikiHover term="shap_mirror">
                  <span className="shap-mirror-title">{`Day ${currentDayPoint.day} Forecast Drivers`}</span>
                </WikiHover>
                {dateSubtitle && (
                  <span className="shap-mirror-date-badge">{dateSubtitle}</span>
                )}
              </div>
            </div>

            {/* Left & Right Side Mirror Bar Chart */}
            <div className="shap-mirror-grid">
              {/* Left Column: Negative Drivers (Pushes Demand Down) */}
              <div className="shap-mirror-col is-negative">
                <div className="shap-col-header">
                  <WikiHover term="shap_mirror">
                    <span className="shap-col-pill is-neg">▼ Decreases Demand</span>
                  </WikiHover>
                </div>
                <div className="shap-drivers-list">
                  {negDrivers.map((drv, i) => {
                    const pct = Math.min(100, Math.round((Math.abs(drv.shap_value) / maxTop5Val) * 100));
                    const valStr = drv.shap_value < 0 ? drv.shap_value.toFixed(2) : `-${drv.shap_value.toFixed(2)}`;
                    const { motionClass, motionType } = getMotionInfo(drv.feature, i, prevNegFeatures);
                    const itemKey = motionClass ? `${drv.feature}-${currentDay.day}-${motionType}` : `${drv.feature}-stable`;

                    return (
                      <div
                        key={itemKey}
                        className={`shap-mirror-card is-neg ${motionClass}`}
                        onClick={() =>
                          onFastInquiry?.(
                            isVi
                              ? `Phân tích lý do yếu tố ${drv.feature_label} làm giảm dự báo ${valStr} vào Ngày ${currentDay.day} cho ${item.name} (${item.sku}).`
                              : `Analyze why ${drv.feature_label} has a negative forecast impact of ${valStr} on Day ${currentDay.day} for ${item.name} (${item.sku}).`
                          )
                        }
                        title={`${drv.feature_label}: ${valStr} (Click to ask assistant)`}
                      >
                        <div className="shap-card-header">
                          <div className="shap-card-name-group">
                            <span className="shap-card-name" title={drv.feature_label}>
                              {drv.feature_label}
                            </span>
                            {motionType === "new" && (
                              <span className="shap-motion-pill is-new" title="New entry in Top 5 compared to day before">
                                NEW
                              </span>
                            )}
                            {motionType === "up" && (
                              <span className="shap-motion-pill is-up" title="Moved up compared to day before">
                                ▲
                              </span>
                            )}
                            {motionType === "down" && (
                              <span className="shap-motion-pill is-down" title="Moved down compared to day before">
                                ▼
                              </span>
                            )}
                          </div>
                          <span className="shap-card-val">{valStr}</span>
                        </div>
                        <div className="shap-bar-track is-neg">
                          <div className="shap-bar-fill is-neg" style={{ width: `${pct}%` }} />
                        </div>
                      </div>
                    );
                  })}

                  {/* Other Negative Drivers (Sum of all features below Top 5) */}
                  <div
                    key="other-neg"
                    className="shap-mirror-card is-neg is-other"
                    onClick={() =>
                      onFastInquiry?.(
                        isVi
                          ? `Phân tích các yếu tố kéo giảm khác đóng góp -${otherNegVal.toFixed(2)} vào Ngày ${currentDay.day} cho ${item.name} (${item.sku}).`
                          : `Analyze the other negative drivers contributing -${otherNegVal.toFixed(2)} on Day ${currentDay.day} for ${item.name} (${item.sku}).`
                      )
                    }
                    title={`Other negative features (sum below top 5): -${otherNegVal.toFixed(2)}`}
                  >
                    <div className="shap-card-header">
                      <span className="shap-card-name is-other">Other</span>
                      <span className="shap-card-val">-{otherNegVal.toFixed(2)}</span>
                    </div>
                    <div className="shap-bar-track is-neg">
                      <div className="shap-bar-fill is-neg is-other" style={{ width: `${otherNegPct}%` }} />
                    </div>
                  </div>
                </div>
              </div>

              {/* Center Spine Divider */}
              <div className="shap-mirror-spine" aria-hidden="true" />

              {/* Right Column: Positive Drivers (Pushes Demand Up) */}
              <div className="shap-mirror-col is-positive">
                <div className="shap-col-header">
                  <WikiHover term="shap_mirror">
                    <span className="shap-col-pill is-pos">▲ Increases Demand</span>
                  </WikiHover>
                </div>
                <div className="shap-drivers-list">
                  {posDrivers.map((drv, i) => {
                    const pct = Math.min(100, Math.round((Math.abs(drv.shap_value) / maxTop5Val) * 100));
                    const valStr = `+${Math.abs(drv.shap_value).toFixed(2)}`;
                    const { motionClass, motionType } = getMotionInfo(drv.feature, i, prevPosFeatures);
                    const itemKey = motionClass ? `${drv.feature}-${currentDay.day}-${motionType}` : `${drv.feature}-stable`;

                    return (
                      <div
                        key={itemKey}
                        className={`shap-mirror-card is-pos ${motionClass}`}
                        onClick={() =>
                          onFastInquiry?.(
                            isVi
                              ? `Phân tích lý do yếu tố ${drv.feature_label} thúc đẩy tăng dự báo ${valStr} vào Ngày ${currentDay.day} cho ${item.name} (${item.sku}).`
                              : `Analyze why ${drv.feature_label} has a positive forecast impact of ${valStr} on Day ${currentDay.day} for ${item.name} (${item.sku}).`
                          )
                        }
                        title={`${drv.feature_label}: ${valStr} (Click to ask assistant)`}
                      >
                        <div className="shap-card-header">
                          <div className="shap-card-name-group">
                            <span className="shap-card-name" title={drv.feature_label}>
                              {drv.feature_label}
                            </span>
                            {motionType === "new" && (
                              <span className="shap-motion-pill is-new" title="New entry in Top 5 compared to day before">
                                NEW
                              </span>
                            )}
                            {motionType === "up" && (
                              <span className="shap-motion-pill is-up" title="Moved up compared to day before">
                                ▲
                              </span>
                            )}
                            {motionType === "down" && (
                              <span className="shap-motion-pill is-down" title="Moved down compared to day before">
                                ▼
                              </span>
                            )}
                          </div>
                          <span className="shap-card-val">{valStr}</span>
                        </div>
                        <div className="shap-bar-track is-pos">
                          <div className="shap-bar-fill is-pos" style={{ width: `${pct}%` }} />
                        </div>
                      </div>
                    );
                  })}

                  {/* Other Positive Drivers (Sum of all features below Top 5) */}
                  <div
                    key="other-pos"
                    className="shap-mirror-card is-pos is-other"
                    onClick={() =>
                      onFastInquiry?.(
                        isVi
                          ? `Phân tích các yếu tố thúc đẩy khác đóng góp +${otherPosVal.toFixed(2)} vào Ngày ${currentDay.day} cho ${item.name} (${item.sku}).`
                          : `Analyze the other positive drivers contributing +${otherPosVal.toFixed(2)} on Day ${currentDay.day} for ${item.name} (${item.sku}).`
                      )
                    }
                    title={`Other positive features (sum below top 5): +${otherPosVal.toFixed(2)}`}
                  >
                    <div className="shap-card-header">
                      <span className="shap-card-name is-other">Other</span>
                      <span className="shap-card-val">+{otherPosVal.toFixed(2)}</span>
                    </div>
                    <div className="shap-bar-track is-pos">
                      <div className="shap-bar-fill is-pos is-other" style={{ width: `${otherPosPct}%` }} />
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        );
      })()}
    </div>
  );
}
