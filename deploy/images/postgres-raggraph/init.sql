-- pg-raggraph prerequisites: extensions must exist before
-- pg_raggraph.db._ensure_schema() runs schema.sql (schema.sql:2). Verified by
-- reading the real 0.3.0a3 schema, NOT the design prose:
--   * vector   — schema.sql uses hnsw / vector_cosine_ops (pgvector base)
--   * pg_trgm  — schema.sql idx uses gin_trgm_ops (Task-0 caught this:
--                "only vector" was wrong; gin_trgm_ops needs pg_trgm)
-- Everything else (tables, migrations) is auto-applied by pg-raggraph at
-- runtime. Idempotent; runs once on first DB init against POSTGRES_DB.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
