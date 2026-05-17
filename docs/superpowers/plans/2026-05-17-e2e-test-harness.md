# E2E Test Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A one-command deployable full-stack docker harness that runs Stele's gated contract/e2e suites for real on all 5 backends (closing the mariadb/clickhouse e2e gap), reserves a pg-raggraph slot for Phase 5, and doubles as a sample self-host deployment.

**Architecture:** A new `deploy/` directory holds a profiled `docker-compose.full.yml` (profiles `core` | `graph` | `all`), a `Makefile`, `.env.example`, and a sample `README.md`. A new `tests/e2e/` package holds a backend-parametrized public-API journey test and a skip-gated Phase 5 living-knowledge placeholder. The `e2e` pytest marker is registered and **deselected by default** so the fast unit loop is unchanged; CI opts in via a new GitHub Actions workflow. Reuses the proven DSN conventions from `scripts/test-backends.sh` and the existing healthcheck'd compose services.

**Tech Stack:** docker compose (profiles + healthchecks), GNU make, pytest (markers + parametrize), the existing Stele public API (`Stele.from_config`, `store`/`search`/`fetch`/`recall`/`indexing_status`).

**Spec:** `docs/superpowers/specs/2026-05-17-e2e-test-harness-design.md` (design-approved).

---

## File Structure

| Path | New/Mod | Responsibility |
|---|---|---|
| `pyproject.toml` | Modify | Register `e2e` marker; `addopts = "-m 'not e2e'"` so default `pytest` excludes e2e |
| `tests/e2e/__init__.py` | Create | Package marker |
| `tests/e2e/conftest.py` | Create | Backend collector (DSN-gated), per-backend `Stele` factory, fail-loud-if-DSN-set-but-unreachable check, `e2e` marker auto-applied |
| `tests/e2e/test_full_journey.py` | Create | Public-API journey (store→index→vector/hybrid→fetch→recall) parametrized over 5 backends |
| `tests/e2e/test_living_knowledge.py` | Create | Phase 5 placeholder; skip-gated on `STELE_PG_RAGGRAPH_DSN`; encodes the Verification Bar |
| `deploy/docker-compose.full.yml` | Create | Profiled stack: `core` (pg+mariadb+clickhouse), `graph` (pg-raggraph slot), `all` |
| `deploy/.env.example` | Create | The `STELE_*` DSNs for the compose network |
| `deploy/Makefile` | Create | `up` `down` `e2e` `e2e-graph` `logs` `nuke` `dry-run` |
| `deploy/README.md` | Create | Sample self-host quickstart + sovereign notes |
| `deploy/images/postgres-raggraph/README.md` | Create | Phase 5 image stub (documented no-op now) |
| `.github/workflows/e2e.yml` | Create | CI job: boot stack via make, run e2e + gated suites |
| `.gitignore` | Modify | Ignore `tests/e2e/evidence/` |

**Not touched (locked / out of scope):** `src/stele/**`, `docker-compose.backends.yml`, `docker-compose.postgres.yml`, `scripts/*.sh` (kept working; migration is a noted follow-up, not this plan), any Phase-1 file.

**Known facts (verified, use verbatim):**
- DSN formats (from `scripts/test-backends.sh`):
  - `STELE_PG_DSN=postgresql://yonk:yonk@localhost:55432/stele`
  - `STELE_MARIADB_DSN=mariadb://yonk:yonk@localhost:53306/stele`
  - `STELE_CLICKHOUSE_DSN=http://default:@localhost:58123/stele`
- Stele config per backend: `{"backend": {"type": "memory"}}`, `{"backend": {"type": "sqlite", "path": "..."}}`, `{"backend": {"type": "<pg|mariadb|clickhouse>", "dsn": "<env>"}}`; add `{"indexing": {"mode": "sync"}}` to populate the chunk store.
- `Stele` API: `Stele.from_config(cfg)`; `stash.store(content, namespace=ns) -> StoredResult(.reference,.artifact_id,.index_status)`; `stash.search(reference, query, mode=...) -> list[SearchHit(.retrieval_mode,.chunk_id,.artifact_id,.text,.metadata)]`; `stash.fetch(reference).content`; `stash.indexing_status(artifact_id).status`; `stash.recall.artifact_search(query=, scope=MemoryScope(user_id=...), artifact_id=...).strategy_used`; `from stele.core.memory_record import MemoryScope`.
- chunk_id format is `{artifact_id}:{ordinal}`.
- venv: `.venv/bin/pytest`, `.venv/bin/ruff`, `.venv/bin/mypy`. Trio must stay green.

