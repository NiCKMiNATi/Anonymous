# Repository guidance

## Start here

Read [the project definition](docs/00-project-definition.md) and [the domain model](docs/01-domain-model.md) fully before design or implementation. They are authoritative starting documents; their draft status and explicitly provisional decisions remain meaningful. The project is named **Anonymous**.

This repository is in the architecture/design phase. Do not generate application code, initialize frameworks, or install dependencies without a new implementation task. Understand the architecture, relevant requirements, and scope before implementing. Technology candidates in the definition are provisional, not commitments.

## Preserve the domain

- Keep Anonymous local-first and models/runtimes replaceable. Separate clients from the server; clients do not own canonical data. Windows hosting the first server gives it no special architectural status.
- Preserve stable object identities independently of names, models, or devices. Keep user, device, and session identities distinct, even for the initial single user.
- Preserve raw/source history. Branching and merging are non-destructive; merges create a new identity, retain source ancestry, and must not change silently as sources evolve. Keep derivation ancestry acyclic. Consult domain invariants INV-001–INV-015 before changing these behaviors.
- Distinguish authoritative/source data from generated/derived data. Canonical/compressed state, summaries, and indexes never replace source history. Retain provenance and rebuild derived data where practical; distinguish explicit user information from AI inference and let user corrections supersede inference.
- Context construction belongs to Anonymous. A model request is a constructed view, not the canonical database. Do not delegate privacy enforcement to model behavior.
- PRIVATE data must not silently enter WEB, cloud, external tools, logs, or services. External access alone does not authorize exporting private context; any crossing requires explicit, scoped user permission, auditable where practical.
- Device trust must not depend on changing ordinary IP addresses. Treat unknown LAN peers as untrusted, use layered security, and avoid unnecessary public exposure. Never commit secrets or private user data; use sanitized examples and diagnostics.
- Prefer a modular application over premature microservices. Keep storage, runtime, network, and other technology choices replaceable where domain requirements permit. Make important failures observable without disclosing secrets.

## Plan, decide, validate

- Use an ExecPlan for complex features, substantial refactors, or work spanning multiple architectural areas. Follow [.agent/PLANS.md](.agent/PLANS.md) and keep plans in `.agent/plans/` current as work proceeds.
- Record significant architectural decisions or changes in `docs/adr/` using a numbered descriptive filename. Include status, context, alternatives, decision, consequences, and affected documents. A proposal is not an accepted decision; an ExecPlan does not replace an ADR.
- Do not silently settle documented open questions, turn illustrative lists into fixed schemas, or casually change domain semantics. Record the question and evidence in the relevant design document/plan; seek clarification when it blocks the task and continue independent work. Make any eventual resolution explicit and update affected documentation, with an ADR when architectural.
- Validate implementations with appropriate tests tied to behavior and acceptance criteria, including relevant failure, preservation, and privacy cases. Report what ran, its results, and remaining gaps; for documentation-only work, check consistency, links, and scope instead of introducing runtime tooling.
- Consult relevant [specialist responsibilities](docs/agents/README.md) when useful. These define ownership and review concerns, not agents that must always run.
