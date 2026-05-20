#!/usr/bin/env bash
# Runnable tour of every stele data-plane subcommand via the CLI.
#
# Counterpart to examples/mcp_tour.py: both exercise the same engine
# (bind_handlers), so the JSON shapes are identical. This script is what
# you'd write if you were wiring stele into a non-MCP-capable agent or a
# CI pipeline.
#
# Run from the repo root:
#   .venv/bin/python -m pip install -e .  # if you haven't already
#   bash examples/cli_tour.sh
#
# Or with a fake home + tmp config (recommended; doesn't touch your real
# stele state):
#   HOME=$(mktemp -d) bash examples/cli_tour.sh

set -eu

# Resolve the stele binary — prefer .venv if present, fall back to PATH.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [ -x "$ROOT/.venv/bin/stele" ]; then
  STELE="$ROOT/.venv/bin/stele"
else
  STELE="$(command -v stele || true)"
fi
if [ -z "$STELE" ]; then
  echo "error: stele binary not found; run 'pip install stele-core' first" >&2
  exit 1
fi

# Use a temp dir for the tour so we don't accumulate cruft.
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
cd "$TMP"

# Pretty-print every call with jq if available; otherwise raw JSON.
JQ="$(command -v jq || true)"
fmt() { if [ -n "$JQ" ]; then "$JQ" .; else cat; fi; }

echo "=== Tour environment ==="
echo "stele: $STELE"
echo "cwd:   $TMP"
echo "jq:    ${JQ:-not found (raw JSON output)}"
echo

echo "=== Init (sqlite — memory backend doesn't persist across CLI invocations) ==="
"$STELE" init --backend sqlite
echo

# ---- Artifact surface ---------------------------------------------------

echo "=== stele store (text) ==="
REF="$("$STELE" store --text "User prefers tabs over spaces." --content-type text --namespace tour | "${JQ:-cat}" ${JQ:+-r .ref})"
if [ -z "$JQ" ]; then
  echo "  (install jq to capture refs from output; using placeholder ref for the rest of the tour)"
  REF="stele://default/placeholder"
else
  echo "  -> $REF"
fi
echo

echo "=== stele store (markdown decision log) ==="
SECOND_REF="$("$STELE" store \
  --text "Project decisions log:
- 2026-05-01: chose Postgres 15 for prod
- 2026-05-15: upgraded to Postgres 17" \
  --content-type markdown \
  --namespace tour | "${JQ:-cat}" ${JQ:+-r .ref})"
[ -n "$JQ" ] && echo "  -> $SECOND_REF"
echo

echo "=== stele fetch ==="
"$STELE" fetch "$REF" --pretty | fmt
echo

echo "=== stele search (within an artifact) ==="
"$STELE" search "$SECOND_REF" "Postgres" --limit 3 --pretty | fmt
echo

echo "=== stele query (across a namespace) ==="
"$STELE" query "postgres" --namespace tour --limit 3 --pretty | fmt
echo

echo "=== stele list ==="
"$STELE" list --namespace tour --pretty | fmt
echo

# ---- Memory surface -----------------------------------------------------

echo "=== stele memory add (initial fact) ==="
MID_OLD="$("$STELE" memory add "Project uses Postgres 15" \
  --source-ref "$SECOND_REF" \
  --kind fact \
  --namespace tour | "${JQ:-cat}" ${JQ:+-r .memory_id})"
[ -n "$JQ" ] && echo "  -> $MID_OLD"
echo

echo "=== stele memory add (supersedes the previous) ==="
MID_NEW="$("$STELE" memory add "Project uses Postgres 17" \
  --source-ref "$SECOND_REF" \
  --kind fact \
  --namespace tour \
  --supersedes "$MID_OLD" | "${JQ:-cat}" ${JQ:+-r .memory_id})"
[ -n "$JQ" ] && echo "  -> $MID_NEW (superseded $MID_OLD)"
echo

echo "=== stele memory get ==="
"$STELE" memory get "$MID_NEW" --pretty | fmt
echo

echo "=== stele memory search ==="
"$STELE" memory search "Postgres" --namespace tour --pretty | fmt
echo

echo "=== stele memory list ==="
"$STELE" memory list --namespace tour --pretty | fmt
echo

echo "=== stele memory update (metadata only) ==="
"$STELE" memory update "$MID_NEW" --metadata '{"reviewed":"tour"}' --pretty | fmt
echo

# ---- Extraction surface -------------------------------------------------

echo "=== stele extract from-text ==="
"$STELE" extract from-text \
  --text "Decision: standardize on Postgres 17 going forward. Owner: infra team." \
  --source-ref "$SECOND_REF" \
  --namespace tour \
  --pretty | fmt
echo

echo "=== stele extract from-messages ==="
echo '[
  {"role":"user","content":"What database do we use?"},
  {"role":"assistant","content":"Postgres 17 in production."}
]' | "$STELE" extract from-messages --input - --namespace tour --pretty | fmt
echo

echo "=== stele extract from-artifact ==="
"$STELE" extract from-artifact "$SECOND_REF" --namespace tour --pretty | fmt
echo

# ---- Recall -------------------------------------------------------------

echo "=== stele recall (memory_search strategy) ==="
"$STELE" recall "What Postgres version do we use?" \
  --namespace tour \
  --strategy memory_search \
  --pretty | fmt
echo

# ---- Interception -------------------------------------------------------

echo "=== stele stash (oversize Bash output) ==="
printf 'x%.0s' {1..8192} | "$STELE" stash Bash - --namespace tour --pretty | fmt
echo

# ---- Cleanup -----------------------------------------------------------

echo "=== stele memory retract ==="
"$STELE" memory retract "$MID_NEW" --reason "tour complete" --pretty | fmt
echo

echo "=== stele memory delete (soft) ==="
"$STELE" memory delete "$MID_OLD" --pretty | fmt
echo

echo "=== stele delete (artifact) ==="
"$STELE" delete "$REF" --pretty | fmt
"$STELE" delete "$SECOND_REF" --pretty | fmt
echo

echo "=== Tour complete ==="
echo "Every data-plane subcommand exercised. JSON shapes match the MCP tool surface."
