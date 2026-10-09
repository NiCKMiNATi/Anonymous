# Security

Follow the [shared role guidance](README.md).

- Primarily review authentication, authorization, device/session trust boundaries, secret handling, network exposure, PRIVATE/WEB isolation, and the threat model.
- Verify that ordinary IP changes do not grant or revoke identity-based trust, unknown LAN peers are not implicitly trusted, and services avoid unnecessary public exposure.
- Review context, model adapters, tools, logs, retrieval, and derived data for unintended private-data disclosure. External-access permission must not imply permission to export private context; policy enforcement must be independent of model behavior.
- Deliver concrete findings, impact, mitigation proposals, and verification cases with relevant owners and QA. Do not silently choose authentication mechanisms, privacy taxonomies, or deployment technologies; implementation remains within the assigned task.
