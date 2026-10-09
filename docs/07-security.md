# Anonymous — V0 Security Design & Threat Model v0.1

**Status:** Security design baseline v0.1. Logical controls below are accepted for this design; concrete mechanisms, operating parameters and implementation evidence remain open gates. This is not approval to deploy or use real private data.  
**Date:** 2026-10-03.  
**Ownership:** Security with Architect coordination; focused author reviews in section 16.

## 1. Authority, purpose and decision boundary

This document develops the security portion of [Requirements](02-requirements.md) (RB), [V0 Scope](03-v0-scope.md) (V0), [Architecture](04-architecture.md) (AB) and [Logical Data Model](05-data-model.md) (LM). The [Project Definition](00-project-definition.md) and [Domain Model](01-domain-model.md) remain authoritative starting documents, including their draft/provisional distinctions. [ADR-0005](adr/0005-layered-private-access.md) already establishes layered private access. [ADR-0007](adr/0007-access-invalidation-and-owner-recovery.md) records the narrower new lifecycle decisions. The [ExecPlan](../.agent/plans/2026-10-03-v0-security-design.md) records scope and checks.

V0 has one primary user, one authoritative modular server application, Windows/macOS/iPhone clients and one server-private local model runtime. All conversation content, output, context and provenance is PRIVATE. There is no WEB/cloud/tool execution, private-release operation, public self-registration, general multi-user role system, offline write synchronization or user-visible deletion. Authorized remote clients remain inside the private application boundary. Windows co-hosting grants no client privileges.

This baseline defines assets, threats, controls and observable security outcomes. It does not select an authentication protocol, credential format, database, framework, OS secret store, transport provider, TLS termination arrangement, runtime or concrete API. Section 14 assigns open decisions to explicit gates; document completion does not mean Q-21 or LM LD-07 is fully resolved. No implementation or hardware benchmark is included.

## 2. Assets, adversaries and assumptions

| Asset | Protection needed | Authoritative owner |
| --- | --- | --- |
| Source and saved assistant history, commit instants and canonical order | Confidentiality; no unauthorized mutation/loss; preserved original attribution. | C04/C05 under C09 through C08. |
| Boundaries, message/run/model/runtime references and operation correlations | Private relationship integrity; an identifier is never access permission. | C05/C08; current authorization from C03. |
| User, Device and Session identities and lifecycle | No spoofed ownership, unauthorized enrollment, revived invalid session or address-based trust. | C03/C08. |
| Authentication, provisioning and recovery material | Confidentiality, narrowly scoped use, invalidation and protected lifecycle. | C03; deployment/client custody through C10/C01. |
| Constructed context, provisional output and client views | PRIVATE treatment; safe presentation; no external fetch/execution side effects. | C06/C07/C05/C02/C01. |
| Access availability and truthful outcomes | Access enforcement remains usable within the supported resource envelope; uncertainty is not success. | C02/C03/C05/C10. |
| Configuration, binaries/models and operational evidence | Trusted changes, bounded execution authority and sanitized diagnostics. | Owner administration and C10/C07/C08. |

Relevant adversaries include an unknown LAN/public peer; an overlay peer lacking application approval; a malicious website visited on an approved device; a caller manipulating IDs, headers, clocks or submission contents; a thief holding a valid session/device credential; and adversarial user/model text. Misconfiguration, lost acknowledgments, stale access caches, process death, unavailable storage and compromised dependencies are also failure causes.

The operator-controlled host, operating system, selected application code and protected administration form the trusted computing base. A fully compromised administrator/kernel can read memory or replace enforcement; V0 does not claim isolation from that attacker. Authorized clients can retain received information, and compromised clients can misuse current authority until containment. These limits do not excuse preventable exposure to ordinary LAN peers, untrusted origins or lower-privilege local accounts.

Device authentication proves continuity of the selected credential/approved endpoint relationship, not an unforgeable physical chassis identity. Copyable credential theft can impersonate that device until invalidation. Fingerprints, names, client-supplied IDs and ordinary IP addresses are insufficient proof. Hardware binding must not be claimed without evidence.

Actual OS/browser versions, client packaging, origins, network provider and runtime remain unverified. At-rest theft protection, encryption and backup-copy handling need SD-07 decisions before real private use. No traffic-analysis anonymity, secure deletion, disaster recovery, certification or penetration-test completion is claimed.

## 3. Trust boundaries and permitted flows

Diagram 1 — arrows show application flow, not implicit trust:

```text
Windows / Mac / iPhone client       unknown LAN / public / overlay peer
              |                                    |
              +---- protected private reachability-+
                                   |
                         C02 ingress validation
                                   |
                    C03 user + device + session
                       + operation/resource permission
                                   |
                    C04/C05 application authority
                         |                  |
                 C08 private state   C06 eligible context
                                            |
                                      C07 local runtime
                                            |
                                      untrusted output
                                            |
                   result + current C03 delivery check
                                            |
                              C02 --> C01 safe presentation

No application-content path to WEB/cloud/tools/external reporting.
Missing current authority at a gate --> deny; no protected state disclosure.
```

