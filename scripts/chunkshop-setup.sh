#!/usr/bin/env bash
# Batteries-included setup for Stele Phase 4 vector/hybrid indexing.
#
# Stele synthesizes ALL chunkshop config internally from `IndexingConfig`
# — users never write chunkshop YAML or set chunkshop env vars. The only
# one-time cost is the fastembed ONNX model download, which this script
# performs up front so it never happens silently inside `Stele.store()`.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="${ROOT}/.venv/bin/python"
[ -x "$PY" ] || PY="python3"

echo "==> 1/4  Install the chunkshop extra (Postgres is core; no [postgres] extra)"
echo "    uv:  uv sync --extra all-backends --extra dev --extra chunkshop"
echo "    pip: pip install 'stele-core[chunkshop]'"

echo "==> 2/4  Prefetch the embedder model (fastembed all-MiniLM-L6-v2, dim 384)"
# Equivalent to 'chunkshop prefetch' — load the embedder once so the
# multi-second ONNX fetch happens here, at install/CI time.
"$PY" - <<'PYCODE'
from chunkshop.config import FastembedEmbedder
from chunkshop.embedders import load_embedder

emb = load_embedder(
    FastembedEmbedder(
        type="fastembed",
        model_name="sentence-transformers/all-MiniLM-L6-v2",
        dim=384,
    )
)
vec = emb.embed(["__stele_probe__"])
assert vec.shape[1] == 384, vec.shape
print(f"    embedder ready: dim={emb.dim}")
PYCODE

echo "==> 3/4  Verify the model cache"
# fastembed's default cache is /tmp/fastembed_cache (NOT ~/.cache/fastembed).
FOUND=0
for d in "${FASTEMBED_CACHE_PATH:-}" /tmp/fastembed_cache "$HOME/.cache/fastembed" "$HOME/.cache/huggingface/hub"; do
  [ -n "$d" ] || continue
  if find "$d" -maxdepth 2 -type d -iname '*minilm*' 2>/dev/null | grep -q .; then
    echo "    cached under: $d"
    FOUND=1
    break
  fi
done
[ "$FOUND" -eq 1 ] || { echo "    WARNING: MiniLM cache dir not located (embed still worked)"; }

echo "==> 4/4  Optional: bring up real backends for vector/hybrid tests"
echo "    Postgres:           scripts/postgres-up.sh   (exports STELE_PG_DSN)"
echo "    MariaDB/ClickHouse: docker compose -f docker-compose.backends.yml up -d"

cat <<'NOTE'

Done. Notes:
  * Offline use: set HF_HUB_OFFLINE=1 once the model is cached; the embed
    path then never reaches the network. Run this script BEFORE going
    offline (or in CI image build).
  * The in-process ("memory") chunk store needs NO model — it uses a
    deterministic hash embedder and is always offline-safe.
  * sqlite/postgres/mariadb/clickhouse chunk stores use the cached
    fastembed model; all chunkshop config is derived from Stele's
    IndexingConfig (TargetConfig(dsn=...) — no os.environ).
NOTE