---

### Task 1: Register the `e2e` marker and deselect it by default

**Files:**
- Modify: `pyproject.toml` (the `[tool.pytest.ini_options]` block)
- Test: `tests/e2e/test_marker_probe.py` (temporary; deleted in Step 5)

- [ ] **Step 1: Write the failing probe test**

Create `tests/e2e/test_marker_probe.py`:

```python
import pytest


@pytest.mark.e2e
def test_probe_is_e2e_marked() -> None:
    assert True
```

- [ ] **Step 2: Run default collection to verify it is NOT deselected yet**

Run: `.venv/bin/pytest -q tests/e2e/test_marker_probe.py --collect-only 2>&1 | tail -3`
Expected: it collects `test_probe_is_e2e_marked` (marker not yet registered/deselected) — and emits a `PytestUnknownMarkWarning`.

- [ ] **Step 3: Register the marker and deselect by default**

In `pyproject.toml`, replace the `[tool.pytest.ini_options]` block:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src", "."]
addopts = "-m 'not e2e'"
markers = [
  "memory: memory backend contract tests",
  "e2e: full-stack end-to-end tests (deselected by default; CI opts in with -m e2e)",
]
```

- [ ] **Step 4: Verify default excludes e2e, explicit includes it**

Run: `.venv/bin/pytest -q tests/e2e/test_marker_probe.py 2>&1 | tail -2`
Expected: `1 deselected` (0 ran).
Run: `.venv/bin/pytest -q -m e2e tests/e2e/test_marker_probe.py 2>&1 | tail -2`
Expected: `1 passed`.
Run (regression — default suite still green & unchanged): `STELE_PG_DSN=postgresql://yonk:yonk@localhost:55432/stele .venv/bin/pytest -q 2>&1 | tail -1`
Expected: the existing pass count, `0` e2e tests run (e2e deselected).

- [ ] **Step 5: Delete the probe, commit**

```bash
rm tests/e2e/test_marker_probe.py
git add pyproject.toml
git commit -m "test(e2e): register e2e marker, deselect by default"
```

---

### Task 2: e2e package + conftest (backend collector, Stele factory, fail-loud health)

**Files:**
- Create: `tests/e2e/__init__.py`
- Create: `tests/e2e/conftest.py`

- [ ] **Step 1: Create the package marker**

Create `tests/e2e/__init__.py` (empty file).

- [ ] **Step 2: Write the conftest**

Create `tests/e2e/conftest.py`:

```python
"""E2E harness fixtures.

Backends: memory + sqlite always; postgres/mariadb/clickhouse when their
STELE_*_DSN is set. If a DSN is set but the server is unreachable, FAIL
LOUD (no silent half-up runs — that is the whole point of the harness).
Every test here is auto-marked `e2e` (deselected by default; CI opts in).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from stele import Stele

_DSN = {
    "postgres": os.environ.get("STELE_PG_DSN"),
    "mariadb": os.environ.get("STELE_MARIADB_DSN"),
    "clickhouse": os.environ.get("STELE_CLICKHOUSE_DSN"),
}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Auto-apply the `e2e` marker ONLY to items under tests/e2e/.

    A conftest hook receives the WHOLE session's items, not just this
    directory's — filter by nodeid or the global suite gets marked e2e.
    """
    for item in items:
        if item.nodeid.startswith("tests/e2e/"):
            item.add_marker(pytest.mark.e2e)


def _backends() -> list[str]:
    bk = ["memory", "sqlite"]
    bk += [name for name, dsn in _DSN.items() if dsn]
    return bk


@pytest.fixture(params=_backends())
def backend(request: pytest.FixtureRequest) -> str:
    return request.param


@pytest.fixture
def stash(backend: str, tmp_path: Path) -> Iterator[Stele]:
    cfg: dict[str, object] = {"indexing": {"mode": "sync"}}
    if backend == "memory":
        cfg["backend"] = {"type": "memory"}
    elif backend == "sqlite":
        cfg["backend"] = {"type": "sqlite", "path": str(tmp_path / "e2e.db")}
    else:
        cfg["backend"] = {"type": backend, "dsn": _DSN[backend]}
    try:
        s = Stele.from_config(cfg)
    except Exception as exc:  # noqa: BLE001 - fail loud, never skip a set DSN
        pytest.fail(
            f"{backend}: DSN is set but Stele could not connect "
            f"({type(exc).__name__}: {exc}). The harness must run against a "
            f"live server — bring it up with `make -C deploy up`."
        )
    try:
        yield s
    finally:
        s.close()
```

