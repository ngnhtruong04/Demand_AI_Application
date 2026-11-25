from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from psycopg import Connection, sql

from app.core.config import BACKEND_ROOT
from scripts.ingestion.common import get_api_connection, get_master_connection

IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
DEFAULT_CONFIG = BACKEND_ROOT / "config" / "core_sources.json"
CORE_TABLES = ("inventory", "calendar", "sales_daily", "series_weights")


@dataclass(frozen=True)
class TableSpec:
    name: str
    columns: tuple[str, ...]
    keys: tuple[str, ...]
    immutable: tuple[str, ...]
    expressions: tuple[str, ...]

    @property
    def mutable(self) -> tuple[str, ...]:
        return tuple(c for c in self.columns if c not in self.keys and c not in self.immutable)


SPECS = {
    "inventory": TableSpec("inventory", ("unique_id", "warehouse", "product_unique_id", "name", "l1_category_name_en", "l2_category_name_en", "l3_category_name_en", "l4_category_name_en"), ("unique_id",), ("warehouse",), ("unique_id", "warehouse", "product_unique_id::bigint", "name", '"L1_category_name_en"', '"L2_category_name_en"', '"L3_category_name_en"', '"L4_category_name_en"')),
    "calendar": TableSpec("calendar", ("warehouse", "date", "holiday_name", "holiday", "shops_closed", "winter_school_holidays", "school_holidays"), ("warehouse", "date"), (), ("warehouse", "date", "holiday_name", "holiday::smallint", "shops_closed::smallint", "winter_school_holidays::smallint", "school_holidays::smallint")),
    "sales_daily": TableSpec("sales_daily", ("unique_id", "warehouse", "date", "sales", "total_orders", "sell_price_main", "availability", "type_0_discount", "type_1_discount", "type_2_discount", "type_3_discount", "type_4_discount", "type_5_discount", "type_6_discount"), ("unique_id", "date"), ("warehouse",), ("unique_id", "warehouse", "date", "sales", "total_orders", "sell_price_main", "availability", "type_0_discount", "type_1_discount", "type_2_discount", "type_3_discount", "type_4_discount", "type_5_discount", "type_6_discount")),
    "series_weights": TableSpec("series_weights", ("unique_id", "weight"), ("unique_id",), (), ("unique_id", "weight")),
}


