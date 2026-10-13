# Taximan developer workflow. `make` with no target prints this list.
PY      := .venv/bin/python
export PYTHONPATH := src:concurrency

.DEFAULT_GOAL := help

help: ## show targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

venv: ## create the virtualenv and install the package with dev extras
	python3 -m venv .venv
	$(PY) -m pip install -q --upgrade pip
	$(PY) -m pip install -q -e ".[dev,warehouse]"
	@# macOS sometimes marks files under dot-directories hidden and Python 3.12 then ignores the .pth file
	@chflags -R nohidden .venv 2>/dev/null || true

db-up: ## start MySQL 8.4 in Docker and wait until healthy
	docker compose up -d --wait
	@docker exec taximan-mysql mysql -uroot -p$${MYSQL_ROOT_PASSWORD:-rootpass} -e \
	  "CREATE DATABASE IF NOT EXISTS taximan_test; GRANT ALL ON \`taximan%\`.* TO 'taximan'@'%'; FLUSH PRIVILEGES;" 2>/dev/null

db-down: ## stop MySQL (data volume is kept)
	docker compose down

db-reset: ## destroy the data volume and start fresh
	docker compose down -v && $(MAKE) db-up

migrate: ## apply pending migrations
	$(PY) -m taximan.cli migrate

seed: ## generate and load a year of synthetic data (SCALE=1 is ~300k trips)
	$(PY) -m taximan.cli seed --scale $${SCALE:-1}

analytics: ## run the 12 analytical queries
	$(PY) -m taximan.cli analytics

serve: ## run the API on http://127.0.0.1:8000 (docs at /docs)
	$(PY) -m taximan.cli serve --reload

lab: ## run all three concurrency demonstrations
	$(PY) concurrency/lost_update.py
	$(PY) concurrency/double_booking.py
	$(PY) concurrency/dispatch.py

test: ## run the test suite against the taximan_test database
	MYSQL_DATABASE=taximan_test $(PY) -m pytest -q -p no:warnings

bootstrap: venv db-up migrate seed ## everything from zero to a seeded database

# --- optional Snowflake layer, see docs/WAREHOUSE.md ------------------------
warehouse-setup: ## create the Snowflake warehouse, database, schemas and stage (once)
	$(PY) -m taximan.cli warehouse setup

warehouse-extract: ## export the PII free Parquet extract from MySQL to data/warehouse
	$(PY) -m taximan.cli warehouse extract

warehouse-load: ## recreate the RAW tables in Snowflake and load the extract
	$(PY) -m taximan.cli warehouse load

warehouse-build: ## create the ANALYTICS views in Snowflake
	$(PY) -m taximan.cli warehouse build

warehouse-check: ## reconcile Snowflake against MySQL, exits 1 on any mismatch
	$(PY) -m taximan.cli warehouse check

warehouse: warehouse-extract warehouse-load warehouse-build warehouse-check ## extract, load, build and check
