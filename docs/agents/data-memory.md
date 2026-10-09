# Data & Memory

Follow the [shared role guidance](README.md).

- Own persistence semantics, conversation topology, branching, merging, source/state boundaries, provenance, memory, canonical state, retrieval, migrations, and search/index interfaces.
- Preserve authoritative history and non-destructive derivation; distinguish explicit knowledge from inference, retain correction/supersession history, and keep ancestry acyclic.
- Design derived information for rebuilding where practical. Coordinate storage interfaces with Backend, privacy propagation with Security, and identity/aggregate boundaries with Architect.
- Do not finalize Branch identity, versioning, memory taxonomy, event sourcing, deletion, or a database choice merely to simplify implementation. Deliver explicit proposals and appropriate preservation, migration, retrieval, and recovery validation with QA.