- [ ] **Step 3: Verify it collects with memory+sqlite and no warnings**

Run: `.venv/bin/pytest -q -m e2e tests/e2e/ --collect-only 2>&1 | tail -3`
Expected: collection succeeds (0 tests yet, no errors, no marker warning).

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/__init__.py tests/e2e/conftest.py
git commit -m "test(e2e): harness conftest — DSN-gated backends, fail-loud factory"
```

---

### Task 3: Full-journey public-API test (the e2e gap closer)

**Files:**
- Create: `tests/e2e/test_full_journey.py`

- [ ] **Step 1: Write the journey test**

Create `tests/e2e/test_full_journey.py`:

```python
"""Public-API end-to-end journey, per backend. No internals touched.

store -> indexing_status -> vector search -> hybrid search -> fetch
-> recall(artifact_search). Asserts the Phase 4 invariants on every backend —
this is what finally proves mariadb + clickhouse e2e for real.

Content is intentionally PII-free: chunkshop-backed stores correctly reject
unscrubbed PII at the write boundary (Phase 4 design). Scrub-on-fetch is a
Phase-1 guarantee with its own extensive coverage; the harness's unique value
is the cross-backend index/search/recall path.
"""

from __future__ import annotations

import re

from stele import Stele
from stele.core.memory_record import MemoryScope

_CHUNK_ID = re.compile(r"^[0-9a-f]+:\d+$")


def test_full_journey(stash: Stele) -> None:
    # namespace "default": recall.artifact_search resolves artifact_id against
    # the default namespace; artifact_id (uuid) provides uniqueness and each
    # backend param gets an isolated Stele instance.
    stored = stash.store(
        "The incident root cause was a missing database index on the "
        "orders table; the fix was to rebuild the index overnight.",
        namespace="default",
    )
    assert stored.index_status in {"indexed", "queued"}
    assert stash.indexing_status(stored.artifact_id).status == "indexed"

    vec = stash.search(stored.reference, "database index", mode="vector")
    assert vec, "vector search returned nothing"
    top = vec[0]
    assert top.retrieval_mode == "vector"
    assert top.chunk_id is not None and _CHUNK_ID.match(top.chunk_id)
    assert top.chunk_id.split(":")[0] == stored.artifact_id
    assert type(top).__module__.startswith("stele.")  # no native obj escapes

    hyb = stash.search(stored.reference, "database index", mode="hybrid")
    assert hyb and hyb[0].retrieval_mode == "hybrid"

    fetched = stash.fetch(stored.reference)
    assert "database index" in str(fetched.content)  # exact-evidence round-trip

    result = stash.recall.artifact_search(
        query="root cause",
        scope=MemoryScope(user_id="e2e"),
        artifact_id=stored.artifact_id,
    )
    assert result.strategy_used == "artifact_search"
