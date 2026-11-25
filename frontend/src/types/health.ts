export interface HealthStatusResponse {
  status: string;
}

export interface BackendInfoResponse {
  name: string;
  docs: string;
}

export interface HealthCheckResult {
  ok: boolean;
  data?: HealthStatusResponse;
  error?: string;
  url: string;
  responseTimeMs?: number;
}
