# Stele Build Specs

These documents are the implementation handoff for the rebuild. The mission brief defines what "complete" means; these specs define what to build first, how modules fit together, and how every backend proves it satisfies the public contract.

## Documents

- [Product and API Specification](./product-api-spec.md): public behavior, object models, lifecycle rules, PII policy, and integration surfaces.
- [Backend and Retrieval Specification](./backend-retrieval-spec.md): storage schemas, backend capability matrix, retrieval semantics, Chunkshop mapping, and pg-raggraph boundaries.
- [Testing and Benchmark Specification](./testing-benchmark-spec.md): unit, contract, integration, benchmark, recall, PII, and performance verification gates.
- [Implementation Execution Plan](./implementation-execution-plan.md): milestone order, file ownership, dependencies, and exit criteria.
- [Build Backlog](./build-backlog.md): ticket-sized implementation tasks for the first build wave.
- [Runtime Agent Memory Architecture Spec](./runtime-agent-memory-architecture-spec.md): prior-art lessons, architecture treatment matrix, WorkGraph specs, adapter health, scheduling, and benchmark tasks.

## Build Rule

No milestone is considered done until its spec section, tests, docs note, and benchmark impact are either implemented or explicitly marked not applicable with a reason.
