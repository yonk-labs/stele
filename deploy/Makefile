COMPOSE = docker compose -f docker-compose.full.yml
ROOT := $(abspath $(CURDIR)/..)
DATE := $(shell date +%Y-%m-%d)
EVID := $(ROOT)/tests/e2e/evidence/$(DATE)
PG ?= postgresql://yonk:yonk@localhost:55452/stele
MARIA ?= mariadb://yonk:yonk@localhost:53316/stele
CH ?= http://default:@localhost:58133/stele
DSNENV = STELE_PG_DSN="$(PG)" STELE_MARIADB_DSN="$(MARIA)" STELE_CLICKHOUSE_DSN="$(CH)"

.PHONY: up up-all down nuke logs dry-run e2e e2e-graph

dry-run:
	$(COMPOSE) --profile core config -q && echo "compose OK"

up:
	$(COMPOSE) --profile core up -d --wait

up-all:
	$(COMPOSE) --profile all up -d --wait

down:
	$(COMPOSE) --profile all down

nuke:
	$(COMPOSE) --profile all down -v

logs:
	$(COMPOSE) --profile all logs --tail=100

e2e: up
	mkdir -p "$(EVID)"
	cd "$(ROOT)" && bash scripts/chunkshop-setup.sh >/dev/null 2>&1 || true
	cd "$(ROOT)" && $(DSNENV) .venv/bin/pytest -q -m e2e tests/e2e \
	  | tee "$(EVID)/E2E-Report.txt"
	cd "$(ROOT)" && $(DSNENV) .venv/bin/pytest -q \
	  tests/contract/test_vector_contract.py \
	  tests/contract/test_indexing_modes_contract.py \
	  tests/integration/test_showcase_e2e.py \
	  | tee -a "$(EVID)/E2E-Report.txt"
	$(MAKE) down

e2e-graph: up-all
	cd "$(ROOT)" && STELE_PG_RAGGRAPH_DSN=postgresql://yonk:yonk@localhost:55453/stele \
	  .venv/bin/pytest -q -m e2e tests/e2e/test_living_knowledge.py
	$(MAKE) down