| Boundary | Required treatment | Owner / gate |
| --- | --- | --- |
| Network to application | Confidentiality/integrity and authenticated server destination; reachable peers still need application authority. | C02/C03/C10; SD-01/05. |
| Client to use case | Validate untrusted identity claims, content, targets and clocks at the operation, not just a login screen. | C02/C03/C04/C05. |
| Application to runtime | Only authorized constructed input; no database access, arbitrary endpoint, credentials, tools or cloud fallback. | C06/C07/C10; SD-08. |
| Runtime to application/client | Generated text has no command/access authority; attribute it to the producing attempt and render as data. | C05/C02/C01. |
| Application to persistence | Server-owned access/history facts, coherent transitions and current permission; logs cannot replace durable authority. | C03/C05/C08; SD-04/07. |
| Private application to infrastructure | Identify intermediary payload access, key custody, metadata, enrollment/recovery trust and outage dependencies. | C10/Security; SD-05. |

Relay/control-plane visibility into addresses, peer associations, timing or sizes depends on the selected system; no provider behavior is asserted. Infrastructure is not authorized to receive plaintext conversation content. A component terminating payload protection becomes part of the trusted private deployment and must be identified. Untrusted request headers cannot elevate a caller into that role.

## 4. Threat register

These are design risks, not discovered implementation vulnerabilities. Every threat must be addressed before its affected capability is enabled; no speculative severity score or exploit probability is assigned.

| ID | Threat and consequence | Controls / owner | Future check |
| --- | --- | --- | --- |
| TH-01 | LAN/overlay presence, old address or forged device ID grants history access. | SG-01/02; C02/C03. | ST-01/02. |
| TH-02 | Stolen, fixed, replayed or expired session grants continued authority; reapproval revives it. | SG-03/04; C03/C08. Theft before detection remains a risk. | ST-03/04. |
| TH-03 | First reachable caller claims ownership; missing state or recovery reset creates an attacker owner. | SG-03; C03/C08/C10. | ST-05/06. |
| TH-04 | Guessed IDs, correlation reuse or historical permission bypass discloses/mutates a target. | SG-02/05; C03/C04/C05. | ST-01/07. |
| TH-05 | Revocation races admission, buffers, cache reads or reconnect; old output continues. | SG-05/06; C02/C03/C05/C08. | ST-08/09. |
| TH-06 | Browser request forgery, hostile origin/host or proxy-header spoofing acts with owner authority. | SG-07/08; C01/C02/C10. | ST-10/11. |
| TH-07 | Stored user/model text executes script, loads an external tracker or triggers a tool. | SG-08/09; C01/C06/C07. | ST-12/13. |
| TH-08 | Runtime destination substitution, telemetry or package behavior exports context or reaches the store. | SG-09; C07/C10. A separate process is not automatically isolated. | ST-13/14. |
| TH-09 | Secrets/private text leak through logs, errors, URLs, dumps, client caches or backups. | SG-08/10; C01/C02/C03/C07/C08/C10. | ST-12/15. |
| TH-10 | Clock adjustment, state failure, process death or rollback restores invalid authority. | SG-04/06/10; C03/C08/C10. Backup rollback is not a V0 recovery guarantee. | ST-04/09/16. |
| TH-11 | Oversized input, repeated authentication or many conversations exhaust resources and prevent revocation. | SG-11; C02/C03/C05/C10. | ST-17. |
| TH-12 | Remote infrastructure/cloud dependence blocks provisioned local authentication; fallback weakens protection. | SG-07/12; C03/C10. Remote outage may still prevent remote use. | ST-18. |

## 5. Access decision and operation permissions

**SG-01 — Reachability is not authority.** All clients use the same protected contract. Signed-out localhost access, unapproved user/device pairing, old trusted IP and overlay membership each fail independently. The server resolves proof to its own user/device/session associations; caller-supplied associations are claims to verify.

**SG-02 — Current, scoped permission.** Before exposing private state or accepting an operation, C03 establishes the valid primary-user context, approved device, valid session, capability and resource ownership. C04/C05 cannot accept a client-selected owner override. Unknown authority denies access. Apply this to old operation lookups, pagination, provisional output and run/source metadata. An ID, input boundary, timestamp or earlier accepted request is insufficient.

This follows deny-by-default and every-request authorization guidance; Anonymous adds its device, ownership and delivery obligations. [OWASP Authorization](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html)