def load_config(path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    required = {"raw_schema", "core_schema", "tables"}
    if set(data) != required or set(data["tables"]) != set(CORE_TABLES):
        raise ValueError("Core source config has unexpected keys")
    for value in [data["raw_schema"], data["core_schema"], *data["tables"].values()]:
        if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
            raise ValueError(f"Unsafe SQL identifier in core config: {value!r}")
    return data


def _table(schema: str, table: str) -> sql.Composed:
    return sql.SQL("{}.{}").format(sql.Identifier(schema), sql.Identifier(table))


def source_query(config: dict[str, Any], spec: TableSpec) -> sql.Composed:
    expressions = [sql.SQL(e) for e in spec.expressions]
    aliases = [sql.Identifier(c) for c in spec.columns]
    fields = [sql.SQL("{} AS {}").format(e, a) for e, a in zip(expressions, aliases)]
    return sql.SQL("SELECT {} FROM {}").format(
        sql.SQL(", ").join(fields),
        _table(config["raw_schema"], config["tables"][spec.name]),
    )


def inspect_database(conn: Connection, config: dict[str, Any]) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute("SELECT version(), current_database(), current_user")
        version, database, user = cur.fetchone()
        cur.execute("SELECT table_schema, table_name FROM information_schema.tables WHERE table_schema IN (%s,%s) ORDER BY 1,2", (config["raw_schema"], config["core_schema"]))
        tables = [list(row) for row in cur.fetchall()]
        cur.execute("SELECT table_schema,table_name,column_name,data_type,is_nullable FROM information_schema.columns WHERE table_schema IN (%s,%s) ORDER BY 1,2,ordinal_position", (config["raw_schema"], config["core_schema"]))
        columns = [list(row) for row in cur.fetchall()]
    return {"version": version, "database": database, "current_user": user, "tables": tables, "columns": columns}


def validate_raw(conn: Connection, config: dict[str, Any]) -> dict[str, Any]:
    raw = config["raw_schema"]
    names = config["tables"]
    tables = {name: _table(raw, table) for name, table in names.items()}
    checks: dict[str, Any] = {}
    with conn.cursor() as cur:
        for name, table in tables.items():
            cur.execute(sql.SQL("SELECT count(*) FROM {}").format(table))
            checks[f"{name}_rows"] = cur.fetchone()[0]

        queries = {
            "inventory_bad_keys": sql.SQL("SELECT count(*) FROM {} WHERE unique_id IS NULL OR btrim(unique_id)='' OR warehouse IS NULL OR btrim(warehouse)=''").format(tables["inventory"]),
            "inventory_bad_product_id": sql.SQL("SELECT count(*) FROM {} WHERE product_unique_id IS NOT NULL AND product_unique_id !~ '^[0-9]+$'").format(tables["inventory"]),
            "inventory_duplicate_pk": sql.SQL("SELECT count(*) FROM (SELECT unique_id FROM {} GROUP BY 1 HAVING count(*)>1)x").format(tables["inventory"]),
            "calendar_bad_keys": sql.SQL("SELECT count(*) FROM {} WHERE warehouse IS NULL OR btrim(warehouse)='' OR date IS NULL").format(tables["calendar"]),
            "calendar_duplicate_pk": sql.SQL("SELECT count(*) FROM (SELECT warehouse,date FROM {} GROUP BY 1,2 HAVING count(*)>1)x").format(tables["calendar"]),
            "calendar_bad_flags": sql.SQL("SELECT count(*) FROM {} WHERE holiday NOT IN (0,1) OR shops_closed NOT IN (0,1) OR winter_school_holidays NOT IN (0,1) OR school_holidays NOT IN (0,1)").format(tables["calendar"]),
            "sales_bad_keys": sql.SQL("SELECT count(*) FROM {} WHERE unique_id IS NULL OR btrim(unique_id)='' OR warehouse IS NULL OR btrim(warehouse)='' OR date IS NULL").format(tables["sales_daily"]),
            "sales_duplicate_pk": sql.SQL("SELECT count(*) FROM (SELECT unique_id,date FROM {} GROUP BY 1,2 HAVING count(*)>1)x").format(tables["sales_daily"]),
            "sales_inventory_orphans": sql.SQL("SELECT count(*) FROM {} s LEFT JOIN {} i ON (i.unique_id,i.warehouse)=(s.unique_id,s.warehouse) WHERE i.unique_id IS NULL").format(tables["sales_daily"], tables["inventory"]),
            "sales_calendar_orphans": sql.SQL("SELECT count(*) FROM {} s LEFT JOIN {} c ON (c.warehouse,c.date)=(s.warehouse,s.date) WHERE c.warehouse IS NULL").format(tables["sales_daily"], tables["calendar"]),
            "sales_nonfinite": sql.SQL("SELECT count(*) FROM {} WHERE total_orders IN ('NaN'::float8,'Infinity'::float8,'-Infinity'::float8) OR sales IN ('NaN'::float8,'Infinity'::float8,'-Infinity'::float8) OR sell_price_main IN ('NaN'::float8,'Infinity'::float8,'-Infinity'::float8) OR availability IN ('NaN'::float8,'Infinity'::float8,'-Infinity'::float8) OR type_0_discount IN ('NaN'::float8,'Infinity'::float8,'-Infinity'::float8) OR type_1_discount IN ('NaN'::float8,'Infinity'::float8,'-Infinity'::float8) OR type_2_discount IN ('NaN'::float8,'Infinity'::float8,'-Infinity'::float8) OR type_3_discount IN ('NaN'::float8,'Infinity'::float8,'-Infinity'::float8) OR type_4_discount IN ('NaN'::float8,'Infinity'::float8,'-Infinity'::float8) OR type_5_discount IN ('NaN'::float8,'Infinity'::float8,'-Infinity'::float8) OR type_6_discount IN ('NaN'::float8,'Infinity'::float8,'-Infinity'::float8)").format(tables["sales_daily"]),
            "weights_bad_keys": sql.SQL("SELECT count(*) FROM {} WHERE unique_id IS NULL OR btrim(unique_id)=''").format(tables["series_weights"]),
            "weights_duplicate_pk": sql.SQL("SELECT count(*) FROM (SELECT unique_id FROM {} GROUP BY 1 HAVING count(*)>1)x").format(tables["series_weights"]),
            "weights_invalid": sql.SQL("SELECT count(*) FROM {} WHERE weight IS NULL OR weight <= 0 OR weight >= 'Infinity'::float8 OR weight='NaN'::float8").format(tables["series_weights"]),
            "weights_inventory_orphans": sql.SQL("SELECT count(*) FROM {} w LEFT JOIN {} i USING(unique_id) WHERE i.unique_id IS NULL").format(tables["series_weights"], tables["inventory"]),
            "sales_missing_weights": sql.SQL("SELECT count(*) FROM (SELECT DISTINCT unique_id FROM {} EXCEPT SELECT unique_id FROM {})x").format(tables["sales_daily"], tables["series_weights"]),
            "ids_multiple_warehouses": sql.SQL("SELECT count(*) FROM (SELECT unique_id FROM (SELECT unique_id,warehouse FROM {} UNION SELECT unique_id,warehouse FROM {})x GROUP BY 1 HAVING count(DISTINCT warehouse)>1)y").format(tables["inventory"], tables["sales_daily"]),
        }
        for name, query in queries.items():
            cur.execute(query)
            checks[name] = cur.fetchone()[0]
        cur.execute(sql.SQL("SELECT min(date), max(date), count(*) FILTER (WHERE sales IS NULL) FROM {}").format(tables["sales_daily"]))
        minimum, maximum, null_sales = cur.fetchone()
        checks.update(sales_min_date=str(minimum), sales_max_date=str(maximum), sales_null_count=null_sales)
        cur.execute(sql.SQL("SELECT count(*) FROM (SELECT unique_id FROM {} EXCEPT SELECT unique_id FROM {})x").format(tables["inventory"], tables["series_weights"]))
        checks["inventory_only_ids"] = cur.fetchone()[0]
    gate_names = [name for name in checks if name.endswith(("bad_keys", "bad_product_id", "duplicate_pk", "bad_flags", "orphans", "invalid", "missing_weights", "multiple_warehouses", "nonfinite"))]
    failures = {name: checks[name] for name in gate_names if checks[name] != 0}
    return {"passed": not failures, "failures": failures, "checks": checks}


def _comparison(spec: TableSpec, left: str = "t", right: str = "s") -> sql.Composed:
    payload = tuple(c for c in spec.columns if c not in spec.keys)
    return sql.SQL(" AND ").join(sql.SQL("{}.{} IS NOT DISTINCT FROM {}.{}").format(sql.Identifier(left), sql.Identifier(c), sql.Identifier(right), sql.Identifier(c)) for c in payload)


def _join(spec: TableSpec, left: str = "t", right: str = "s") -> sql.Composed:
    return sql.SQL(" AND ").join(sql.SQL("{}.{} = {}.{}").format(sql.Identifier(left), sql.Identifier(c), sql.Identifier(right), sql.Identifier(c)) for c in spec.keys)


def load_core(conn: Connection, config: dict[str, Any], on_conflict: str = "error") -> dict[str, Any]:
    if on_conflict not in {"error", "update"}:
        raise ValueError("on_conflict must be error or update")
    conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
    conn.execute("SET LOCAL lock_timeout = '15s'")
    conn.execute("SELECT pg_advisory_xact_lock(hashtext('demandai-core-load-v1'))")
    validation = validate_raw(conn, config)
    if not validation["passed"]:
        raise ValueError(f"Raw validation failed: {validation['failures']}")
    result: dict[str, Any] = {}
    core_schema = config["core_schema"]
    with conn.cursor() as cur:
        for spec in SPECS.values():
            source = source_query(config, spec)
            target = _table(core_schema, spec.name)
            join = _join(spec)
            same = _comparison(spec)
            cur.execute(sql.SQL("WITH s AS ({}) SELECT count(*) FILTER (WHERE t.{} IS NULL), count(*) FILTER (WHERE t.{} IS NOT NULL AND ({})), count(*) FILTER (WHERE t.{} IS NOT NULL AND NOT ({})) FROM s LEFT JOIN {} t ON {}").format(source, sql.Identifier(spec.keys[0]), sql.Identifier(spec.keys[0]), same, sql.Identifier(spec.keys[0]), same, target, join))
            missing, unchanged, conflicting = cur.fetchone()
            if conflicting and on_conflict == "error":
                raise ValueError(f"{spec.name}: {conflicting} existing keys have different payload")
            if spec.immutable and on_conflict == "update":
                immutable_diff = sql.SQL(" OR ").join(sql.SQL("t.{} IS DISTINCT FROM s.{}").format(sql.Identifier(c), sql.Identifier(c)) for c in spec.immutable)
                cur.execute(sql.SQL("WITH s AS ({}) SELECT count(*) FROM s JOIN {} t ON {} WHERE {}").format(source, target, join, immutable_diff))
                if cur.fetchone()[0]:
                    raise ValueError(f"{spec.name}: immutable identity mapping changed")
            columns = sql.SQL(", ").join(map(sql.Identifier, spec.columns))
            conflict_keys = sql.SQL(", ").join(map(sql.Identifier, spec.keys))
            if on_conflict == "update" and spec.mutable:
                assignments = sql.SQL(", ").join(sql.SQL("{} = EXCLUDED.{}").format(sql.Identifier(c), sql.Identifier(c)) for c in spec.mutable)
                changed = sql.SQL(" OR ").join(sql.SQL("{}.{} IS DISTINCT FROM EXCLUDED.{}").format(sql.Identifier(spec.name), sql.Identifier(c), sql.Identifier(c)) for c in spec.mutable)
                action = sql.SQL("DO UPDATE SET {} WHERE {}").format(assignments, changed)
            else:
                action = sql.SQL("DO NOTHING")
            cur.execute(sql.SQL("INSERT INTO {} ({}) ({}) ON CONFLICT ({}) {}").format(target, columns, source, conflict_keys, action))
            affected = cur.rowcount
            result[spec.name] = {"inserted": missing, "unchanged": unchanged, "conflicting": conflicting, "affected": affected, "updated": max(affected - missing, 0)}
        verification = verify_core(conn, config)
        if not verification["passed"]:
            raise ValueError(f"Core reconciliation failed: {verification['failures']}")
    return {"tables": result, "verification": verification}


def verify_core(conn: Connection, config: dict[str, Any]) -> dict[str, Any]:
    failures: dict[str, int] = {}
    checks: dict[str, Any] = {}
    with conn.cursor() as cur:
        for spec in SPECS.values():
            source = source_query(config, spec)
            target = _table(config["core_schema"], spec.name)
            join = _join(spec)
            same = _comparison(spec)
            cur.execute(sql.SQL("WITH s AS ({}) SELECT (SELECT count(*) FROM s), (SELECT count(*) FROM {}), (SELECT count(*) FROM s LEFT JOIN {} t ON {} WHERE t.{} IS NULL), (SELECT count(*) FROM s JOIN {} t ON {} WHERE NOT ({}))").format(source, target, target, join, sql.Identifier(spec.keys[0]), target, join, same))
            source_count, core_count, missing, conflicts = cur.fetchone()
            checks[spec.name] = {"source": source_count, "core": core_count, "missing": missing, "payload_conflicts": conflicts, "core_only": core_count - source_count + missing}
            if missing or conflicts:
                failures[spec.name] = missing + conflicts
        cur.execute(sql.SQL("SELECT count(*) FROM {} s JOIN {} i ON (s.unique_id,s.warehouse)=(i.unique_id,i.warehouse) JOIN {} c ON (s.warehouse,s.date)=(c.warehouse,c.date) JOIN {} w ON w.unique_id=s.unique_id").format(_table(config["core_schema"], "sales_daily"), _table(config["core_schema"], "inventory"), _table(config["core_schema"], "calendar"), _table(config["core_schema"], "series_weights")))
        checks["joined_sales_rows"] = cur.fetchone()[0]
        if checks["joined_sales_rows"] != checks["sales_daily"]["source"]:
            failures["joined_sales_rows"] = checks["joined_sales_rows"]
    return {"passed": not failures, "failures": failures, "checks": checks}


def run_migrations() -> None:
    command.upgrade(Config(str(BACKEND_ROOT / "alembic.ini")), "head")


def analyze_core(conn: Connection, config: dict[str, Any]) -> None:
    with conn.cursor() as cur:
        for table in CORE_TABLES:
            cur.execute(sql.SQL("ANALYZE {}").format(_table(config["core_schema"], table)))


def write_report(kind: str, payload: dict[str, Any], report_dir: Path) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    data = {"kind": kind, "generated_at": datetime.now(timezone.utc).isoformat(), **payload}
    path = report_dir / f"core_{kind}_{timestamp}.json"
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    md = path.with_suffix(".md")
    md.write_text(f"# Core {kind} report\n\n- Generated: {data['generated_at']}\n- Status: {'PASS' if data.get('passed', True) else 'FAIL'}\n\n```json\n{json.dumps(data, indent=2, default=str)}\n```\n", encoding="utf-8")
    return path
