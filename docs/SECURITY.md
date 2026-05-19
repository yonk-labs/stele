# Security Posture & Threat Model

Stele is **local-first / sovereign by design**: no built-in authentication,
one connection per instance, create-on-first-use schema. That design makes
several security boundaries the *operator's* responsibility, not the
library's. This page states them plainly so they are discoverable before you
deploy. For the full Tier-1/Tier-2 scaling detail, see
[OPERATING-STELE-AT-SCALE.md](OPERATING-STELE-AT-SCALE.md); for embedding-tier
specifics see [EMBEDDING-DEPLOYMENT-GAP.md](EMBEDDING-DEPLOYMENT-GAP.md) and
[EMBEDDING-FIX-PLAN.md](EMBEDDING-FIX-PLAN.md).

## Reference signing — OFF by default

`signing.mode` defaults to `"disabled"`. Unsigned `stele://` references are
**forgeable**: anyone who can guess or construct a reference string can request
the artifact behind it. This is safe for single-user / local use.

For any **shared, multi-tenant, or networked** deployment, set
`signing.mode="required"` with a strong `signing.secret`. Note the secret is
**global to the instance** — one secret signs all references, so a leaked
secret compromises *every* tenant on that instance, not just one.

Constructing a `Stele` with signing disabled emits a one-time
`SteleSecurityWarning` so the insecure-by-default posture is **not silent**.
Suppress it deliberately with:

```python
import warnings
from stele.core.exceptions import SteleSecurityWarning
warnings.filterwarnings("ignore", category=SteleSecurityWarning)
```

The disabled default is a deliberate local-first choice. The runtime warning
added here makes it non-silent. **Flipping the default to `"required"` is a
deliberate breaking change and is tracked separately** — it is intentionally
*not* changed by this work.

## Multi-tenant isolation — caller discipline, not enforcement

`namespace` is a **filter, not an enforced isolation boundary**. There is no
per-tenant authentication or authorization by design (sovereign / local-first).
Two callers using the same instance can read each other's namespaces if they
know (or guess) the namespace and reference.

For multi-tenant use, choose one:

- Distinct `namespace` per tenant **plus an application-layer authz check** on
  every call (the app, not Stele, decides who may touch which namespace), or
- One Stele instance / database **per tenant** (strongest isolation).

## PII — scrubbed on model-visible surfaces only

PII scrubbing is applied to **summaries, `fetch` output, `search`/`query`
hits, and memory text**. It is **NOT** applied to:

- raw artifact content (raw `fetch` is gated by `pii.raw_fetch_enabled`),
- `export_jsonl` output,
- the chunk index,
- pg-raggraph tables.

Treat **exports, backups, and indexes as containing raw, unscrubbed PII** and
secure them accordingly (encryption at rest, access control, retention).

## Where to go next

- [OPERATING-STELE-AT-SCALE.md](OPERATING-STELE-AT-SCALE.md) — full Tier-1
  (hard blockers) and Tier-2 (operational discipline) detail.
- [EMBEDDING-DEPLOYMENT-GAP.md](EMBEDDING-DEPLOYMENT-GAP.md) /
  [EMBEDDING-FIX-PLAN.md](EMBEDDING-FIX-PLAN.md) — embedding-tier specifics.

## CI / test note

The disabled-signing advisory is a `SteleSecurityWarning` (a `UserWarning`
subclass), emitted once per `Stele` construction with default config. The
test suite intentionally has no `filterwarnings = error`, so it surfaces as
a *reported* warning, not a failure. **If CI hardening later enables
`filterwarnings = error`**, whitelist this category or every default-config
test reddens:

```toml
[tool.pytest.ini_options]
filterwarnings = ["error", "default::stele.core.exceptions.SteleSecurityWarning"]
```
