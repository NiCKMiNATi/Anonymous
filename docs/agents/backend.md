# Backend

Follow the [shared role guidance](README.md).

- Once implementation begins, own the Python/FastAPI server area under `server/`: APIs, application services, model adapters, background processing, and server-side integration. This reflects the provisional direction, not framework initialization or permanent commitment.
- Keep client contracts independent of runtime providers; coordinate persistence semantics with Data & Memory and interface changes with Frontend and Architect.
- Preserve history, provenance, and privacy boundaries through context construction and execution. Make failures observable using sanitized diagnostics.
- Deliver scoped server changes, documented contracts, and appropriate service/integration tests; seek Security review for trust-boundary changes and QA input on failure scenarios.