| Operation | Necessary authority and coherent outcome | Denial behavior |
| --- | --- | --- |
| Create/list/open/read history or provenance | Valid approved session; owned targets; returned metadata within that scope. | No private content/existence details or mutation. |
| Send or explicit retry | Above plus current C05 eligibility/admission; replay resolves only an authorized existing operation. | No unauthorized append, queued work or inference; admitted work is reconciled, not erased. |
| Reconcile/receive saved or provisional result | Current recipient session/device/resource permission, even if another session initiated it. | No further delivery; saved history remains intact. |
| Logout | Invalidate the selected session; replay cannot alter another session/device. | Local client clearing alone does not confirm server invalidation. |
| Approve/revoke/restore device or change owner authenticators | Explicit primary-owner intent, management authority and current target state; fresh owner proof under SD-02/03. | No self-approval, silent retargeting or model-authorized trust change. |
| Provision first owner or recover all lost devices | Dedicated controlled owner proof under section 6. | Reaching the ceremony grants no history or management access. |
| Change runtime/deployment/secret configuration | Trusted operator administration outside ordinary chat. | Chat input, model output and client parameters cannot perform it. |
| WEB/cloud/tool/private release, arbitrary file/store access | No V0 application capability. | Unsupported; no implicit fallback. |

Invalid credentials/inaccessible resources must not reveal private target details through helpful errors. Authorized users still need actionable expiry, uncertainty and recovery states. No timing-side-channel elimination is claimed; concrete error shaping is SD-09. OWASP similarly warns against authentication error differences that disclose account state. [OWASP Authentication](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html)

## 6. First owner, device approval and recovery

**SG-03 — Controlled trust creation; no automatic revival.** “Uninitialized” must be positively established for an intended new dataset by trusted administration. It cannot mean an empty result after failed access-state reads, missing configuration or failure to locate an existing dataset. Ordinary clients cannot race to become owner. Existing data with unavailable ownership remains closed for recovery.

Diagram 2 — provisioning and trust lifecycle (logical states, not a persisted enum):

```text
positively new dataset + controlled owner proof
                    |
             coherent first-owner/device establishment
                    |
           normal registration closed

unknown device --> owner-approved enrollment --> approved device --> revoked
                                                     ^                 |
                                                     +-- explicit owner restoration
                                                          + fresh valid session

lost/unknown access state --> protected recovery; never automatic first-owner mode
invalid old session ------> remains invalid, even after device restoration
```

Required ceremony outcomes:

1. Bind one stable primary user to the intended dataset and first approved device. Provisioning proof is purpose-scoped and cannot be replayed to create another owner/unrestricted session. Races/conflicts are observable; no first-request-wins rule.
2. Bind additional approval to the intended endpoint proof, not a device name or claimed ID. An unapproved client receives no history preview. The existing owner or controlled recovery context authorizes the transition.
3. Establishment, consumption of provisioning authority and registration closure must be coherent. Lost acknowledgment resolves the existing establishment; incomplete/uncertain state stays closed.
4. Restoration requires explicit owner action against current state. Replaying an earlier approval/restoration returns its original outcome and cannot undo later revocation. Old invalidated sessions remain unusable. Suspected stolen credentials must be addressed rather than trusted again by default.
5. All-devices-lost recovery uses separately verified owner proof, never guessed conversation facts or model answers. Preserve user/conversation identity, order, commit instants and provenance. Replacing compromised authenticators invalidates dependent old authority coherently; the affected scope must be explicit.

Concrete proof remains open: owner-held offline recovery material, an authenticated host-administration ceremony or another reviewed local mechanism may qualify. Physical proximity/localhost reachability alone does not. SD-02 must select custody, replay handling, recovery and usability before provisioning implementation. No generic bypass/default password is specified. Trusted host administration is an operational assumption, not a Windows chat privilege.

## 7. Session validity and device continuity

**SG-04 — Finite, server-enforced validity.** A Session is associated with an authenticated user and approved device, not synonymous with either. Proof mechanisms may be related, but a claimed device ID is not proof. Concurrent sessions remain distinguishable; ordinary address change alone cannot redefine device trust.

Logout, expiry and device revocation irreversibly end the affected session's authority. Reauthentication establishes fresh session authority; device restoration cannot resume invalid material. Renewal/rotation cannot bypass current revocation or replay an invalid predecessor. No token/cookie/JWT/certificate representation is chosen.

Only server-established session authority is accepted. Authentication or privilege change must not promote attacker-chosen pre-authentication material into a valid privileged session. Concrete proof generation/rotation and anti-fixation behavior are SD-01/03 design obligations.

Policy must define a finite absolute validity ceiling, renewal conditions, idle behavior and fresh proof for sensitive trust changes. Activity/silent renewal cannot create indefinite validity without renewed authentication. Durations, long-generation idle treatment and rotation overlap remain SD-03; arbitrary values do not demonstrate security/usability on actual clients. Server-side expiry/invalidation and renewed authority after sensitive changes are supported by [OWASP Session Management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html).

Check expiry at protected admission and delivery, not only connection establishment. A session may end while already admitted work finishes/saves privately; another authorized session can reconcile it. Reauthentication cannot implicitly resubmit a new message intent.

