export type ForecastStatus =
  | "In Stock"
  | "Monitor"
  | "Reorder"
  | "Critical"
  | "Deadstock";

export interface DayForecastPoint {
  day: number;
  date: string;
  predicted: number;
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

export interface GroupedDriver {
  id: string;
  name: string;
  score: number;
  color?: string;
}

export interface ForecastedItem {
  run_id?: string;
  shap_status?: "not_requested" | "queued" | "running" | "completed" | "failed";
  shap_error?: string;
  id: string;
  sku: string;
  name: string;
  forecast14d: number;
  onHandStock: number;
  status: ForecastStatus;
  category?: string;
  warehouse?: string;
  reorderPoint?: number;
  safetyStock?: number;
  leadTimeDays?: number;
  daily_points?: DayForecastPoint[];
  grouped_drivers?: GroupedDriver[];
  price?: number;
}

export type ForecastState = "idle" | "loading" | "completed" | "error";

export interface ForecastFilter {
  search: string;
  status: "All" | ForecastStatus;
  sortBy: "forecast14d" | "onHandStock" | "name" | "status";
  sortOrder: "asc" | "desc";
  page: number;
  pageSize: number;
}