```

- [ ] **Step 2: Run it for the always-on backends (no docker needed)**

Run: `.venv/bin/pytest -q -m e2e "tests/e2e/test_full_journey.py" -k "memory or sqlite" 2>&1 | tail -3`
Expected: `2 passed` (memory + sqlite journeys pass locally with the cached fastembed model).

- [ ] **Step 3: Run the full trio to confirm default loop is unaffected**

Run: `.venv/bin/ruff check . 2>&1 | tail -1` → `All checks passed!`
Run: `.venv/bin/mypy src tests benchmarks 2>&1 | tail -1` → `Success`
Run: `STELE_PG_DSN=postgresql://yonk:yonk@localhost:55432/stele .venv/bin/pytest -q 2>&1 | tail -1`
Expected: existing pass count unchanged; `tests/e2e` deselected (0 e2e ran).

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/test_full_journey.py
git commit -m "test(e2e): public-API full journey across backends (HC-2)"
```

---

### Task 4: Phase 5 living-knowledge placeholder (locks the bar before impl)

**Files:**
- Create: `tests/e2e/test_living_knowledge.py`

- [ ] **Step 1: Write the skip-gated placeholder**

Create `tests/e2e/test_living_knowledge.py`:

```python
"""Phase 5 Living Knowledge Verification Bar — placeholder.

Skip-gated on STELE_PG_RAGGRAPH_DSN until Phase 5 wires the Revisor. Written
NOW to lock the acceptance bar before implementation (inverse of the Phase 4
fiction problem). Bar (docs/sovereign-memory-system-plan.md): new evidence
supersedes old; superseded deprioritized/hidden by policy; retracted
hidden/flagged/surfaced by policy; as_of recovers history; version_filter
returns one family; every hit cites stele:// evidence.
"""

from __future__ import annotations

import os

import pytest

_RAGGRAPH_DSN = os.environ.get("STELE_PG_RAGGRAPH_DSN")

pytestmark = pytest.mark.skipif(
    not _RAGGRAPH_DSN,
    reason="STELE_PG_RAGGRAPH_DSN unset — Phase 5 not wired (see "
    "docs/superpowers/specs/2026-05-17-phase5-recon-correction-sheet.md)",
)


def test_supersede_then_current_view_excludes_old() -> None:
    pytest.fail("Phase 5: implement against the wired Revisor")


def test_retract_honors_policy_hide_flag_surface_both() -> None:
    pytest.fail("Phase 5: implement against the wired Revisor")


def test_as_of_recovers_historical_view() -> None:
    pytest.fail("Phase 5: implement against the wired Revisor")


def test_version_filter_returns_one_family() -> None:
    pytest.fail("Phase 5: implement against the wired Revisor")


def test_every_living_knowledge_hit_cites_stele_ref() -> None:
    pytest.fail("Phase 5: implement against the wired Revisor")