Use a documented server-controlled time/elapsed-time policy across restart, suspend and clock changes. Client timezone, message commit timestamps and canonical order are never expiry authorities. Backward clock adjustment cannot revive an invalid session. If validity cannot be established after restart, deny access or require reauthentication. Persistence versus conservative invalidation of otherwise valid sessions on restart remains SD-03/04.

## 8. Revocation, concurrent admission and protected delivery

**SG-05 — Access checks govern acceptance, not merely receipt.** C03/C04/C05 establish a coherent order between invalidation and new protected admission. An earlier-arriving request not yet admitted has no grandfathered authority. A mutation admitted before invalidation may finish its authorized coherent unit; this grants neither another action nor later delivery. Contracts must distinguish accepted work from a request merely queued.

**SG-06 — Invalidation is effective before acknowledgment.** Confirm logout/revocation only after durable invalidation and enforcement against subsequent protected admission/delivery. Device revocation covers all its sessions; logout covers the selected session. Stale cached allow decisions cannot bypass it. Failed/uncertain persistence or enforcement cannot produce success; block affected access while uncertain and expose a sanitized management/reconciliation outcome.

Diagram 3 — invalidation boundary:

```text
owner intent --> current authority/target check
                             |
                deny new affected admission/delivery
                             |
                confirm durable invalidation + enforcement
                             |
                  acknowledge effective revocation
                             |
             later affected admission/delivery denied

already admitted run --> may finish/save privately --> other authorized session
lost acknowledgment --> reconcile same change under current management authority
```

Cover ordinary responses, incremental output if offered, cached/history reads, reconnects and queued application output. Permission to construct a response is not permission to release it later. Coordinate current authorization and release to the controlled transport boundary with invalidation, preventing a check-then-send race. This selects no lock, lease or transaction mechanism.

Bytes released into transport before invalidation may arrive later and cannot be recalled. Do not call an application buffer “already delivered,” or claim that closing a socket prevents earlier bytes arriving. Adapters must identify their actual release boundary and prove stale application output cannot be released after acknowledgment. Receiver arrival time alone is insufficient; ST-08 captures server release/invalidation order.

Acknowledged invalidation survives intact-storage process restart. Lost acknowledgment reconciles the original result. An unconfirmed transition may or may not have committed; neither UI state nor logs prove success. Recover authoritative state before affected access. A session invalidated by its own operation cannot later read private confirmation using only its old correlation; use another permitted context or controlled recovery.

No cancellation feature, deletion or automatic retry is introduced. C05 independently reconciles surviving runtime work and uncertain publication under LM-07/CB-05/06. Revocation cannot turn unknown execution into known failure, release busy admission incorrectly or authorize a second generation.

## 9. Protected deployment and network behavior

**SG-07 — Explicit private endpoints and intermediary trust.** Record listening application/runtime/store/administration surfaces, allowed client origins, endpoints, server-identity validation and trusted termination points before protected use. Clients reach only the intended private application boundary. Runtime/store remain server-private; ordinary clients and unknown LAN/overlay peers cannot call them directly. Local binding is containment, not application authentication.

