SELECT unique_id, weight
FROM core.series_weights
WHERE unique_id = ANY(%(unique_ids)s)
ORDER BY unique_id;
