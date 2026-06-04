# Postgres Demo and Repeatable Tests

## TL;DR

Use the included Docker Compose file to start a local Postgres 16 + pgvector instance, export the DSN, and run the same contract/showcase tests against Postgres.

## Start Postgres

```bash
scripts/postgres-up.sh
```

This starts:

- image: `pgvector/pgvector:pg16`
- container: `stele-postgres`
- host port: `55432`
- database: `stele`
- user/password: `yonk` / `yonk`

Export:

```bash
export STELE_PG_DSN=postgresql://yonk:yonk@localhost:55432/stele
```

## Run Postgres Tests

```bash
scripts/test-postgres.sh
```

This runs:

- storage contract tests
- retrieval contract tests
- showcase integration tests
- `stele-showcase`

When `STELE_PG_DSN` is set, the contract and showcase suites include `PostgresBackend` rows. Without the env var, Postgres tests are skipped and the no-container path stays memory + SQLite.

## Stop Postgres

```bash
scripts/postgres-down.sh
```

## Reset Data

To remove the Docker volume and start from a clean database:

```bash
docker compose -f docker-compose.postgres.yml down -v
scripts/postgres-up.sh
```

