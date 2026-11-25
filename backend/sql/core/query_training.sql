SELECT s.unique_id, s.warehouse, s.date, s.sales, s.total_orders, s.sell_price_main,
       s.type_0_discount, s.type_1_discount, s.type_2_discount, s.type_3_discount,
       s.type_4_discount, s.type_5_discount, s.type_6_discount,
       i.name, i.l1_category_name_en AS "L1_category_name_en",
       i.l2_category_name_en AS "L2_category_name_en",
       i.l3_category_name_en AS "L3_category_name_en",
       i.l4_category_name_en AS "L4_category_name_en",
       c.holiday_name, c.holiday, c.shops_closed,
       c.winter_school_holidays, c.school_holidays
FROM core.sales_daily s
JOIN core.inventory i ON (i.unique_id, i.warehouse) = (s.unique_id, s.warehouse)
JOIN core.calendar c ON (c.warehouse, c.date) = (s.warehouse, s.date)
WHERE s.date >= %(start_date)s AND s.date <= %(end_date)s
ORDER BY s.unique_id, s.date;
