SELECT warehouse, date, holiday_name, holiday, shops_closed,
       winter_school_holidays, school_holidays
FROM core.calendar
WHERE warehouse = %(warehouse)s
  AND date >= %(start_date)s
  AND date <= %(end_date)s
ORDER BY date;
