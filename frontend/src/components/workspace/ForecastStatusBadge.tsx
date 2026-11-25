import React from "react";
import type { ForecastStatus } from "@/types/forecast";
import { WikiHover } from "@/wiki";

interface ForecastStatusBadgeProps {
  status: ForecastStatus;
  className?: string;
  enableWiki?: boolean;
}

/**
 * Returns corresponding CSS modifier class for each business status:
 * 1. In Stock: Green
 * 2. Monitor: Blue
 * 3. Reorder: Warm Amber
 * 4. Critical: Warning Red
 * 5. Deadstock: Dark Plum / Deep Charcoal (Most severe)
 */
function getStatusModifier(status: ForecastStatus): string {
  switch (status) {
    case "In Stock":
      return "status-in-stock";
    case "Monitor":
      return "status-monitor";
    case "Reorder":
      return "status-reorder";
    case "Critical":
      return "status-critical";
    case "Deadstock":
      return "status-deadstock";
    default:
      return "status-in-stock";
  }
}

export default function ForecastStatusBadge({
  status,
  className = "",
  enableWiki = true,
}: ForecastStatusBadgeProps) {
  const modifier = getStatusModifier(status);

  const badge = (
    <span
      className={`status-badge ${modifier} ${className}`}
      role="status"
      aria-label={`Status: ${status}`}
    >
      <span className="status-dot" aria-hidden="true" />
      <span className="status-text">{status}</span>
    </span>
  );

  if (!enableWiki) {
    return badge;
  }

  return <WikiHover term={status}>{badge}</WikiHover>;
}

