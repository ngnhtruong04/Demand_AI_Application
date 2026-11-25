-- Verify the demo inventory snapshot loaded for the forecast start date.
SELECT
    snapshot_date,
    COUNT(*) AS row_count,
    COUNT(DISTINCT unique_id) AS unique_item_count,
    COUNT(DISTINCT source_sha256) AS source_version_count,
    MIN(source_file) AS source_file
FROM core.inventory_snapshot
WHERE snapshot_date = DATE '2024-06-03'
GROUP BY snapshot_date;

SELECT
    scenario_group,
    COUNT(*) AS item_count
FROM core.inventory_snapshot
WHERE snapshot_date = DATE '2024-06-03'
GROUP BY scenario_group
ORDER BY scenario_group;

SELECT
    MAX(date) AS last_sales_date,
    MAX(date) + 1 AS expected_snapshot_date
FROM core.sales_daily;

SELECT COUNT(*) AS orphan_count
FROM core.inventory_snapshot AS snapshot
LEFT JOIN core.inventory AS inventory
    ON inventory.unique_id = snapshot.unique_id
WHERE snapshot.snapshot_date = DATE '2024-06-03'
  AND inventory.unique_id IS NULL;

SELECT
    unique_id,
    current_stock,
    lead_time_days,
    safety_stock,
    baseline_avg_daily_sales,
    baseline_reorder_point,
    scenario_group
FROM core.inventory_snapshot
WHERE snapshot_date = DATE '2024-06-03'
ORDER BY unique_id::bigint
LIMIT 20;
