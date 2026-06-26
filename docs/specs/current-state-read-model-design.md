# Design note: current-state read-model (backlog item 2)

Status: design / investigation complete, 2026-06-26. Outcome: **downgrade — do not
build a materialized read-model.** A thin `memory.active()` convenience is the only
part worth considering, and even that is optional.

## The premise (from the consumer-driven backlog)

The bento gap map flagged this as the deepest signal: bento writes facts to stele
AND projects each into a separate `admin.agent_memory` SQL table, because `/v1/ask`
needs a fast "active facts for this scope" read. The inferred gap was that stele's
bi-temporal recall is the wrong shape/speed for that hot path, so stele should offer
a materialized current-state view and bento could drop the parallel table.

## What the investigation found (the premise is mostly wrong)

The duplication is **not** driven by a stele performance or shape gap. It is driven
by bento's **ACL / multi-tenant authorization layer**. Evidence in bento:

- `backend/api/ingredients/distiller.py::project_fact_to_agent_memory` docstring:
  the projection exists "to make the current fact surface on the next `/v1/ask`
  **without rewriting the ACL-aware read path**." stele stays canonical; the
  projection is the ACL-aware current-state surface.
- `recall_user_facts` (the `/v1/ask` read) is ACL-aware: org / team / personal
  scoping, project partitioning, approval state. Migrations:
  `0005_agent_memory_scope`, `0021_agent_memory_project_partition`,
  `0022_memory_acl`. Tests: `test_memory_acl`, `test_recall_org_isolation`,
  `test_memory_project_partition`.

stele's scope model is `user / agent / app / session / namespace`. It has no
org/team ACL, no project partition, no approval workflow. Those are deliberately
bento's (a product concern). So `admin.agent_memory` is not "a cache stele forced
bento to build" — it is bento's **ACL-filtered current-state read-model**, and it
would still be needed even if stele offered a fast current-state view, because the
ACL logic lives in bento's DB by design.

## Conclusion

- **Do not build a materialized current-state read-model in stele.** It would not let
  bento drop `admin.agent_memory` (ACL still forces the projection), so it buys no
  consumer value, and it adds a denormalized surface stele has to keep consistent
  with the canonical bi-temporal store. Net negative.
- **Do not build multi-tenant ACL into stele.** Zero pull, product concern, post-V1
  per the distribution notes. Pushing ACL into stele would couple it to one
  consumer's authorization model.
- **Optional, small:** a `memory.active(scope, *, kind=None, limit=...)` convenience
  that returns current active records for a scope (sugar over `list(scope,
  ["active"], ...)`). It would let bento's projection *source* its facts from one
  named call instead of a list+filter, the same way `find_precedent` did for the
  supersession join. Low effort, mild value, only worth it if a second caller wants
  it. Not urgent.

## What changed in the backlog

Item 2 is downgraded from "design next (deepest signal)" to "investigated — mostly a
non-gap; optional thin `memory.active()` only." The real next consumer-driven items
are 3 (provenance/span linkage in `extract`) and 4 (LLM-provider abstraction for
`extract.from_session`). See [consumer-driven-backlog.md](../project/consumer-driven-backlog.md).

## Honesty / scope

Based on bento's projection docstring, the ACL migrations, and the ACL test names.
I did not deep-read `recall_user_facts`' internals; if it turns out the ACL filtering
is cheap and the real `/v1/ask` cost is elsewhere, revisit. The conclusion (ACL is the
driver, not a stele read gap) is well-supported by the docstring's own words.
