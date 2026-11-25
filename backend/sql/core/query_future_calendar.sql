SELECT warehouse, date, holiday_name, holiday, shops_closed,
       winter_school_holidays, school_holidays
FROM core.calendar
WHERE warehouse = %(warehouse)s
  AND date >= %(forecast_start)s
  AND date <= %(forecast_end)s
ORDER BY date;
