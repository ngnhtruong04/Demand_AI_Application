import assert from "node:assert";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const statusJson = JSON.parse(fs.readFileSync(path.join(__dirname, "../src/wiki/status.json"), "utf8"));
const metricsJson = JSON.parse(fs.readFileSync(path.join(__dirname, "../src/wiki/metrics.json"), "utf8"));

// Test statuses
const expectedStatuses = ["Deadstock", "Critical", "Reorder", "Monitor", "In Stock"];
for (const status of expectedStatuses) {
  assert(statusJson.statuses[status], `Missing status: ${status}`);
  assert(statusJson.statuses[status].calculation, `Missing calculation for status: ${status}`);
  assert(statusJson.statuses[status].summary, `Missing summary for status: ${status}`);
}

// Test metrics
const expectedMetrics = ["forecast", "stock", "daysOfSupply", "reorderPoint", "safetyStock", "breakdown", "shap_mirror"];
for (const metric of expectedMetrics) {
  assert(metricsJson.metrics[metric], `Missing metric: ${metric}`);
  assert(metricsJson.metrics[metric].calculation, `Missing calculation for metric: ${metric}`);
  assert(metricsJson.metrics[metric].summary, `Missing summary for metric: ${metric}`);
}

console.log("✓ All wiki status and metric definitions verified successfully.");
