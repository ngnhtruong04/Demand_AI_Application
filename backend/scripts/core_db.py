from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from app.core.config import BACKEND_ROOT
from scripts.core.service import analyze_core, inspect_database, load_config, load_core, run_migrations, validate_raw, verify_core, write_report
from scripts.ingestion.common import get_master_connection


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect, validate, migrate and publish PostgreSQL core tables")
    parser.add_argument("--config", type=Path, default=BACKEND_ROOT / "config" / "core_sources.json")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("inspect", "validate", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--report-dir", type=Path, default=BACKEND_ROOT / "reports")
    sub.add_parser("migrate")
    load = sub.add_parser("load")
    load.add_argument("--on-conflict", choices=("error", "update"), default="error")
    load.add_argument("--report-dir", type=Path, default=BACKEND_ROOT / "reports")
    args = parser.parse_args()
    started = time.monotonic()
    config = load_config(args.config)
    if args.command == "migrate":
        run_migrations()
        return
    with get_master_connection() as conn:
        if args.command in {"inspect", "validate", "verify"}:
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        if args.command == "inspect":
            payload = inspect_database(conn, config)
        elif args.command == "validate":
            payload = validate_raw(conn, config)
        elif args.command == "verify":
            payload = verify_core(conn, config)
        else:
            payload = load_core(conn, config, args.on_conflict)
    if args.command == "load":
        with get_master_connection() as conn:
            analyze_core(conn, config)
    payload["elapsed_seconds"] = round(time.monotonic() - started, 2)
    path = write_report(args.command, payload, args.report_dir)
    print(json.dumps(payload, indent=2, default=str))
    print(f"Report: {path}")
    if payload.get("passed") is False:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
