.PHONY: help install-backend install-frontend dev-backend dev-frontend test-backend test-frontend lint-frontend typecheck-frontend build-frontend check-db dry-run-raw core-inspect core-validate core-migrate core-load core-verify core-migrate-forecast core-load-forecast core-verify-forecast

help:
	@echo "DemandAIApplication Root Commands:"
	@echo "  make install-backend     - Setup venv and install backend dependencies"
	@echo "  make install-frontend    - Install frontend npm dependencies"
	@echo "  make dev-backend         - Run FastAPI backend in development mode"
	@echo "  make dev-frontend        - Run Next.js frontend in development mode"
	@echo "  make test-backend        - Run backend unit tests"
	@echo "  make test-frontend       - Run frontend API timeout/error tests"
	@echo "  make lint-frontend       - Run frontend ESLint"
	@echo "  make typecheck-frontend  - Run frontend TypeScript typecheck"
	@echo "  make build-frontend      - Build frontend production bundle"
	@echo "  make check-db            - Check database connection via backend"
	@echo "  make dry-run-raw         - Run dry-run data ingestion via backend"
	@echo "  make core-inspect        - Inspect raw and core schema (read-only)"
	@echo "  make core-validate       - Validate raw gates (read-only)"
	@echo "  make core-migrate        - Apply Alembic core migration"
	@echo "  make core-load           - Transactionally load core from raw"
	@echo "  make core-verify         - Reconcile core with raw (read-only)"
	@echo "  make core-migrate-forecast - Apply Alembic forecast migrations to RDS"
	@echo "  make core-load-forecast  - Ingest 14-day forecasts and TreeSHAP into RDS"
	@echo "  make core-verify-forecast- Reconcile and inspect RDS forecast retention" 

install-backend:
	$(MAKE) -C backend venv
	$(MAKE) -C backend install

install-frontend:
	npm --prefix frontend install

dev-backend:
	$(MAKE) -C backend run

dev-frontend:
	npm --prefix frontend run dev

test-backend:
	$(MAKE) -C backend test

lint-frontend:
	npm --prefix frontend run lint

typecheck-frontend:
	npm --prefix frontend run typecheck

test-frontend:
	npm --prefix frontend test

build-frontend:
	npm --prefix frontend run build

check-db:
	$(MAKE) -C backend check-db

dry-run-raw:
	$(MAKE) -C backend dry-run-raw

core-inspect:
	$(MAKE) -C backend core-inspect

core-validate:
	$(MAKE) -C backend core-validate

core-migrate:
	$(MAKE) -C backend core-migrate

core-load:
	$(MAKE) -C backend core-load

core-verify:
	$(MAKE) -C backend core-verify

core-migrate-forecast:
	$(MAKE) -C backend core-migrate-forecast

core-load-forecast:
	$(MAKE) -C backend core-load-forecast

core-verify-forecast:
	$(MAKE) -C backend core-verify-forecast
