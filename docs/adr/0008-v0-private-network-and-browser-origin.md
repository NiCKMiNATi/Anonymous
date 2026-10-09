# ADR-0008: V0 private network and browser origin

**Status:** Accepted for V0 design; configuration and actual-device acceptance pending.  
**Date:** 2026-10-04.

## Context

Anonymous needs private remote access from Windows, macOS and iPhone over shared LAN, mobile and Pocket Wi-Fi networks without a required public listener or new paid subscription. The project permits responsive browser clients. ADR-0001/0005 require equal client authority and provisioned local operation without cloud authentication. Ordinary network addresses cannot identify trusted devices.

## Alternatives

- Tailscale provides documented cross-platform encrypted direct/relay connectivity and device approval; remote operation depends on external coordination/account services.
- Plain WireGuard supports encrypted peers and roaming but this deployment has no verified reachable endpoint. Providing a hub/discovery/relay arrangement would add operational and possible cost dependencies.
- LAN-only access cannot satisfy remote use.
- Tailscale Serve or publicly issued HTTPS certificates could simplify client trust, but couple the chosen serving/renewal path to external infrastructure. A private CA adds custody/trust-installation work while permitting independent offline operation.
- Desktop wrappers/native clients add unrequired packaging and credential integrations; native mobile is outside V0.

## Decision

Use a responsive browser client, targeting maintained Edge on Windows and Safari on macOS/iPhone for initial acceptance. Select Tailscale for remote private reachability, with explicit network-device approval and least-privilege application-only grants. Network membership is never Anonymous authentication. Provider enrollment/removal remains separate from Anonymous enrollment/revocation.

Serve frontend and logical API from one Anonymous-owned HTTPS origin. Terminate TLS independently of Tailscale. Use a dedicated operator-managed private CA, offline signing key and explicitly verified client trust. Use the configured server MagicDNS FQDN remotely and the same hostname/port resolved to loopback on the server host. The Windows browser follows the same application authentication path. No wildcard/LAN/public core listener or cloud fallback.

Require verified server identity, TLS 1.3 or maintained TLS 1.2, exact host/origin handling, and finite certificate validity. Actual hostname/port, supported versions, CA custody/renewal and offline local behavior remain bounded configuration/validation prerequisites. They are not existing configured facts. No framework, proxy product or certificate tooling is selected.

## Consequences

This fits the existing three-device personal environment and retains transport replaceability. Tailscale's documented free Personal plan currently fits, subject to eligibility/terms recheck. Remote connectivity can fail with provider/network outages; provisioned Windows loopback authentication/chat must remain usable without its daemon. Network/account metadata is infrastructure-visible; application TLS terminates only in the trusted host.

Private CA custody is substantial operational responsibility. A stolen root key can impersonate services trusted by those clients. No CA or other key is generated; owner custody and three-client trust tests are mandatory before provisioning. DNS/origin changes require deliberate client/certificate migration, not new domain identities. Tailscale is selected on documented fit, not measured reliability.

## Evidence and affected documents

The [evaluation sections 2–4, 10 and 13](../evaluations/v0-access-security-mechanisms.md) contain the official vendor sources, comparison, exposure matrix and outstanding evidence. This decision refines SD-05/06 in [security](../07-security.md) and the provisional transport/client choices in [architecture](../04-architecture.md), preserving [V0 scope](../03-v0-scope.md). No earlier ADR is superseded.