Observers must not read or successfully modify accepted payloads. A browser deployment needs a validated secure origin and compatible credential protections; bypassing identity/certificate errors is not an operating procedure. The complete path, including termination-to-application hops, needs a protection story. Follow maintained TLS guidance when selecting that mechanism; no version/cipher/certificate deployment is finalized here. [OWASP Transport Layer Security](https://cheatsheetseries.owasp.org/cheatsheets/Transport_Layer_Security_Cheat_Sheet.html)

Only specifically trusted ingress may supply security-relevant proxy metadata; it replaces untrusted copies. Validate configured destination/origin expectations rather than arbitrary host/forwarding claims. Direct ingress must not bypass protections. DNS/address changes do not redefine Device identity.

Before remote access, document infrastructure peer enrollment, payload/metadata visibility, key custody/recovery, update trust, outage behavior and recurring-cost dependencies. No Tailscale/provider behavior is assumed. Public forwarding/debug/runtime endpoints are not prerequisites. A control-plane outage cannot justify public or unauthenticated fallback.

**SG-12 — Provisioned local use remains independent.** With external services unavailable and the private local path intact, an already provisioned device must authenticate and complete the chat lifecycle. Expose transport/certificate provisioning or renewal/recovery dependencies; no hidden cloud identity dependency in local authentication. This does not promise disconnected remote access.

## 10. Browser/client security and private presentation

**SG-08 — Displayed content is untrusted data.** User and assistant content may contain malicious markup/links. V0 text chat needs no executable content: preserve saved text exactly while rendering it safely as data. Any future rich formatting requires a reviewed constrained renderer; no active HTML, scripts, frames, external media, link previews or executable code actions. External URLs in message content remain inert in this baseline; external navigation/private release is not a V0 application capability. Do not embed third-party scripts, fonts, analytics or reporting that could receive private context.

Safe text handling/context-appropriate encoding is the primary rendering protection; content-security policy is an additional layer. Renderer and policy remain SD-06. [OWASP Cross Site Scripting Prevention](https://cheatsheetseries.owasp.org/cheatsheets/Cross_Site_Scripting_Prevention_Cheat_Sheet.html)

Browser authentication must address request forgery, origin/host validation, framing and connection initiation. If ambient cookies are selected, explicit anti-forgery controls and cookie scope/security attributes are design prerequisites. Origin allowlists/CORS are not authentication. SameSite is not assumed sufficient without a justified deployment analysis; read-only navigation cannot hide state changes. Persistent streaming connections, if selected, need protected handshakes and continuing message/delivery authority. This does not select cookies, CORS configuration or WebSockets. [OWASP CSRF Prevention](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)

Protected content must not leak through shared caches, public URLs, notifications or diagnostic previews. Credential/cache policy must cover back navigation, suspended tabs, logout, expiry, offline views and device loss. Once informed of invalidation, the supported client stops protected operations, clears its displayed private view and avoids automatic replay after login. It cannot erase screenshots, unmanaged OS/browser copies or data retained by a compromised client. No disconnected-write/cache product is introduced; concrete caching and custody remain SD-06/07.

Keep authorship, provisional/saved/uncertain states and continuously visible FR-15 time near actions without hover. Expiry and message commit time have different meanings; changing timezone cannot alter canonical history or server authority.

## 11. Model/runtime, context and external-transfer containment

**SG-09 — No model-controlled effects.** C06 constructs only the authorized current-conversation view under V0-D01 with actual input attribution. Content asking for web access or claiming owner/system authority cannot change C03 policy, select destinations, invoke tools, alter trust or access another conversation. Roles come from server records, not instructions inside content. Privacy never depends on model compliance.

C07 uses only approved local runtime configuration from trusted composition. Requests cannot supply arbitrary URLs, paths, executables or download instructions. Runtime failure has no external fallback. Output returns through its producing attempt; it cannot choose recipients, publish history directly or become executable markup.

Installation/model acquisition are separate operator tasks. Before private invocation, assess selected runtime/package provenance, effective network/file permissions, telemetry, updates, prompt caches and supervision. Application-level “no tools” is insufficient if the runtime has unrestricted egress or ambient store/secret access. A separate process is not a sandbox. Missing containment evidence is an SD-08 blocker, not proof of safe defaults. A fully compromised trusted host remains outside the guarantee.

Only supplied context is intentionally shared with the runtime, without application secrets or unrelated conversation contents. Errors/debug traces/runtime caches also receive PRIVATE treatment. Replacement must revalidate security without rewriting historical model/run identities or provenance.

## 12. Secrets, persistent access state and observable failures

**SG-10 — Minimize secret-bearing surfaces.** Use authentication/recovery material only for its protected operation. Exclude it from ordinary URLs, history, source references, prompts, consoles, repository files, generic errors and telemetry. Operational correlation must not contain reusable credentials. Client custody and server verification/storage remain SD-01/07; protection from compromised-host memory reads is not claimed.

This governs application-managed credential handling; it is not a promise to detect every secret deliberately pasted into ordinary user content. Such submitted content remains PRIVATE under the ordinary history/context rules. No automatic source redaction or mutation is introduced to claim a stronger guarantee.

Protect access/history state, configuration and diagnostics from unauthorized OS principals. Application authorization is not at-rest encryption. State which theft/backup/local-account threats selected protections address, what remains exposed on an unlocked host, and how recovery preserves ownership. Do not claim encryption protection without configured/tested evidence.

Retain minimal operational evidence for establishment, approval/revocation, session invalidation and recovery: responsible authorized context where known, target relationship, operation kind, confirmed/failed/unknown disposition and safe correlation. This is not a full event store or indefinite login journal. History/run retention remains V0-D03; security-log retention/access and failure-volume bounds are SD-09. Logs cannot establish canonical access-state success. OWASP likewise distinguishes useful event evidence from secrets/sensitive data that should be excluded or protected. [OWASP Logging](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html)

Runtime/third-party errors are untrusted: bound size, prevent diagnostic injection and suppress raw payloads. A logging outage cannot leak rejected content into fallback channels. Optional diagnostic failure need not erase history or halt an otherwise durably authorized operation; missing required access/durability evidence does block it. No external incident reporting is introduced.

Suspected compromise uses remaining authorized management or controlled recovery to invalidate affected authority. Preserve saved history; already received data cannot be recalled. Copying a stale database over live access state is not an approved recovery method. Future backup/restore must prevent reviving revoked credentials and remains outside the intact-storage process-restart guarantee.

**SG-11 — Bounded work without security starvation.** Reject malformed/unsupported or over-limit input before expensive work. Bound authentication/provisioning attempts, input/output, connection buffers, logs and global generation resource use. One generation per conversation is not a global exhaustion control. Limits/timeouts need actual configuration/runtime evidence under SD-09; no numbers are invented. Saturation cannot enable fail-open access, silent source pruning, unlimited queues or ineffective revocation. Single-host availability limits must be stated rather than promising resistance to all denial of service.

## 13. Mechanism alternatives and selection evidence

These are comparison dimensions, not implementation defaults. A choice must satisfy the whole lifecycle; familiarity with a library/product is insufficient.

| Decision area | Alternatives to evaluate | Required selection evidence |
| --- | --- | --- |
| Session proof | Server-resolved opaque proof versus self-contained signed proof with current invalidation checks. | Immediate device-wide invalidation, logout/expiry, replay/rotation, restart/clocks and client custody. Signature validity alone is insufficient. |
| User/device authentication | Reviewed owner authentication with independently verifiable approved endpoint association; evaluate proof mechanisms available on actual clients. | Distinct identities, rejection of unapproved devices, no IP binding, theft limits, local offline operation and recovery. No assumed physical hardware binding. |
| Bootstrap/recovery | Owner-held offline proof, controlled authenticated host ceremony or another reviewed local method. | Race resistance, intended dataset/device binding, loss/theft/replay, all-devices-lost recovery and no public reset; owner custody/usability choice. |
| Client delivery/credentials | Reviewed secure-origin browser delivery/credential transport versus later native protected custody. | Actual three-client compatibility, forgery/origin controls, connected-session expiry, no cloud login and safe caching. Native development is not selected. |
| Private transport | Private connectivity plus validated endpoint protection; layering/termination depends on deployment. | Threat/metadata/key-custody inventory, roaming, local offline behavior, no public exposure and actual cost/dependency evidence. |
| Storage/process protection | Host protections and least-privilege custody with encryption/isolation selected for declared threats. | Unauthorized-account rejection, key recovery, runtime containment and honest compromised-host limits. |

No database/ORM, certificate system, credential format, cryptographic algorithm, OS API, port, API route or vendor is fixed. SD-01–09 require explicit mechanism decisions and validation before affected implementation/use. SD-10 must not expand V0 through deferred features.

## 14. Open decisions and readiness gates

These refine Q-21, relevant Q-10/12/13/16/18/19/23/24, and LM LD-03–08/11–13. Original questions/source documents remain unchanged. Each intentionally unresolved mechanism belongs to a group below.

| ID | Open issue and why | Owner / next artifact | Blocking point |
| --- | --- | --- | --- |
| SD-01 | User/device/session proof, binding, credential transport/verification. Client technology and actual support are unestablished. | Security + Backend/Frontend; mechanism ADR and access contract. | Before authentication/access-capable implementation. |
| SD-02 | First-owner/all-devices-lost ceremony, proof custody/replay, compromised-proof replacement and fresh owner evidence. Usable custody cannot be assumed. | Security + owner/Architect; provisioning/recovery ADR and procedure. | Before provisioning/recovery implementation; no open-bootstrap substitute. |
| SD-03 | Absolute duration, idle/renewal/rotation, management freshness and restart/clock policy. Needs actual-client usability/security decisions. | Security + Backend/Frontend; session policy and failure cases. | Before session implementation; finite parameters tested before use. |
| SD-04 | Admission/invalidation/publication coherence, controlled transport release, caches and restart enforcement. Logical outcomes do not prove mechanisms. | Backend + Security/Data & Memory; persistence/transport concurrency contracts. | Before protected saving/delivery implementation. |
| SD-05 | Transport, validated origins/server identity, termination, proxy metadata, interfaces, infrastructure trust/keys, cost and outage dependencies. No deployment/provider verified. | Architect + Security; deployment ADR and environment inventory. | Protected local path before access-capable use; remote-specific choices before remote connectivity. |
| SD-06 | Actual browser/native configurations, renderer, forgery/origin/framing controls, credential/cache behavior and reconnect UX. Platforms/framework provisional. | Frontend + Backend/Security; client/API security contract. | Before protected-client implementation and supported-client acceptance. |
| SD-07 | OS/process permissions, secret custody, at-rest theft protections, dumps/copies and backup-key recovery. Host protections unverified. | Security + Data & Memory/Architect; storage/deployment decision and custody procedure. | Before credentials/real private data; backup claims need separate scope/evidence. |
| SD-08 | Runtime/package provenance, file/network permissions, telemetry/caches and effective containment. Runtime unselected/unmeasured. | Backend + Security; runtime feasibility/security evidence and deployment decision. | Before private context reaches a live runtime. |
| SD-09 | Finite abuse/size/buffer/log limits, evidence retention/access, safe errors and incident procedure. Hardware envelope/contracts pending. | Backend + Security/QA; operational policy and load evidence. | Before affected access/execution implementation; load validation before release. |
| SD-10 | Rich privacy taxonomy, external consent/audit, tools, multi-user policy, Memory privacy and deletion/backup erasure. Product capabilities deferred. | Future scope, then Security/Data & Memory/API design. | Not a PRIVATE-only V0 blocker; mandatory before expansion. |

The design is reviewable now. **Access-capable implementation is not ready** while applicable SD-01–09 choices are unspecified. Runtime evidence and detailed backend/persistence contracts are separate prerequisites. The deferred Memory subsystem need not be designed first.

## 15. Traceability and future verification

All 11 selected security/privacy subsets are mapped below. This does not replace the full V0 acceptance suite.

| Selected requirement | Controls | Acceptance / future cases |
| --- | --- | --- |
| SEC-01 | SG-01/02/03/04. | V0-AC-05; ST-01/05. |
| SEC-02 | SG-02/03/05/06. | V0-AC-05/10; ST-01/06/07/08. |
| SEC-03 | SG-01/04/07. | V0-AC-04/05/10; ST-02/03. |
| SEC-04 | SG-03/04/06. | V0-AC-10; ST-03/08/09. |
| SEC-05 | SG-04/06. | V0-AC-10; ST-03/04/08. |
| SEC-06 | SG-07/12. | V0-AC-04/14; ST-02/11/18. |
| SEC-08 | SG-09/10. | V0-AC-14; ST-13/14/15. |
| PRIV-01 | SG-07/08/09/10. | V0-AC-09/14; ST-12/13/14/15. |
| PRIV-03 | SG-08/09/10. | V0-AC-09/14; ST-12/13/15. |
| PRIV-04 | SG-02/06/09. | V0-AC-09; ST-09/13/16. |
| PRIV-05 | SG-08/09. | V0-AC-09; ST-12/13. |

SEC-07, PRIV-02 and PRIV-06 remain not applicable because tool/release capabilities are absent; ST-13 verifies absence. Supporting coverage: FR-03/14 (shared owned access), FR-08/12 (eligible context/attempts), FR-15 (formatting never changes commit instant/access validity), NFR-01/04/05/06/07 (local independence, equal clients, actual configuration, bounded responsibilities), DATA-01/02/03/05/07/08 and REC-01–05 (stable preserved sources and execution). V0-AC-01/02/03/06/07/08/11/12/13/15 remain cross-checks through LM.

All INV-001–015 survive: identity/client/runtime 001/002/008/009/010; preservation/ancestry 003/004/005/006/011/014; source/inference/correction 007/013; model-independent privacy 012; constructed context 015. Access invalidation cannot rewrite history or turn a historical boundary into current permission. V0-D01–06 and LM CB-01–07 remain unchanged.

Use synthetic data/credentials only. These are future test specifications, not executed tests. Start with owner device A and distinct sessions A1/A2, approved device B, unknown client U, two distinguishable conversations and a controllable model fixture. Use isolated test endpoints under the tester's control, never public collectors for private fixture content. Capture sanitized admission/release/invalidation evidence, client observations, before/after history and actual configuration.

| Case | Procedure | Objective pass condition |
| --- | --- | --- |
| ST-01 | From U, signed-out Windows and valid user proof without approved device proof, attempt read/list/send/management and guessed IDs; repeat from A1. | Unauthorized cases disclose nothing private and cause no mutation/inference; authorized control works. |
| ST-02 | Change A's address/reconnect; let U reuse the former address. | A retains device identity/trust with valid current session; U inherits none; recorded protected remote path works. |
| ST-03 | Attempt attacker-selected session fixation at login; logout A1, check A2/B, revoke A, explicitly restore it/create A3; replay A1/A2 credentials. | Only server-established fresh authority is accepted; logout affects A1 only; revocation affects both; restoration cannot revive old sessions; history unchanged. |
| ST-04 | Exercise expiry/renewal while reading/generating/reconnecting; change client timezone/server clock and restart. | No invalid-session revival or indefinite renewal without required proof; expiry stops delivery; message instants/order unchanged. |
| ST-05 | Race authorized/unauthorized provisioning, replay proof and lose acknowledgment; then make existing-dataset access storage unreadable. | One authorized establishment; replay resolves it; unreadable existing state never opens enrollment. |
| ST-06 | Approve/revoke/restore, replay old approval after revocation, and exercise valid/invalid all-devices-lost recovery. | Current owner/target intent governs; old replay cannot restore trust; recovery preserves identity/history and invalidates affected old authority. |
| ST-07 | Reconcile accepted submission from unauthorized session; reuse correlation for changed content/target; reauthenticate after lost response. | Correlation grants no authority; permitted reconciliation returns same outcome without duplicate inference/history. |
| ST-08 | Pause delivery before release, race revocation, resume; test streaming/final/cached output and late queued requests; repeat logout/expiry with B as control. | No new affected release/admission after effective invalidation/ack; earlier releases distinguishable; B can read saved results. |
| ST-09 | Fail invalidation persistence/enforcement; lose acknowledgment after real success; crash/restart while runtime survives. | No false success; acknowledged invalidation retained; unknown access fails closed; unknown execution is not automatically retried. |
| ST-10 | Hostile test origin attempts state changes, framing and connection initiation using actual browser credentials. | No unintended action/private read; configured-origin control works; UI restrictions alone are insufficient. |
| ST-11 | Spoof host/origin/forwarded identity, bypass ingress, inspect transport and reachable surfaces as untrusted peer. | No gained authority; observer cannot read/alter accepted payloads; no direct runtime/store/client bypass. |
| ST-12 | Save/render hostile markup, links/media and private markers from user/model text; inspect network/cache after logout. | Inert display; no external fetch/execution; source unchanged; recorded cache/logout policy holds. |
| ST-13 | Model demands tool/cloud call, role/destination override, another conversation or private release; fail local runtime. | No unsupported effects/fallback; only eligible context and attributable output. |
| ST-14 | Review runtime/dependency origin, effective file/network permissions and telemetry with synthetic input; attempt direct runtime/store access. | Containment demonstrated; no unauthorized store/secret access/payload egress/client bypass; missing evidence blocks readiness. |
| ST-15 | Exercise auth/provisioning/recovery and runtime/storage/malformed-error paths with secret/private markers; inspect logs/context/URLs/reporting. | No markers on disallowed surfaces; sanitized evidence useful; logs cannot replace durable facts. |
| ST-16 | Deny policy-state access, use stale caches, interrupt startup and supply ambiguous validity evidence. | Protected access denied without fabricated empty history/bootstrap; sources preserved; no unjustified authority. |
| ST-17 | Reach documented input/auth/buffer/global-generation limits across conversations; revoke A under load. | Bounded visible refusal, no pruning/unlimited queue/fail-open behavior; revocation effective within recorded envelope. |
| ST-18 | Disable external services with provisioned local path intact; authenticate/run chat; separately interrupt remote connectivity. | Local flow needs no cloud login/new paid service; remote failure introduces no public/plaintext fallback. |

Before acceptance, mechanism owners record precise configuration/steps, actual outcomes and safe evidence. Documentation coverage is not proof on the actual Windows/Mac/iPhone clients, runtime, network and persistence adapters.

## 16. Review record and completion boundary

Focused author reviews, not independent agent approvals or a security audit:

| Review | Finding / disposition |
| --- | --- |
| Architect | Preserved ADR-0001–0006, shared ownership and component boundaries. ADR-0007 records specific lifecycle refinements; mechanism readiness is explicitly separate from document completion. No provider/framework or deferred product feature was selected. |
| Security | Distinguished endpoint proof from physical hardware identity and recorded credential-theft/compromised-host limits. Added session-fixation coverage, controlled bootstrap/recovery and non-revival. Current proof, custody, network trust and finite parameters remain pre-implementation gates. |
| Backend | Separated received requests from admitted work, application buffers from already released transport bytes, and durable invalidation from unconfirmed intent. No false atomicity across runtime/storage/transport; concrete admission/delivery enforcement remains SD-04. |
| Frontend | Covered hostile markup, inert external URLs, cache/logout behavior, cross-origin requests and expiry while connected. Reauthentication cannot create duplicate sends; client display clearing does not claim remote erasure of delivered data. Actual browser configuration remains a gate. |
| Data & Memory | Verified invalidation/recovery preserve source history, provenance, identity/order/instants and fixed boundaries. Distinguished application credential handling from arbitrary user-pasted content; no automatic redaction, full audit-log mandate or deletion feature was added. |
| QA | Checked all 11 selected SEC/PRIV subsets, 12 threats/controls, 18 objective future cases, three diagrams and 10 assigned decision groups. Tests distinguish server release time from client receipt, lost acknowledgment from failed saving, and documentation coverage from actual security evidence. |

Documentation validation on 2026-10-03 passed: requirement selection matched V0 exactly; control/threat/test/gate IDs and references were valid; each threat had controls, owners and checks; each open decision had rationale, ownership and a deadline; local links, section order and diagram fences resolved. Manual walkthroughs checked the three diagrams and lifecycle/failure cases. Before/after file hashes limited changes to this document, ADR-0007, its ExecPlan and README status. Existing baselines/ADRs, later placeholders and runtime evidence were unchanged. No application tests, network probes, security audit or hardware measurements ran.

Primary OWASP references beside relevant controls were consulted on 2026-10-03. They support general security reasoning; project-specific decisions derive from Anonymous's baselines and explicit logical choices here. No conformance level, audit result or vendor compatibility is claimed. Recheck mechanism-specific guidance at selection time.

Next authorized work should resolve access/deployment mechanism gates with actual client configurations and owner recovery preferences, followed by dependent API/persistence contracts. Runtime feasibility/containment needs separate actual-hardware evidence. Memory, private release, tools and deletion remain deferred. This document begins none of those tasks.
