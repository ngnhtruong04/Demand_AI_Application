.PHONY: venv install cert check-db profile-raw migrate migration dry-run-raw load-raw validate-raw dry-run-inventory-snapshot load-inventory-snapshot core-inspect core-validate core-migrate core-load core-verify core-migrate-forecast core-load-forecast core-verify-forecast test run

PYTHON := .venv/bin/python
ALEMBIC := .venv/bin/alembic
UVICORN := .venv/bin/uvicorn
PYTEST := .venv/bin/pytest

venv:
	python3 -m venv .venv
	$(PYTHON) -m pip install --upgrade pip

install:
	$(PYTHON) -m pip install -e ".[dev]"

cert:
	bash scripts/download_rds_ca.sh

check-db:
	$(PYTHON) -m scripts.check_db

profile-raw:
	$(PYTHON) -m scripts.ingestion.profile_raw

migrate:
	$(ALEMBIC) upgrade head

migration:
	$(ALEMBIC) revision --autogenerate -m "$(name)"

dry-run-raw:
	$(PYTHON) -m scripts.ingestion.load_raw --all --dry-run --limit 1000

load-raw:
	$(PYTHON) -m scripts.ingestion.load_raw --all

validate-raw:
	$(PYTHON) -m scripts.ingestion.validate_raw

INVENTORY_FILE ?= data/raw/static_inventory_by_item.csv

dry-run-inventory-snapshot:
	@test -n "$(SNAPSHOT_DATE)" || (echo "SNAPSHOT_DATE is required (YYYY-MM-DD)" && exit 1)
	$(PYTHON) -m scripts.ingestion.load_inventory_snapshot --file "$(INVENTORY_FILE)" --snapshot-date "$(SNAPSHOT_DATE)" --dry-run

load-inventory-snapshot:
	@test -n "$(SNAPSHOT_DATE)" || (echo "SNAPSHOT_DATE is required (YYYY-MM-DD)" && exit 1)
	$(PYTHON) -m scripts.ingestion.load_inventory_snapshot --file "$(INVENTORY_FILE)" --snapshot-date "$(SNAPSHOT_DATE)"

test:
	$(PYTHON) -m pytest -q -m 'not integration'

run:
	$(UVICORN) app.main:app --host 0.0.0.0 --port 8000 --reload

core-inspect:
	$(PYTHON) -m scripts.core_db inspect

core-validate:
	$(PYTHON) -m scripts.core_db validate

core-migrate:
	$(PYTHON) -m scripts.core_db migrate

core-load:
	$(PYTHON) -m scripts.core_db load --on-conflict error

core-verify:
	$(PYTHON) -m scripts.core_db verify

core-migrate-forecast:
	$(ALEMBIC) upgrade head

core-load-forecast:
	$(PYTHON) -m scripts.load_forecast_to_db

core-verify-forecast:
	$(PYTHON) -m scripts.load_forecast_to_db --verify-only
