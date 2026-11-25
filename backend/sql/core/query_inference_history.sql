SELECT unique_id, warehouse, date, sales, total_orders, sell_price_main,
       type_0_discount, type_1_discount, type_2_discount, type_3_discount,
       type_4_discount, type_5_discount, type_6_discount
FROM core.sales_daily
WHERE warehouse = %(warehouse)s
  AND unique_id = ANY(%(unique_ids)s)
  AND date >= %(history_start)s
  AND date < %(forecast_start)s
ORDER BY unique_id, date;
