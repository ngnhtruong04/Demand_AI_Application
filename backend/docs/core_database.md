# Core PostgreSQL database

Schema `core` is the validated relational layer built from read-only `raw` data. It contains `inventory`, `calendar`, `sales_daily`, and `series_weights`. Feature engineering, splits, forecasts, and action tables remain outside PostgreSQL core.

## Source mapping and commands

The active mapping is `config/core_sources.json`; copy `config/core_sources.example.json` for another environment. Identifiers are validated before SQL composition.

```bash
.venv/bin/python -m scripts.core_db inspect
.venv/bin/python -m scripts.core_db validate --report-dir reports
.venv/bin/python -m scripts.core_db migrate
.venv/bin/python -m scripts.core_db load --on-conflict error --report-dir reports
.venv/bin/python -m scripts.core_db verify --report-dir reports
```

For a new environment run inspect, validate, migrate, load, then verify. Inspect and validate are read-only. Load takes an advisory lock, uses one repeatable-read snapshot, validates raw, loads all four tables, reconciles them, and commits once. Any exception rolls back the whole batch.

Identical reruns insert nothing. Existing keys with different payload fail by default. `--on-conflict update` changes mutable payload fields only; an ID-to-warehouse change still fails. Rows present only in core are retained. Reports go to `reports/` and are ignored by Git.

## Current AWS deployment

Deployment on 2026-09-08 used Amazon RDS PostgreSQL 18.3 and Alembic revision `0003_core_schema`.

| Table | Rows |
| --- | ---: |
| core.inventory | 5,432 |
| core.calendar | 23,016 |
| core.sales_daily | 4,007,419 |
| core.series_weights | 5,390 |

Sales spans 2020-08-01 through 2024-06-02 and keeps 52 NULL sales values. Inventory retains 42 IDs without sales/weights.

The current environment has the existing master/API workflow. Alembic and the loader use the master credential. The API user has USAGE and SELECT on core, without DML grants. A DBA should provision dedicated migration/ETL roles before replacing master use.

## Query and test contracts

Parameterized examples are under `sql/core/`. Training excludes `availability` from ML features while preserving it in storage. Inference history excludes `forecast_start`; future calendar includes both endpoints. Weights remain evaluation metadata.

The stored sales end in 2024. Use a historical forecast origin for demos or ingest a newer governed source; do not rewrite source dates.

```bash
RUN_RDS_CORE_INTEGRATION_TESTS=1 .venv/bin/python -m pytest -q tests/test_core_rds_integration.py
```

Use a separate PostgreSQL database for destructive constraint and rollback fixtures. This workstation has no local PostgreSQL server or container runtime, so those isolated tests remain an environment prerequisite and must not run against production RDS.
