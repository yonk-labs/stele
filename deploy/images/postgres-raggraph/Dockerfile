# Phase 5 — pg-raggraph harness Postgres (graph profile, port 55453).
#
# pg-raggraph is a Python LIBRARY that runs in the Stele test/host process and
# connects here over STELE_PG_RAGGRAPH_DSN. It auto-migrates its own schema on
# first connect (pg_raggraph.db._ensure_schema). The ONLY thing this image must
# add over the bare pgvector base is the `vector` EXTENSION: pg-raggraph's
# schema.sql explicitly relies on an init.sql to create extensions
# ("Extensions must be created before this runs (see init.sql)"), unlike
# Stele's own Postgres store which self-creates it. That single difference is
# why the `graph` profile needs a dedicated image, not the plain pg service.
FROM pgvector/pgvector:pg16

# Runs once on first DB init against POSTGRES_DB (=stele). Idempotent.
COPY init.sql /docker-entrypoint-initdb.d/00-pg-raggraph-init.sql