```

- [ ] **Step 2: Verify it skips cleanly today**

Run: `.venv/bin/pytest -q -m e2e tests/e2e/test_living_knowledge.py 2>&1 | tail -2`
Expected: `5 skipped` (STELE_PG_RAGGRAPH_DSN unset).

- [ ] **Step 3: Commit**

```bash
git add tests/e2e/test_living_knowledge.py
git commit -m "test(e2e): Phase 5 living-knowledge bar placeholder (skip-gated)"
```

---

### Task 5: Profiled full-stack compose + env example

**Files:**
- Create: `deploy/docker-compose.full.yml`
- Create: `deploy/.env.example`

- [ ] **Step 1: Write the compose file**

Create `deploy/docker-compose.full.yml`:

```yaml
# Stele full-stack harness + sample deployment.
# Profiles: core (pg+mariadb+clickhouse) | graph (Phase 5 pg-raggraph) | all
services:
  postgres:
    profiles: ["core", "all"]
    image: pgvector/pgvector:pg16
    container_name: stele-e2e-postgres
    environment:
      POSTGRES_USER: yonk
      POSTGRES_PASSWORD: yonk
      POSTGRES_DB: stele
    ports: ["55432:5432"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U yonk -d stele"]
      interval: 2s
      timeout: 5s
      retries: 30

  mariadb:
    profiles: ["core", "all"]
    image: mariadb:11.7
    container_name: stele-e2e-mariadb
    environment:
      MARIADB_USER: yonk
      MARIADB_PASSWORD: yonk
      MARIADB_DATABASE: stele
      MARIADB_ROOT_PASSWORD: yonkroot
    ports: ["53306:3306"]
    healthcheck:
      test: ["CMD", "healthcheck.sh", "--connect", "--innodb_initialized"]
      interval: 2s
      timeout: 5s
      retries: 40

  clickhouse:
    profiles: ["core", "all"]
    image: clickhouse/clickhouse-server:24.10
    container_name: stele-e2e-clickhouse
    environment:
      CLICKHOUSE_DB: stele
      CLICKHOUSE_USER: default
      CLICKHOUSE_PASSWORD: ""
    ports: ["58123:8123", "59000:9000"]
    healthcheck:
      test: ["CMD", "wget", "--spider", "-q", "http://localhost:8123/ping"]
      interval: 2s
      timeout: 5s
      retries: 40

  # Phase 5 reserved slot — built when pg-raggraph PRG-1..PRG-4 land.
  # Distinct port so it runs alongside the plain pgvector service.
  postgres-raggraph:
    profiles: ["graph", "all"]
    build: ./images/postgres-raggraph
    container_name: stele-e2e-postgres-raggraph
    environment:
      POSTGRES_USER: yonk
      POSTGRES_PASSWORD: yonk
      POSTGRES_DB: stele
    ports: ["55433:5432"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U yonk -d stele"]
      interval: 2s
      timeout: 5s
      retries: 30
```

- [ ] **Step 2: Write the env example**

Create `deploy/.env.example`:

```sh
# Source these (or `export`) before `make e2e` to run gated suites for real.
export STELE_PG_DSN=postgresql://yonk:yonk@localhost:55432/stele
export STELE_MARIADB_DSN=mariadb://yonk:yonk@localhost:53306/stele
export STELE_CLICKHOUSE_DSN=http://default:@localhost:58123/stele
# Phase 5 only (graph profile):
# export STELE_PG_RAGGRAPH_DSN=postgresql://yonk:yonk@localhost:55433/stele
```

- [ ] **Step 3: Validate compose config (no images pulled)**

Run: `docker compose -f deploy/docker-compose.full.yml --profile core config -q && echo OK`
Expected: `OK` (valid config, no error).
Run: `docker compose -f deploy/docker-compose.full.yml --profile graph config 2>&1 | grep -c postgres-raggraph`
Expected: a non-zero count (graph profile selects the reserved service).

- [ ] **Step 4: Bring up core and verify health**

Run: `docker compose -f deploy/docker-compose.full.yml --profile core up -d --wait`
Expected: 3 services become healthy (command returns 0). If it fails, that is a real environment problem — fix before proceeding (do not skip).
Run: `docker compose -f deploy/docker-compose.full.yml --profile core down`

- [ ] **Step 5: Commit**

```bash
git add deploy/docker-compose.full.yml deploy/.env.example
git commit -m "feat(deploy): profiled full-stack compose (core|graph|all)"
```

---

### Task 6: Makefile (up/down/e2e/e2e-graph/logs/nuke/dry-run)

**Files:**
- Create: `deploy/Makefile`

- [ ] **Step 1: Write the Makefile**

Create `deploy/Makefile` (note: recipe lines are TAB-indented):

```make
COMPOSE = docker compose -f docker-compose.full.yml
ROOT := $(abspath $(CURDIR)/..)
DATE := $(shell date +%Y-%m-%d)
EVID := $(ROOT)/tests/e2e/evidence/$(DATE)
PG ?= postgresql://yonk:yonk@localhost:55432/stele
MARIA ?= mariadb://yonk:yonk@localhost:53306/stele
CH ?= http://default:@localhost:58123/stele
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
	cd "$(ROOT)" && STELE_PG_RAGGRAPH_DSN=postgresql://yonk:yonk@localhost:55433/stele \
	  .venv/bin/pytest -q -m e2e tests/e2e/test_living_knowledge.py
	$(MAKE) down
```

> Why two pytest invocations: the global `addopts = "-m 'not e2e'"` plus a
> CLI `-m` means a single run can't both *include* `tests/e2e` (needs
> `-m e2e`) and *include* the unmarked contract/integration files (a
> command-line `-m` filters ALL collected items, even explicitly-named
> files). So: run 1 = `-m e2e tests/e2e`; run 2 = the named contract/
> integration files under the default `-m 'not e2e'` (they are unmarked, so
> not excluded). Both with all DSNs set → mariadb+clickhouse run for real.

- [ ] **Step 2: Validate the Makefile parses**

Run: `make -C deploy dry-run 2>&1 | tail -1`
Expected: `compose OK`.

- [ ] **Step 3: Full real run — the HC-1 proof**

Run: `make -C deploy e2e 2>&1 | tail -8`
Expected: stack boots; `tests/e2e/test_full_journey.py` runs **memory + sqlite + postgres + mariadb + clickhouse** (5 params, no DSN skips); contract + showcase suites pass for real; `mariadb` and `clickhouse` journeys PASS (the gap is closed); evidence written to `tests/e2e/evidence/<date>/E2E-Report.txt`; stack torn down. Zero failures.

- [ ] **Step 4: Commit**

```bash
git add deploy/Makefile
git commit -m "feat(deploy): Makefile — e2e runs all 5 backends for real (HC-1)"
```

---

### Task 7: Phase 5 image stub + reserved-slot doc

**Files:**
- Create: `deploy/images/postgres-raggraph/README.md`

- [ ] **Step 1: Write the stub doc**

Create `deploy/images/postgres-raggraph/README.md`:

```markdown
# postgres-raggraph image (Phase 5 — reserved slot, NOT yet built)

The `graph` / `all` compose profiles reference a `build: .` here. It is a
**documented no-op until Phase 5**. Building it is gated by the Phase 5
Task-0 in `docs/superpowers/specs/2026-05-17-phase5-recon-correction-sheet.md`
and the pg-raggraph changes in `2026-05-17-pg-raggraph-requirements.md`
(PRG-1..PRG-4).

When Phase 5 is scheduled, this directory gets a `Dockerfile`:
`pgvector/pgvector:pg16` base + the pinned `pg-raggraph` Python package +
its schema bootstrap. Until then, do not run `--profile graph` expecting a
working server; `tests/e2e/test_living_knowledge.py` stays skip-gated on
`STELE_PG_RAGGRAPH_DSN`.
```

- [ ] **Step 2: Add a placeholder Dockerfile that fails loud if built early**

Create `deploy/images/postgres-raggraph/Dockerfile`:

```dockerfile
# Phase 5 placeholder. Building this now is intentionally an error so the
# `graph` profile cannot silently come up half-working before Phase 5.
FROM pgvector/pgvector:pg16
RUN echo "pg-raggraph image is a Phase 5 deliverable — see README.md" >&2 && false
```

- [ ] **Step 3: Verify `core` profile is unaffected by the stub**

Run: `docker compose -f deploy/docker-compose.full.yml --profile core config -q && echo OK`
Expected: `OK` (core does not reference the build).

- [ ] **Step 4: Commit**

```bash
git add deploy/images/postgres-raggraph/README.md deploy/images/postgres-raggraph/Dockerfile
git commit -m "feat(deploy): reserve Phase 5 pg-raggraph image slot (fail-loud stub)"
```

---

### Task 8: Sample self-host README

**Files:**
- Create: `deploy/README.md`

- [ ] **Step 1: Write the README**

Create `deploy/README.md`:

```markdown
# Stele — Full-Stack Deployment & E2E Harness

This is both the **end-to-end test target** and a **sample self-host
deployment**. Sovereign defaults: after image pull + model cache, no runtime
network is required (set `HF_HUB_OFFLINE=1`).

## Quickstart

```sh
cp .env.example .env && source .env          # STELE_* DSNs
make up                                       # core stack (pg + mariadb + clickhouse), waits for health
cd .. && bash scripts/chunkshop-setup.sh      # one-time: cache the embedder model
make e2e                                       # run the full e2e + contract suites for real, then tear down
```

## Profiles

| Profile | Services | Use |
|---|---|---|
| `core` | postgres(pgvector), mariadb, clickhouse | Phase 1–4 full e2e (default) |
| `graph` | postgres-raggraph | Phase 5 living-knowledge (not built yet) |
| `all` | everything | CI full sweep |

## What `make e2e` proves

`tests/e2e/test_full_journey.py` walks the public Stele API
(store → index → vector/hybrid search → fetch → recall) on **all five
backends**, including mariadb + clickhouse for real. Evidence is written to
`../tests/e2e/evidence/<date>/E2E-Report.txt`.

## Targets

`make up | up-all | down | nuke | logs | dry-run | e2e | e2e-graph`

## Notes

- This does not replace the fast unit loop: `e2e` tests are deselected from
  default `pytest` (`-m 'not e2e'`); CI opts in.
- `make nuke` removes volumes for a clean slate.
- Phase 5 (`graph` profile) is reserved; see `images/postgres-raggraph/`.
```

- [ ] **Step 2: Verify links resolve**

Run: `test -f tests/e2e/test_full_journey.py && test -f scripts/chunkshop-setup.sh && echo OK`
Expected: `OK`.

- [ ] **Step 3: Commit**

```bash
git add deploy/README.md
git commit -m "docs(deploy): sample self-host + e2e quickstart"
```

---

### Task 9: CI e2e workflow + evidence gitignore

**Files:**
- Create: `.github/workflows/e2e.yml`
- Modify: `.gitignore`

- [ ] **Step 1: Ignore the evidence dir**

Append to `.gitignore`:

```
# e2e harness captured run reports
tests/e2e/evidence/
```

- [ ] **Step 2: Write the CI workflow**

Create `.github/workflows/e2e.yml`:

```yaml
name: e2e
on:
  workflow_dispatch: {}
  push:
    branches: ["phase4-chunkshop-indexing", "main"]
jobs:
  e2e:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Install uv
        run: curl -LsSf https://astral.sh/uv/install.sh | sh
      - name: Sync env
        run: ~/.local/bin/uv sync --extra all-backends --extra dev --extra chunkshop
      - name: Cache embedder model
        run: bash scripts/chunkshop-setup.sh
      - name: Full-stack e2e (all 5 backends for real)
        run: make -C deploy e2e
      - name: Upload evidence
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: e2e-evidence
          path: tests/e2e/evidence/
```

- [ ] **Step 3: Validate the workflow YAML parses**

Run: `.venv/bin/python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/e2e.yml')); print('YAML OK')"`
Expected: `YAML OK`.

- [ ] **Step 4: Commit**

```bash
git add .gitignore .github/workflows/e2e.yml
git commit -m "ci(e2e): full-stack e2e workflow + evidence artifact"
```

---

### Task 10: Final verification (HC-1..HC-6) + plan close-out

**Files:** none (verification only)

- [ ] **Step 1: Default loop unaffected (HC-5)**

Run: `STELE_PG_DSN=postgresql://yonk:yonk@localhost:55432/stele .venv/bin/pytest -q 2>&1 | tail -1`
Expected: pre-harness pass count, 0 e2e ran (e2e deselected by default).

- [ ] **Step 2: Trio green**

Run: `.venv/bin/ruff check . 2>&1 | tail -1` → `All checks passed!`
Run: `.venv/bin/mypy src tests benchmarks 2>&1 | tail -1` → `Success`

- [ ] **Step 3: Full harness run proves the gap closed (HC-1, HC-2)**

Run: `make -C deploy e2e 2>&1 | tail -6`
Expected: `test_full_journey` shows 5 passing params incl. `mariadb` + `clickhouse` (no DSN skips), contract/showcase pass, evidence file exists at `tests/e2e/evidence/<date>/E2E-Report.txt`.

- [ ] **Step 4: Locked-files untouched (HC-6)**

Run: `git diff --name-only main..HEAD | grep -E '^src/stele/|docker-compose.backends.yml|docker-compose.postgres.yml|^scripts/' || echo "LOCKED-FILES CLEAN"`
Expected: `LOCKED-FILES CLEAN` (harness is purely additive: `deploy/`, `tests/e2e/`, `pyproject.toml` marker, `.github/`, `.gitignore`).

- [ ] **Step 5: Final commit**

```bash
git commit --allow-empty -m "chore(e2e): harness verified — HC-1..HC-6 green, mariadb+clickhouse e2e closed"
```

---

## Self-Review

**Spec coverage** (vs `2026-05-17-e2e-test-harness-design.md`): HC-1 → Task 6/10; HC-2 → Task 3; HC-3 (graph profile + living-knowledge skip-gated) → Task 4/5/7; HC-4 (sample README + sovereign) → Task 8; HC-5 (default pytest unchanged) → Task 1/10; HC-6 (no locked file) → Task 10. `deploy/` layout, profiles, evidence capture, CI → Tasks 5/6/9. All spec sections map to a task.

**Placeholder scan:** No "TBD"/"add error handling"/"similar to Task N". The Phase 5 image Dockerfile/README and `test_living_knowledge.py` `pytest.fail` bodies are *intentional, spec-required* reserved placeholders (HC-3), not plan placeholders — each is fully specified and gated.

**Type/name consistency:** `stash` fixture (Task 2) used by Task 3; `backend` param consistent; DSN env names (`STELE_PG_DSN`/`STELE_MARIADB_DSN`/`STELE_CLICKHOUSE_DSN`/`STELE_PG_RAGGRAPH_DSN`) consistent across conftest, compose, .env, Makefile, CI; `e2e` marker name consistent; compose service/port names consistent across compose, Makefile, README. `_CHUNK_ID` regex + Stele API names match the verified Phase 4 surface.

One known follow-up (noted, not a gap): migrating `scripts/*.sh` + old compose files onto `deploy/` is deliberately out of scope (kept working); flagged in the spec's Open Decisions.

---

## Execution Corrections (applied 2026-05-17 during inline execution)

Real defects/findings surfaced while executing; live files are authoritative,
this records the deltas (the recon discipline — keep the plan honest):

1. **Dedicated ports** (Task 5/6). The plan copied `docker-compose.backends.yml`
   ports (55432/53306/58123/59000); the environment has a long-lived legacy
   stack (project's pre-rename `yonk-memory-stash-*` containers) squatting
   them. Harness now uses **55452 / 53316 / 58133 / 59010 / 55453** so it is
   self-contained and never collides with or disturbs anything else. Makefile
   defaults + `.env.example` updated accordingly.
2. **conftest marker scope** (Task 2). `pytest_collection_modifyitems` must
   filter `item.nodeid.startswith("tests/e2e/")` — a conftest hook receives
   the whole session's items; without the filter all 419 tests got `e2e`-
   marked and the default suite collapsed to "433 deselected".
3. **Journey content + scope** (Task 3). Content must be PII-free
   (chunkshop-backed stores correctly reject unscrubbed PII at the write
   boundary — Phase 4 design) and `namespace="default"` (recall resolves
   artifact_id there). The recall step runs **only on memory/sqlite/postgres**
   — MariaDB/ClickHouse memory stores are Phase-1 `CapabilityError` stubs by
   design (they support artifact + vector/hybrid only). Test each backend's
   real capability surface; no false green.
4. **ClickHouse experimental vector index** (Task 5/6). chunkshop's CH sink
   emits `vector_similarity('hnsw','cosineDistance')`, which is
   upstream-experimental in ALL ClickHouse versions and chunkshop expects it
   enabled at the server profile level (it does not set it per-query, and is
   pinned to CH 24.10.4 workarounds — a newer image does NOT help). Harness
   mounts `deploy/clickhouse/users.d/allow-vector-index.xml`
   (`allow_experimental_vector_similarity_index=1`) — the actual supported
   mechanism (ClickHouse Cloud enables it by default). Follow-up track: a
   chunkshop change so its CH sink sets this itself (no server config needed
   anywhere) — owner-controlled, same pattern as the pg-raggraph PRG asks.

**HC-1 verified GREEN (2026-05-17):** `make -C deploy e2e` →
`tests/e2e` 5 passed / 5 skipped (Phase 5 placeholder) + contract/integration
21 passed. mariadb + clickhouse exercised end-to-end **for real** — the
original mission gap is closed.
