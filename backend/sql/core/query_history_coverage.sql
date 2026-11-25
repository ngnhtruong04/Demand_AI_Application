WITH requested AS (
  SELECT unnest(%(unique_ids)s::text[]) AS unique_id
), expected_dates AS (
  SELECT d::date AS date
  FROM generate_series(%(history_start)s::date, (%(forecast_start)s::date - 1), interval '1 day') d
)
SELECT r.unique_id,
       count(s.date) AS present_days,
       count(*) FILTER (WHERE s.date IS NULL) AS missing_days,
       count(*) FILTER (WHERE s.date IS NOT NULL AND s.sales IS NULL) AS null_sales_days,
       count(*) FILTER (WHERE s.sales = 0) AS zero_sales_days
FROM requested r
CROSS JOIN expected_dates d
LEFT JOIN core.sales_daily s ON s.unique_id = r.unique_id AND s.date = d.date
GROUP BY r.unique_id
ORDER BY r.unique_id;
