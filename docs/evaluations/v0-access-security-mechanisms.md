# V0 Access & Security Mechanism Evaluation v0.1

**Status:** Design evaluation complete; choices below are accepted for V0 where marked DECIDED_V0. Configuration, custody and actual-environment evidence remain prerequisites, not completed deployment work.  
**Date:** 2026-10-04.  
**Owners:** Security and Architect; six focused author reviews in section 16.

## 1. Authority and outcome

This evaluation refines [Security Design & Threat Model](../07-security.md), not its threat model. It follows the [project definition](../00-project-definition.md), [domain model](../01-domain-model.md), [requirements](../02-requirements.md), [scope](../03-v0-scope.md), [architecture](../04-architecture.md), [logical model](../05-data-model.md), and accepted ADRs 0001–0007. See the [ExecPlan](../../.agent/plans/2026-10-04-v0-access-security-mechanisms.md).

Select a responsive browser client; Tailscale for private remote reachability; independently terminated HTTPS; an Anonymous owner passphrase, approved browser device credential and opaque server-side session; explicit local bootstrap/recovery; and serialized admission/invalidation/delivery enforcement. These choices are recorded in ADRs [0008](../adr/0008-v0-private-network-and-browser-origin.md), [0009](../adr/0009-v0-browser-device-and-session-credentials.md), [0010](../adr/0010-v0-owner-bootstrap-and-recovery.md) and [0011](../adr/0011-v0-access-coordinator-and-delivery.md).

No runtime, model, database, framework, API routes or physical schema is selected. No software, credentials, infrastructure, firewall or ports were configured. Vendor documentation establishes candidate capabilities; no actual-client compatibility, performance or security test has run.

The intended host is the existing Windows Ryzen 7 5700X / RTX 3070 8 GB / 32 GB RAM desktop on untrusted shared-house networking. Clients are that Windows machine, M1 Pro MacBook Pro and iPhone. Pocket Wi-Fi, mobile networks and CGNAT are normal remote conditions. Exact OS/browser versions, encryption support and available resources remain unverified. The core path must require no new recurring subscription.

## 2. Client configuration gate

**DECIDED_V0:** A responsive browser application is sufficient. Project Definition §9 permits this initial form; its technology direction and V0 Scope §4 support all required text-chat interactions without native mobile. Use one same-origin web application/API surface. No desktop wrapper, native desktop/mobile app, service worker, PWA installation or offline content cache is required. No frontend framework follows from this choice.

Target acceptance configurations are a maintained Microsoft Edge on Windows, Safari on macOS and Safari on iPhone, in ordinary first-party browser profiles with JavaScript and secure cookies enabled. This selects browser families to test, not invented installed versions or support for every release. Private browsing, embedded webviews and browser profiles that erase cookies are not persistent-device configurations. Cookie loss is recoverable by explicit re-enrollment. Each required device must pass MT-01 before real use; substitute browser families require the same evidence.

Owner device management is required on the desktop browser; iPhone requires core chat and enrollment, not a full administration console. All clients use C02/C03 and the same ownership checks. The Windows browser receives only a transport optimization, never direct data/runtime access.

## 3. Private-network evaluation and selected boundary

| Candidate | Fit for the intended environment | Burden, limitations and disposition |
| --- | --- | --- |
| Tailscale managed private network | Documented Windows/macOS/iOS clients, WireGuard-encrypted direct or relayed connections, device approval and network policy. Relay fallback is practical when direct connectivity fails across NAT/CGNAT. | **Selected for V0.** External account/control/relay dependencies for remote operation; metadata exposure and vendor changes remain risks. Anonymous auth/local access remain independent. |
| Plain WireGuard with manually managed peers | Strong encrypted peer identity, roaming and NAT keepalives. Suitable if a reachable peer/endpoint already exists. | Not selected: no verified reachable endpoint here. Keepalives preserve mappings; they do not supply a general discovery/relay service for two hard-NAT peers. An extra public hub, routing and key-distribution work would add unproven cost/operations. This is a deployment inference, not a claim WireGuard cannot roam. |
| LAN-only HTTPS | Small local surface. | Not selected as remote access: cannot satisfy Pocket Wi-Fi/mobile use. Local loopback HTTPS remains supported. |

Tailscale documents encrypted direct/DERP/peer-relay connectivity and relay fallback; this supports selection without assuming a direct path or requiring inbound public port forwarding. Actual network restrictions may still block connectivity. [Connection types](https://tailscale.com/docs/reference/connection-types). WireGuard documents endpoint configuration and NAT keepalives; its paper describes key-based roaming. [Quick start](https://www.wireguard.com/quickstart/), [protocol paper](https://www.wireguard.com/papers/wireguard.pdf).

Tailscale provides the required platform clients. [Installation matrix](https://tailscale.com/docs/install). Its current Personal plan is $0 for personal/noncommercial use, with up to six users and unlimited user devices; this fits the intended single-owner setup. Confirm account eligibility and current terms before deployment; a business trial or optional paid feature cannot become a hidden V0 dependency. [Pricing, consulted 2026-10-04](https://tailscale.com/pricing).

The selected network policy is explicit device approval plus least-privilege grants from approved client nodes to the server's application HTTPS listener only. Review/remove any broad existing allow rule: adding a narrow grant does not cancel a broader grant. No subnet routing, exit node, public Funnel, shared-node access or provider AI/content proxy is needed. These are intended restrictions, not configuration performed here. [Device approval](https://tailscale.com/docs/features/access-control/device-management/device-approval), [grant semantics](https://tailscale.com/docs/reference/syntax/grants).

Keep provider identity, node keys and account recovery in Tailscale's custody model, separate from the Anonymous User/Device identities. The operator protects the network account with its available strong authentication and independently recoverable account access. Keep network node-key expiry finite, record its configured interval, and rehearse operator reauthentication without disabling Anonymous protection; an expired server node can interrupt remote use while local loopback still works. Provider enrollment/key renewal may require an external identity provider; Anonymous login never uses it. Tailnet administration is a separate control plane; Anonymous holds no Tailscale administration API key.

Removal from Tailscale and revocation in Anonymous are separate actions. For a lost client, revoke Anonymous authority first when reachable and remove the network node as defense in depth; document incomplete actions if either layer is unavailable. Uninstalling a network client is not network removal. [Device removal](https://tailscale.com/docs/features/access-control/device-management/how-to/remove). Anonymous revocation acknowledgment never waits for provider propagation or trusts a network disconnection as its own durable revocation.

Tailscale's control plane coordinates identities, public keys and network policy; encrypted relays do not terminate Anonymous TLS. Treat provider account/node/address associations and traffic timing/size as infrastructure metadata, not Anonymous history storage. Use non-sensitive machine names. An existing tailnet can partly continue through a coordination outage, but fresh enrollment, policy propagation and reconnect behavior must not be promised during it. [Coordination outage behavior](https://tailscale.com/docs/reference/coordination-server-down). If the daemon or usable path is down, remote Anonymous access can fail closed. No public/plaintext fallback.

## 4. Transport, origin and local access

**DECIDED_V0:** Terminate TLS in the Anonymous-owned ingress, independently of Tailscale Serve. Serve the static frontend and logical API on exactly one configured HTTPS origin. No remote reverse proxy, trusted identity headers or separate browser API origin is needed. Permit TLS 1.3 and maintained TLS 1.2 configurations; reject obsolete protocols and certificate warnings. Library/cipher implementation is later technology work. [OWASP TLS](https://cheatsheetseries.owasp.org/cheatsheets/Transport_Layer_Security_Cheat_Sheet.html).

Select an operator-managed private CA for server identity, with its public root explicitly trusted on each supported client and its signing key kept offline. Use a leaf certificate with a matching subject alternative name for the server's actual configured MagicDNS fully qualified hostname, not an IP or a user-supplied Host value. Remote clients resolve that hostname through the private network. Windows has an operator-provisioned local name-resolution override for the **same hostname and port** to loopback; TLS still validates that hostname. Both paths reach the identical ingress/access code. MagicDNS supplies a device FQDN; changing the device/tailnet name is therefore an explicit origin/certificate migration, not an ordinary IP change. [MagicDNS naming](https://tailscale.com/docs/features/magicdns).

This local path requires no running Tailscale daemon, external DNS, cloud login or online certificate renewal during ordinary use. Offline CA signing permits renewal without a cloud service, but requires the operator and intact CA custody. Certificate expiry still denies access. Select finite leaf validity within 30–365 days (initial 90 days) and an advance renewal check; actual browser acceptance, root lifetime/renewal and protected signing procedure must be recorded before deployment. These are operational policy values, not claims about universal certificate lifetime limits.

Manual private-root installation is possible on Apple clients, but iPhone requires explicit SSL/TLS trust after manual profile installation. Root installation must use an authenticated local transfer and out-of-band fingerprint verification; never trust a root merely because an unverified web page supplies it. [Apple iPhone trust procedure](https://support.apple.com/en-ca/102390), [Apple local CA/macOS trust guidance](https://developer.apple.com/documentation/backgroundassets/testing-asset-packs-locally). Windows trust-store deployment, Safari/Edge chain validation and offline behavior require MT-01/09 evidence; no trust store is changed here.

Tradeoff: this avoids making local access depend on provider HTTPS issuance/renewal, at the cost of maintaining a small private CA and installing trust on three devices. A trusted root has broad impersonation power if stolen; use a dedicated CA, restrict issuing practice to Anonymous, keep its private key off the live server, and document replacement/removal from clients. Do not claim browser-enforced root name constraints without testing. Public CA certificates and Tailscale Serve were evaluated but not selected for this independent offline path. This is a local deployment choice, not a permanent dependence of Anonymous domain identities on Tailscale DNS.

CA custody is **CONFIGURABLE_V0** and unresolved: choose an encrypted offline signing-key package on separately held removable storage, with separately recoverable decryption material, or an equivalently reviewed offline custody procedure. Record who can retrieve it, renewal and loss drills before provisioning. No safe existing custody is assumed. Missing CA custody blocks protected deployment, not completion of the mechanism evaluation. CA loss permits deliberate trust replacement on clients; it does not authorize resetting Anonymous ownership.

Diagram 1 — separate reachability, server identity and application authority:

```text
Mac / iPhone -- Tailscale approved node + restricted network grant --+
                                                                 |
Windows browser -- same origin resolved locally to loopback -------+
                                                                 v
                         Anonymous-owned HTTPS ingress (C02/C10)
                         validated host, origin, CSRF and safe inputs
                                                                 |
                         C03: approved device proof + valid session
                              associated owner + target permission
                                                                 |
                         C04/C05 --> C08 private canonical state
                             |
                         C06 --> C07 --> private local runtime

Tailscale membership is not an Anonymous session.
Loopback reachability is not an Anonymous owner credential.
```

## 5. User, device and session credentials

| Layer | Selected mechanism and custody | Meaning / limits |
| --- | --- | --- |
| User | One stable owner, authenticated by a local passphrase; no username namespace or cloud identity integration. Salted Argon2id verifier on the server. | Passphrase proves owner authentication but cannot grant an unapproved browser access. Never use it as a database encryption key. |
| Device | Server-generated, 256-bit cryptographically random opaque bearer credential in a persistent HttpOnly cookie; store its SHA-256 verifier and association with the stable Device, credential generation and approval state. | Proves the approved browser installation's possession, not hardware identity. Labels/IPs/Tailscale claims cannot substitute for it. |
| Session | Fresh independent 256-bit opaque bearer cookie, server-side verifier and current User/Device/credential-generation/session validity association. | Both matching device and session proof required on each protected interaction. No authority encoded solely in a signed token. |
| Recovery / bootstrap | Separate purpose-scoped high-entropy proofs described in section 7; never login cookies. | No token can change roles merely by being sent to another operation. |

All random material is to be generated using a maintained OS-backed cryptographic generator during later implementation; none is generated here. Use independent purpose-bound SHA-256 verifiers for uniformly random 256-bit secrets, constant-time secret comparisons and strict input length limits. Passwords require a slow password hash, not this fast digest. Adopt the OWASP Argon2id floor of 19 MiB, two iterations and parallelism one; tune upward only after measuring coexistence with generation, within the finite configuration envelope in section 12. No custom cryptographic implementation. [OWASP Password Storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html).

V0 passphrase policy: allow 15–128 characters, spaces and password-manager paste; no silent truncation, composition puzzle or periodic change without cause. This is a project default for an owner credential, not a multi-factor assurance claim. Password entry is transient, submitted only over the configured TLS origin and excluded from ordinary logs/content. Password change requires current approved session plus fresh existing passphrase (or the recovery ceremony); it invalidates all prior sessions and establishes a fresh one after coherent success. Suspected endpoint theft also requires device-credential revocation/replacement; password change alone is not device removal.

Device and session cookies use `Secure`, `HttpOnly`, `SameSite=Strict`, `Path=/`, no `Domain`, and distinct `__Host-` names. No credential in URLs, localStorage, sessionStorage, IndexedDB or frontend-readable token stores. Server validity controls access regardless of browser expiration/restoration. Host-scoped cookies are **not port-isolated**: dedicate the hostname to Anonymous and run no untrusted service on another port under it. The cookie mechanism and session-cookie restoration caveat are documented by [MDN Set-Cookie](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Set-Cookie).

Browser device credentials expire after a server-enforced 180 days by default (configurable 30–365 days); cookie lifetime cannot extend that deadline. Expiry stops dependent sessions, then requires explicit fresh enrollment. This finite limit bounds unattended retained proof; it is not measured convenience. Re-enrollment rotates proof, not stable identity. Copying both cookies can impersonate the session until expiry/revocation; stealing a device cookie plus the passphrase can establish new sessions. HttpOnly limits script reads but cannot stop an active same-origin compromise from issuing actions. Unlocked/compromised clients remain residual risks.

A Device represents an explicitly owner-recognized endpoint, with one or more independently enrolled browser-profile credentials. The owner may attach a new profile to an existing Device through explicit management; never infer this from names/fingerprints/IP. Profiles are distinguishable approved credentials; device revocation covers all of them. Each profile has its own session cookie, so two profiles can supply distinct concurrent sessions for one Device. Ordinary tabs in one profile share one session; closing a tab is not logout. Replacing a lost profile disables its old proof before activating the new one. Do not copy cookies between profiles as enrollment.

Alternatives: network identity alone fails localhost/provider independence and the unapproved-device rule; a passphrase alone lacks approved endpoint proof; device proof alone omits fresh owner evidence. Synced passkeys could authenticate the owner but do not by themselves establish this distinct approved endpoint association. Hardware-bound WebAuthn or client TLS certificates add capability/recovery/cross-browser work without required V0 evidence; defer them. OAuth/cloud sign-in is unnecessary for Anonymous. Signed self-contained session tokens still need live revocation state and add signing-key/claim/expiry complexity with no independent offline verifier requirement; prefer opaque sessions.

## 6. Sessions, clocks and sensitive actions

The following are V0 policy defaults with bounded configuration. They trade some repeated login against private-data exposure; test actual usability before release. The need for finite server-enforced idle/absolute timeouts and reauthentication is consistent with [OWASP Session Management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html); the exact choices are Anonymous's decisions.

| Concern | Concrete V0 policy |
| --- | --- |
| Establishment | Approved device proof plus correct owner passphrase; mint a fresh session identifier and CSRF context. Never elevate an existing pre-authentication token. |
| Absolute expiry | Eight hours from authentication; configurable one–eight hours. No activity or token replacement extends this session's ceiling. |
| Idle expiry | Thirty minutes; configurable five–thirty minutes, never exceeding absolute expiry. Successful user-initiated protected interactions update activity; background polling, heartbeats, streaming output and failed requests do not. This is a client behavior contract, not proof of human presence. |
| Long generation | Generation/output does not suspend either deadline. Expiry ends protected delivery; previously admitted computation can finish/save privately. New login reconciles the existing intent, never resends automatically. |
| Renewal / rotation | No silent refresh token or rolling lifetime. Fresh passphrase plus currently approved device creates a new session and invalidates the previous session for that browser profile before confirmation. No overlap/grace acceptance of the predecessor. Other profiles' sessions remain valid unless explicitly invalidated. |
| Management freshness | Re-enter passphrase for each approve/deny/revoke/credential-change action. If confirmation is separate, its server-side grant is single-use, target/action/current-revision bound and expires within five minutes; no general unlocked management mode. Recovery uses its own proof. |
| Logout / session revoke | Durably end only the selected session; stop all its tabs/streams; clear its cookie/view. Retain the device cookie so ordinary login remains possible. A remaining approved owner session with fresh proof can revoke a named other session. |
| Device revoke | Disable the Device and all credential generations/sessions in one coherent transition. Reapproval never revalidates old proof or sessions. |
| Concurrent sessions | Separate server identities; never share expiry/idle state across distinct sessions. Login in another profile does not log out the first. Enforce a configured finite session count without silently evicting an unrelated valid session. |
| Server restart | Before readiness, exclusively acquire authoritative-instance ownership and durably advance the access boot generation. Every earlier session/pending ceremony is invalid. Device approvals and owner verifier remain; login again. Uncertain persistence means no protected readiness. |
| Clock / suspend | Within a boot use server monotonic elapsed-time deadlines plus wall-clock anomaly detection; message timestamps and client timezones play no role. Invalidate live sessions/pending ceremonies on suspend/resume or ambiguous elapsed-time evidence. Forward/backward wall-clock discontinuities require reauthentication; never recompute an expired session as valid. The OS integration proving detection is a validation gate. |

Session verification always checks current boot, current device/credential generation, terminal invalidation and deadlines. For persistent device-proof age, retain a durable last-known security-time floor at successful security transitions; startup/login with a regressed or ambiguous clock denies new authority until trusted clock correction or explicit proof replacement. Observed credential expiry is terminal and cannot be undone by a later clock change. This security evidence is separate from message commit instants; its storage/time representation remains open. Durable terminal facts are retained as needed until the boot-generation barrier makes old proof permanently ineligible; this does not require an indefinite session journal. Unknown session IDs deny. A lost login response may require a new login; it must not recover plaintext tokens from a digest or revive a predecessor. Forgotten passphrase is handled only by section 7. A browser that restores an old cookie after closing cannot override server expiry.

## 7. Bootstrap, enrollment and recovery ceremonies

**First Windows/server bootstrap:** Trusted OS administration explicitly initializes an intended new dataset at a positively verified empty target. Normal startup never creates ownership because a file/read/configuration is missing. Create an installation/dataset binding marker in protected host state outside the dataset, and a matching initialized-owner binding in authoritative storage. They record that initialization occurred, not secret owner proof. Missing, mismatched or partly written bindings close access and enter controlled repair; neither one alone authorizes bootstrap. An explicit new installation must never overwrite or silently adopt existing history.

After the independent HTTPS origin and verified local trust are provisioned, the administrator starts a local, authenticated provisioning ceremony that produces a single-use, purpose/dataset/boot-bound 256-bit bootstrap proof valid for ten minutes. The Windows browser opens the validated canonical HTTPS origin over loopback and enters that proof through a protected form, never a query string or command-line argument. Local reachability alone has no effect. Establish the stable owner, passphrase verifier, first browser device proof and recovery verifier coherently. Confirm successful closure before granting a new ordinary session. Concurrent calls and lost acknowledgment resolve the same establishment; incomplete initialization stays closed. No public registration or default password exists.

The first owner receives a separate 256-bit recovery secret in a human-copyable, checksummed form via the protected ceremony. Only its purpose/dataset-bound verifier is retained by Anonymous. Recovery is not a decryption key and cannot recreate damaged/missing source or ownership records. Raw material is not retained in logs, screenshots, clipboard history or the normal application; require a verification step showing the operator can retrieve the offline copy before declaring provisioning complete.

**Adding the MacBook:** Join Tailscale using its separate enrollment and network-admin approval; install/verify the public CA root; open the canonical origin. The browser receives a fresh random *pending* device credential in its protected cookie. Its verifier and a ten-minute, boot-bound enrollment request confer no access. Display a separate high-entropy pairing phrase bound to that pending request, not the bearer credential. On the already approved desktop, the owner enters that phrase, compares both screens and confirms the intended device/profile with fresh passphrase. Do not allow blind approval by display name. Approval durably activates only that candidate proof with a new credential generation. The Mac then logs in with the owner passphrase to obtain its own session.

**Adding iPhone:** The same three stages apply: network join/approval; trusted certificate and explicit browser enrollment approved from desktop; owner login in Safari. Mobile IP changes do not require enrollment. Safari cookie removal does. Do not promise permanent cookie retention under all iOS storage policies. Native app credentials, email links and SMS verification are unnecessary.

**Deny, revoke, re-enroll, replay:** Denial or pending timeout permanently closes that request. A lost approval acknowledgment can be reconciled under current owner authority; the already-issued candidate cookie avoids storing a recoverable plaintext credential merely to replay issuance. Approval is a compare-and-apply transition against the current target trust generation, with a unique retained operation association. Replaying an already consumed operation returns its historic disposition plus current permitted state, never applies it again. A later revocation wins over an old approval. Restoration requires explicit fresh request/proof and owner action against current state; old device credentials and sessions remain invalid. Stable Device identity can be preserved by explicit owner selection. Revoking a stolen client uses section 9's enforcement barrier; network removal is separate.

**All clients lost:** Require trusted server OS administration **and** the current offline recovery secret. Normal chat/remote ingress cannot enter recovery. The ceremony first makes recovery-in-progress durable and closes ordinary access; verify the dataset binding and recovery verifier. Replace the owner passphrase, revoke all previous device credentials/sessions and pending enrollment/management grants, advance recovery/access generations, and explicitly enroll a new first usable browser. Preserve existing User and Device records, conversation history, exact messages, commit instants, order and run/provenance. It creates fresh access authority, not a new dataset or source owner.

Rotate the recovery secret on successful use. Show a new secret and verify its offline custody before committing the replacement and consuming the old proof. A crash before confirmation leaves ordinary access closed: the old recovery proof may resume only the same pending recovery under trusted host administration, not start parallel recovery or serve chat. After the replacement is committed, the old proof fails forever; lost acknowledgment is resolved by the new proof. If its copy was not actually retained, the recovery procedure cannot claim success for the user. Failed/unknown persistence remains recovery-in-progress. This requires a recoverable coherent C08 transition, not assumed atomicity across browser delivery and storage.

**Recovery custody remains CONFIGURABLE_V0:** The owner has not answered the custody preference question. Before provisioning, choose either a printed key held securely away from server/clients, encrypted removable storage with independently recoverable unlocking material, or a password manager with an independently recoverable offline copy. No cloud-only or same-disk-only copy qualifies. Record a retrieval/loss drill and replacement procedure without putting secret material in this repository. CA, disk-encryption and network-account recovery are separate custodial responsibilities; an Anonymous recovery key does not recover them.

If only sessions are lost, approved device plus passphrase suffices. If the passphrase is lost but a session remains, that session cannot bypass fresh proof for credential changes; use recovery. If recovery material is unavailable but owner passphrase and an approved usable session/device remain, fresh owner proof may rotate recovery material. If no authorized management path and no valid recovery material remain, the dataset stays locked. Do not reopen registration, guess ownership from history, trust localhost or overwrite data. Restoring unreadable/corrupt access state or backups requires separately scoped recovery; this is not a V0 disaster-recovery guarantee. Host administrator compromise remains outside the threat model even though the supported ceremony requires both proofs.

Diagram 2 — authority creation versus recovery:

```text
explicit new-dataset administration + bootstrap proof
                 --> coherent owner/device establishment --> registration closed

network approval --> pending browser proof --> fresh owner approval
                 --> approved device proof + passphrase --> new session

revocation --> old credentials and sessions terminally invalid
fresh restoration --> new proof/generation --> new session (same Device identity)

all clients lost + intact access state + host admin + offline recovery secret
                 --> closed recovery --> rotate proof/revoke old authority
                 --> new browser enrollment; existing history unchanged
missing/unreadable state or missing required proof --> closed, never new-owner mode
```

## 8. Browser security and credential storage

C02 validates the configured Host and origin; reject ambiguous/duplicate credential inputs and untrusted forwarded identity/host/protocol headers. There is no trusted proxy in this deployment. CORS is disabled for cross-origin access: no wildcard or reflected credentialed allowance. Same-origin policy alone is not protection against forged state changes.

Use a server-side synchronizer CSRF token bound to the current session (or separate pre-authentication context for login/enrollment), supplied in a custom request header for mutations. Require exact trusted Origin for these browser requests; missing/null/hostile Origin denies rather than inventing a fallback. No state-changing GET. Session creation, logout and enrollment are included. Stream/poll initiation must carry matching current authority and an anti-forgery context; if the later transport cannot carry the selected proof safely, change the transport contract, not put session secrets in URLs. Fetch Metadata is additional defense, not a substitute. [OWASP CSRF guidance](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html).

C01 renders messages as plain text with context-safe DOM text handling; no active HTML, link previews, external image/font/script loads or model-triggered actions. Apply a restrictive content security policy allowing only required same-origin assets/connections, no inline/eval scripts, no objects, no framing, no foreign form destinations or base-URL override; include framing denial and content-type sniffing protection. Final header serialization and any nonce mechanism belong to later client contract work. All assets are local. User and assistant FR-15 timestamps remain continuously visible near actions; full date/time may be secondary. Formatting never changes persisted absolute instants or server order.

Protected content and credential responses use `Cache-Control: no-store`; no shared cache, service worker, persistent conversation storage, push preview or private text/credential in browser URLs or document titles. Client state stays in memory. On logout/invalidation, clear private DOM/state and the session cookie, retaining only the intended device cookie. Clear/hide private views on page suspension/navigation; require a successful current-authority check before revealing a restored/back-forward page. Browser screenshots, memory, downloads made outside the app, extensions and OS task-switcher snapshots cannot be reliably recalled; no remote-erasure claim. Do not erase device proof accidentally with blanket site-data clearing on ordinary logout. Reconnect authenticates/reconciles existing operations without auto-send.

| Location | Selected storage expectation / deployment evidence |
| --- | --- |
| Windows server verification state | Salted owner verifier; purpose-bound random-secret digests; device/session/generation/invalidation facts through C08. Restricted NTFS ACLs for a dedicated service identity, distinct from ordinary browser user and runtime identity. Do not expose raw storage to clients. |
| Windows server usable secrets | TLS leaf private key and any selected runtime/service secret protected with user-scoped Windows DPAPI under the dedicated service identity plus file ACLs; plaintext only in required process memory. No JWT signing secret needed. Never use machine-wide DPAPI as a substitute for account isolation. Exact secret-file representation/library is not selected. |
| Offline owner/CA keys | Recovery proof as section 7; CA signing key offline, never installed in the application/runtime. Dedicated custody and rotation drills. Server has no stored plaintext owner passphrase/recovery key. |
| Windows browser | Browser-managed secure cookie jar in a protected OS profile. Ordinary web code cannot choose Windows Credential Manager/DPAPI backing for cookies; no such assurance is claimed. Device lock, maintained browser and verified disk protection are prerequisites. |
| macOS browser | Browser-managed cookies in protected profile; FileVault and screen lock expected. Anonymous does not directly integrate Keychain from browser JavaScript or promise non-exportable device proof. |
| iPhone Safari | Browser-managed cookies, device passcode and platform Data Protection. No app-controlled Secure Enclave/keychain slot, no claim cookies survive clearing/restoration or are hardware-bound. Re-enroll after loss. |
| Copies/diagnostics | Disable application/runtime payload tracing, automatic crash-content upload and private profile/history synchronization for the supported configuration. Inspect OS/browser backup/sync paths and disk-key escrow before private use. No automatic export to cloud. |

Microsoft documents user-scoped DPAPI and its account-reset/recovery limitations. It protects stored secrets, not a compromised service process or transit. [DPAPI](https://learn.microsoft.com/en-us/windows/win32/seccrypto/example-c-program-using-cryptprotectdata). DPAPI loss after an OS account reset can make service secrets unavailable; preserve source state and use reviewed reprovisioning, never bypass data authorization.

**CONFIGURABLE_V0:** At-rest encryption and recovery custody must be verified on actual devices before storing real private data. Prefer available Windows BitLocker/Device Encryption and macOS FileVault; record edition/hardware eligibility and offline recovery. Windows automatic device encryption may escrow a recovery key to an account, so do not silently assume all key custody is local. [Microsoft BitLocker](https://learn.microsoft.com/en-us/windows/security/operating-system-security/data-protection/bitlocker/index). Apple documents passcode-backed Data Protection and FileVault. [Apple platform protection](https://support.apple.com/en-euro/guide/security/sec20230a10d/web). If existing Windows facilities cannot satisfy private custody without purchase, a separately reviewed local encryption option is required; deployment remains gated, not permission to assume unencrypted data is protected. No physical database encryption format is chosen. Full-host compromise, unlocked-profile theft and inaccessible encryption keys remain limits.

## 9. Coherent authorization and active delivery

**DECIDED_V0:** C03 is the single authoritative access coordinator inside the modular server. C02, C04 and C05 must go through it for authorization-sensitive admission and transport release. Use one serialized coordination boundary for current policy decisions, security transitions and bounded release actions; C08 supplies durable compare-and-apply semantics. No independently cached allow decisions, disconnected JWT verification or per-worker authority. Exact synchronization primitive and storage transaction representation await implementation technology; the serialization protocol is selected now.

| Boundary | Mandatory check / effect |
| --- | --- |
| Request admission | Both device and session proof, boot/generations/deadlines, associated owner and permitted operation; receipt/queueing is not admission. |
| Resource reads | Current ownership for conversation, message, run, provenance and pagination; IDs are not permissions. |
| Send / retry | C03 authorization serialized with C05 durable admission. One pending/active/uncertain generation per conversation; busy new sends do not append or queue. |
| Poll / stream connect | Current session/device/resource authority; protected handshake and bounded subscriptions. |
| Each protected release | Recheck current authority immediately at the application's irreversible handoff to the controlled TLS transport, serialized against invalidation. All private metadata/body chunks and cached results are included. |
| Retry / reconciliation | Current permission before disclosing original outcome; correlation never authenticates or causes fresh inference. |
| Management | Current approved session, fresh action-bound owner proof, target's current generation and replay-safe transition. |

Revocation sequence: enter coordinator; mark affected scope denied; quiesce its application-side release/admission; durably commit terminal invalidation/operation disposition; discard not-yet-released affected output; confirm no stale writer remains; acknowledge. A persistence/enforcement failure retains the deny barrier and reports failure/unknown, not success. Recover the same outcome under a still-authorized management context. If the server cannot establish safe scope, close all protected admission/delivery until repaired.

A release action holds the serialization boundary only for a bounded, nonblocking handoff; do not hold it across slow client I/O or inference. Full transport buffer means defer/drop the pending output under limits and reauthorize any later handoff. A check followed by an unlocked queued write is forbidden. TLS/library/OS buffers already accepted beyond the documented release boundary count as released, and may arrive later; bytes still queued in application/framework workers do not. The adapter must expose this boundary and pass MT-07 before acceptance. A transport that cannot do so is ineligible.

Already admitted coherent mutations and their existing generation may finish/save privately. Invalidation neither cancels inference by assumption nor releases the per-conversation busy gate. Another valid session can read saved output. On restart, obtain exclusive process ownership, confirm access boot generation and invalidations, and reconcile runtime/publication independently before enabling affected new generation. The exclusive-instance lock must be held for the process lifetime and fail the second instance closed; its Windows/storage primitive remains a bounded implementation binding, not permission for concurrent authorities.

Diagram 3 — ordered release and invalidation:

```text
current-authority check + bounded transport release -- coordinator -- revoke
              |                                                    |
              v                                      deny + persist invalidation
      released bytes may arrive later                 + stop stale writers
                                                                  |
                                                        effective acknowledgment
                                                                  |
                                                  later admission/release denied
existing run --> private completion/publication --> another currently valid session
```

## 10. Service exposure and runtime containment

| Surface | Intended binding and allowed caller |
| --- | --- |
| Anonymous HTTPS ingress / API | Explicit loopback and Tailscale interfaces only; same configured origin. No wildcard/LAN/public listener. Host firewall independently denies ordinary residential-LAN ingress. IPv4 and IPv6 both inspected. Reachability still requires app auth. |
| Frontend | Same ingress, static nonsensitive shell may precede login. If a build/development server exists later, it is never a second production remote surface. |
| Model runtime | Loopback or authenticated/ACL-protected local IPC only; C07 is the only authorized application caller. No overlay/LAN/public reachability. |
| Persistence | Prefer no client-facing network surface; if later storage is network-capable, restrict to local authenticated application/service identity. No browser, LAN, overlay or runtime access. This is not database selection. |
| Provisioning / recovery / debug | Trusted OS administration only. No remotely reachable admin/debug/profiler endpoint or browser-facing runtime console. Authenticated owner device management remains part of the ordinary protected app. |

Loopback alone does not authenticate a caller: another local user/process might reach it. **Runtime caller authentication is required for V0** in addition to binding. Accept either runtime-native authentication using a separate C07-held high-entropy service secret, or an OS-authenticated local transport with an enforceable caller ACL. A wrapper in front of an unprotected reachable backend is insufficient. Actual choice is **BLOCKED_PENDING_RUNTIME_EVIDENCE**. If neither can be demonstrated on Windows without unintended exposure, reject that candidate or evaluate a concrete isolation arrangement before selection. No Ollama exception.

The runtime is trusted to process the supplied PRIVATE context, not to read Anonymous files or secrets. Run it under a separate restricted OS principal; deny runtime outbound network during private execution and deny reads of source/access stores, service secrets and unrelated personal files. Permit only verified model files, necessary libraries and bounded private scratch. Model acquisition/update is a separate explicit operator step outside private invocation; do not leave downloader/tool/remote-code capabilities active. No cloud fallback, telemetry containing content, prompt history or cross-request disk cache containing private input/output is permitted. If a runtime must retain private scratch, document bounded local protection/cleanup and inspect it; do not claim secure erasure.

Runtime feasibility/security work must record artifact provenance/version/hash and model license, authentication and bypass tests, effective principal/file/network permissions including child processes, actual listeners, egress/telemetry/log/cache observations with synthetic markers, safe crash behavior, and surviving-process observation/termination. A separate process by itself proves none of these. Authentication, GPU support under that principal, output recovery and coexistence on the RTX 3070 machine remain evidence gates. No benchmark results are invented or appended here.

## 11. Required failure and attack flows

L = private/local reachability and TLS; D = Anonymous device; U/S = owner/session; P = authoritative persistence/admission; R = runtime. All flows preserve saved history unless explicitly appending an already admitted result.

| ID / situation | Layers and expected mechanism behavior | Persisted effect | User-visible result |
| --- | --- | --- | --- |
| F-01 iPhone Wi-Fi to Pocket Wi-Fi | L reconnects through direct/relay as available; D unchanged, S rechecked. No address identity. | No access change merely for IP; existing accepted operation correlation retained. | Reconnect or login if expired; reconcile existing send, no duplicate. |
| F-02 Unknown peer knows host/address | L blocks nonmember/LAN; reachable peer still lacks D/S. Generic shell/enrollment cannot expose history. | No owner/device approval, message or run creation. Rate evidence bounded. | Unreachable or generic access denial/enrollment request. |
| F-03 Approved network node lacks Anonymous auth | L success is insufficient; pending D or missing U/S blocks protected operations. | Pending enrollment only if explicitly requested; no chat mutation. | Await approval/login, no history preview. |
| F-04 Authorized device revoked | D/P coordinator disables all its proofs/sessions before ack; separately remove network node. | Durable revocation/generation/disposition; sources unchanged. | Owner sees effective/uncertain outcome honestly; target denied. |
| F-05 Session expires during generation | S deadline blocks next release; R/P may privately complete the existing attempt. | Session terminal; at most original attempt's saved response. | View clears when informed; login and reconcile, no auto-resend. |
| F-06 Revoke while streaming | D/S/P release barrier stops not-yet-released bytes; pre-released bytes may arrive. | Revocation durable before ack; run preserved, not falsely cancelled. | Stream ends/access denied; other session may read final saved answer. |
| F-07 Server restarts | L local origin persists; P boot barrier invalidates all old S/ceremonies; R reconciled before conflicting work. | Fresh boot generation; prior invalidations/history unchanged; uncertain work remains blocked. | Login again; see saved/unfinished/uncertain outcome truthfully. |
| F-08 All sessions lost | Approved D plus passphrase creates new S; no bootstrap/recovery needed. | New session facts only. | Ordinary login and existing conversations. |
| F-09 All devices lost, recovery exists | Host admin plus recovery proof enters closed P recovery; rotate U proof, D/S generations and recovery secret. | Same User/history; old credentials revoked; fresh enrollment. | Offline custody verification then new login. |
| F-10 Recovery material unavailable | Remaining approved D/passphrase can rotate recovery; without authorized path deny. Missing/corrupt state never implies new owner. | No reset/overwrite; locked data preserved. | Explicit locked/recovery-unavailable result; separate recovery task if needed. |
| F-11 Shared-LAN scan | L binding/firewall denies app/runtime/store/debug on LAN, including IPv6; D/S still protect accidental reachability. | None beyond sanitized bounded operational evidence. | No core service access. A discovered listener is failed acceptance, not harmless because login exists. |
| F-12 Private-network software offline | Remote L unavailable; cohosted Windows uses same HTTPS origin over static loopback resolution, independent TLS and U/D/S. | No trust change; admitted runs may save; logout/revoke locally still coherent. | Remote unavailable; provisioned local login/chat continues while local prerequisites intact. |
| F-13 Stale approval replay | D/P operation association and target generation reject reapplication after denial/revoke/recovery. | No new authority; original disposition remains associated. | Historic result/current denied state or conflict; fresh owner ceremony required. |
| F-14 Hostile browser origin | L host/origin checks, CSRF synchronizer proof, strict cookies, no credentialed cross-origin allowance/framing. D/S possession alone does not waive forgery checks. | No unauthorized mutation/inference; private reads denied. | Hostile origin fails; legitimate same-origin control succeeds. |

## 12. Bounded configuration and operational behavior

These are policy bounds, not measured machine capacity. Record actual values and validate them before the corresponding implementation/release gate. Configuration is trusted operator state, not model/chat parameters; unknown/missing values fail protected readiness rather than defaulting to unlimited operation.

| Setting | Bounded V0 requirement / initial policy |
| --- | --- |
| Session/ceremony time | Section 6 ranges; pending enrollment/bootstrap ten minutes, no renewal; action grant at most five minutes. Device proof 30–365 days. No zero/unlimited lifetime. |
| Auth work | Argon2id memory 19–64 MiB, iterations 2–4, parallelism one; choose measured setting within bounds. At most one expensive verification concurrently; bounded queue of at most two. Separate admission for already-authenticated revocation so failed logins cannot monopolize it. |
| Attempt rates | Initial five failed credential attempts per minute per presented credential/pending proof and twenty per minute globally, with bounded backoff up to one minute; no permanent owner lockout. IP may supplement abuse accounting, never grant/revoke identity. Reserve a priority management lane with its own bounded attempt budget for a valid approved session, unaffected by the unapproved-login global bucket; retain the one-verification concurrency ceiling. Host recovery remains separate. Validate under load. |
| Counts | At most ten approved browser credentials, four live sessions per Device, sixteen total; pending enrollment at most eight with finite expiry. Refuse new allocation visibly; never silently revoke another valid session to make room. |
| Generation | Conservative V0 ceiling of one globally admitted generation, in addition to one active/unsettled per conversation. Refuse new work while full, without append/queue. Increasing concurrency requires runtime and access-coordinator load evidence and a recorded policy change. |
| Content / context / runtime timeouts | Finite raw request, generated-output and context limits must be selected within measured runtime/capacity bounds before execution implementation. No truncation disguised as full saved output; reject oversized input or report incomplete generation. Classified with runtime evidence below, not assigned a fictitious token capacity. |
| Delivery / diagnostics | Choose finite buffer/connection ceilings with a demonstrated process-memory budget; slow-client output cannot occupy an unbounded queue or coordinator. Runtime-dependent capacity remains gated. Security log default seven days and 32 MiB, configurable one–thirty days and 8–128 MiB, whichever limit is reached first; bound individual entries. No history/run pruning. |

Keep canonical ownership, current generations/invalidation and required operation-replay facts for as long as old authority could otherwise reappear; operational log rotation cannot remove them. Retain only sanitized operation kind, responsible context/target, correlation and confirmed/failed/unknown outcome in the bounded operational journal. Never record raw credentials, passphrases, context, full cookies, pairing phrases or raw third-party errors. Access is local operator or authorized management only. Generic invalid-login/access errors do not reveal private resources; authenticated users receive safe actionable states. Optional logging failure does not establish or negate a durable authority transition.

Incident procedure: from remaining valid management or controlled recovery, revoke affected Anonymous authority, separately remove network nodes, rotate compromised owner/service/CA material as appropriate, stop private runtime use if containment is uncertain, and preserve source data plus sanitized evidence. Do not copy stale access databases over live state. Backup/restore with anti-rollback and secure erasure remain separately scoped.

## 13. Decision matrix and remaining gates

Statuses describe mechanism disposition, not tested implementation readiness. **CONFIGURABLE_V0** means a bounded choice/configuration or an implementation binding to the selected protocol, with named evidence before use; it is not permission to leave the value unspecified in a running system. No item remains BLOCKED_PENDING_CLIENT_DECISION because section 2 resolves the client-form dependency. Exact supported versions still require evidence.

| Security gate / decision | Classification | Resolution, remaining evidence and owner |
| --- | --- | --- |
| SD-01 user/device/session proof | DECIDED_V0 | Local passphrase, approved browser bearer proof, opaque server-side sessions; section 5 / ADR-0009. |
| SD-01 actual browser compatibility and verifier cost | CONFIGURABLE_V0 | Edge/Safari configurations and bounded Argon2id cost; Frontend/Backend record MT-01/11. |
| SD-02 bootstrap/recovery authority and replay | DECIDED_V0 | Explicit host ceremony, dual installation/dataset binding, separate offline proof, credential generations and coherent closed recovery; section 7 / ADR-0010. |
| SD-02 recovery custody and fresh-proof usability | CONFIGURABLE_V0 | Owner chooses one of the independent-copy methods and demonstrates retrieval; no default agreement assumed. Blocks provisioning. |
| SD-03 session lifecycle and restart/clock | DECIDED_V0 | Opaque fresh sessions, no silent refresh, terminal invalidation, new boot generation and suspend/anomaly reauthentication; section 6. |
| SD-03 durations / OS elapsed-time binding | CONFIGURABLE_V0 | Listed finite ranges, actual suspend/clock detection proof; Backend/QA MT-05/08. |
| SD-04 coherence, cached authority and release protocol | DECIDED_V0 | Single coordinator, durable compare-and-apply, deny barrier and bounded serialized release; section 9 / ADR-0011. |
| SD-04 storage/transport/exclusive-instance bindings | CONFIGURABLE_V0 | Must implement the selected protocol, prove CB-07 and exact release boundary without extra authorities; Backend/Data & Memory MT-06–08. No database selected. |
| SD-05 private network / independent local origin | DECIDED_V0 | Tailscale remote, private-CA HTTPS at Anonymous ingress, same-origin loopback path; sections 3–4 / ADR-0008. |
| SD-05 deployment identity, certificate custody, policy/cost/outages | CONFIGURABLE_V0 | Actual hostname/port, CA procedure, root/leaf validity, network account/keys/grants/free-plan eligibility and offline drill; Architect/Security/owner MT-01/09/10. No live values chosen. |
| SD-06 browser forgery/render/cache/reconnect mechanism | DECIDED_V0 | Strict secure cookies, synchronizer CSRF, exact origin, no cross-origin API, text-only and no-store/no service worker; section 8. |
| SD-06 concrete client/header/transport compatibility | CONFIGURABLE_V0 | Actual browser checks and serialization of selected policy; Frontend/Backend MT-01/07/12. No framework gate is silently resolved. |
| SD-07 server usable-secret custody | DECIDED_V0 | Service-user DPAPI plus NTFS isolation; verifiers through C08; browser-managed client cookie custody with explicit limits; section 8. |
| SD-07 at-rest/copy/CA/disk-key custody | CONFIGURABLE_V0 | Verify existing platform encryption, offline keys, profile sync/dumps/copies and least privilege. If unavailable, separately evaluate compliant no-subscription option before private use; Security/owner MT-13. |
| SD-08 runtime access and containment expectation | DECIDED_V0 | Server-private endpoint plus caller authentication/OS ACL; separate restricted principal, no private egress or ambient source/secret access; section 10. |
| SD-08 actual runtime/package/supervision/isolation mechanism | BLOCKED_PENDING_RUNTIME_EVIDENCE | Candidate native auth versus OS-authenticated IPC, effective files/egress/logs/cache, GPU compatibility and surviving-process control must be demonstrated; Backend/Security MT-14 and runtime feasibility plan. |
| SD-09 bounded auth/log/error/incident policy | CONFIGURABLE_V0 | Section 12 finite envelope, sanitized evidence retention and reserved control capacity; Backend/Security MT-11/13. Values need load validation, not universal-security claims. |
| SD-09 execution/content/buffer capacity and deadlines | BLOCKED_PENDING_RUNTIME_EVIDENCE | Measure usable context/output/timeouts/coexistence, then set finite limits and control-lane budgets; Backend/QA MT-11/14. |
| SD-10 richer privacy/tools/Memory/multi-user/delete/backup erasure | DEFERRED_POST_V0 | No expansion; future requirements and dedicated Security/Data & Memory decisions. Source-preservation compatibility remains mandatory. |

No genuine threat-model contradiction was found. Earlier documents' unselected-mechanism statements describe their baseline stage; this dated evaluation and ADRs supply the next-stage dispositions without rewriting them. API design is not started. Dependent persistence/concurrency/transport contracts are still work, even though their required access protocol is now selected.

## 14. Threat/control traceability

All selected security/privacy requirements remain: SEC-01–SEC-06 and SEC-08; PRIV-01/03/04/05. SG coverage below preserves the existing ST cases rather than replacing them. All INV-001–INV-015, V0-D01–D06, CB-01–CB-07 and ADRs 0001–0007 remain intact. In particular, revocation/recovery cannot rewrite source history or FR-15 instants; timestamps neither grant authority nor solely order conversations.

| Threat | Covered controls | Mechanism sections / future checks |
| --- | --- | --- |
| TH-01 network/address identity confusion | SG-01, SG-02 | 3–5, 9; MT-02/09/10; ST-01/02. |
| TH-02 stolen/fixed/replayed sessions | SG-03, SG-04 | 5–7; MT-03–06; ST-03/04. |
| TH-03 bootstrap takeover | SG-03 | 7; MT-02/04/08; ST-05/06. |
| TH-04 IDs/history used as permission | SG-02, SG-05 | 9; MT-02/07; ST-01/07. |
| TH-05 revocation races delivery/admission | SG-05, SG-06 | 9; MT-06/07; ST-08/09. |
| TH-06 cross-origin/header spoofing | SG-07, SG-08 | 4, 8; MT-10/12; ST-10/11. |
| TH-07 executable stored/model content | SG-08, SG-09 | 8, 10; MT-12/14; ST-12/13. |
| TH-08 runtime exfiltration/bypass | SG-09 | 10; MT-14; ST-13/14. |
| TH-09 credential/content leakage | SG-08, SG-10 | 5, 7–8, 12; MT-12/13; ST-12/15. |
| TH-10 restart/clock/stale-state revival | SG-04, SG-06, SG-10 | 6–9; MT-04/05/08; ST-04/09/16. |
| TH-11 exhaustion/security starvation | SG-11 | 9, 12; MT-11/14; ST-17. |
| TH-12 cloud dependence/fail-open fallback | SG-07, SG-12 | 3–4; MT-09; ST-18. |

## 15. Future security test matrix

**Not executed.** Use synthetic credentials/history and isolated fault injection. Record actual versions, deployment policy, sanitized authority/release ordering and before/after canonical facts. Do not record raw test tokens in reusable diagnostics. Tests must establish effects, not merely HTTP status or a UI badge. MT tests specialize ST-01–ST-18 from the security baseline.

| ID | Procedure | Objective acceptance evidence |
| --- | --- | --- |
| MT-01 three-client secure origin | On actual Windows Edge, Mac Safari and iPhone Safari, trust verified root, load canonical origin, enroll/login, create/read/send/reconnect; inspect cookie/CSRF/cache behavior. Exercise local loopback and wrong/expired certificates. | All core flows work with documented versions; secure context/cookie attributes correct; bad certificates fail without bypass; FR-15 visible without hover. Record iPhone trust setup and cookie-loss recovery. |
| MT-02 bootstrap and unauthorized access | Race valid/invalid bootstrap; try signed-out Windows, unknown LAN/overlay and passphrase-only client. Remove/mismatch marker or deny ownership reads. | Only intended ceremony establishes one owner; no private disclosure/mutation/inference elsewhere; missing state never opens registration. |
| MT-03 enrollment/replay | Enroll Mac/iPhone, deny/expire request, lose approval acknowledgment, revoke then replay old approve and old cookies; explicitly restore with fresh candidate. Test an extra profile attached to same Device. | Correct proof/target binding, no name-only approval, historic operation cannot reactivate; old proof remains dead; two profiles have distinct sessions under one Device. |
| MT-04 recovery/custody | Retrieve offline copy after simulated client loss; wrong/missing proof; crash before/after recovery commit; repeat old key; lose final acknowledgment; test passphrase change/compromise scope. | Same owner/history/instants/order/provenance; all old proofs invalid; only proper pending recovery resumes; new key proves completed recovery; unavailable proof leaves closed data. |
| MT-05 expiry/rotation/clocks | Use short test-configured deadlines; active generation, background poll, user action, backward/forward clocks, suspend/resume and browser restore. Renew with fresh password. | No silent lifetime extension or expired authority revival; stream stops at next release; persistent credential age cannot regress across restart; new login does not auto-send; predecessor fails. Production values recorded within bounds. |
| MT-06 selective and device revocation | Device A with profiles/sessions A1/A2 plus B control; logout A1, then revoke A; inject persist/enforcement failure and lost ack. | Logout preserves A2/B; device revoke stops both A sessions; ack only after effective durable enforcement; unknown transitions fail closed; history unchanged. |
| MT-07 release/admission races | Pause after check but before transport release; race revoke/logout/expiry with history/final/stream chunks and waiting new sends; fill slow-client buffers. Reconcile earlier intent from revoked then valid context. | Sanitized server ordering proves no affected new release/admission after barrier/ack; pre-released bytes distinguishable; no duplicate run/append; control session retrieves eligible saved outcome. |
| MT-08 restart/exclusive authority | Abruptly restart at security transition phases and during surviving runtime; attempt second app instance; restore old session cookies and stale process cache. | One authority; durable new boot barrier; all old sessions/ceremonies denied; preserved revocation; no fresh inference to resolve uncertainty or lost history. |
| MT-09 roaming and outages | Move iPhone to Pocket Wi-Fi/mobile; record direct/relay use, then interrupt provider path/daemon. With daemon stopped and external connectivity disabled, cold-start browser/app and login/chat locally. | No IP-based identity changes; remote failure fails closed; local canonical HTTPS/login/chat works without cloud DNS/auth/renewal. Certificate renewal procedure is independently offline-capable. |
| MT-10 network boundaries | From controlled untrusted LAN/overlay peers and lower-privilege local account, inspect IPv4/IPv6 app/runtime/store/debug access, host/origin/forwarded spoofing and wrong DNS. | Only intended app listener reachable through permitted path; no runtime/store bypass; server identity validated; spoofed headers grant no authority. |
| MT-11 limits and coexistence | Saturate failed login/pending enrollment/connections, context/output boundaries and generation while authorized B revokes A. Measure queue, memory, latency and coordinator stalls. | Finite recorded bounds, no silent pruning/unbounded backlog; management remains effective within documented envelope; unsupported capacities stay blocked. No performance number assumed. |
| MT-12 hostile content/browser | Cross-origin forms/fetch/framing/stream handshakes, login CSRF, missing Origin, malicious saved markup/URLs; navigate back/suspend/logout and inspect caches/network. | No forged action/private read/external fetch/script execution; private restored view gated; plaintext source preserved; device cookie survives ordinary logout only. |
| MT-13 secrets/OS/copies | Exercise owner/device/session/recovery failures and raw runtime errors with markers; inspect logs, URLs, browser storage/sync, dumps, ACLs and encryption-key custody under actual OS profiles. | No raw secrets/private payload on prohibited surfaces; verifier/DPAPI ACL protections shown; no unapproved cloud copies; missing disk/custody evidence prevents private deployment. |
| MT-14 runtime evidence | For each candidate, record source/version, listeners/auth, bypass attempts, GPU execution under restricted account, files/egress/children/cache/logs and crash/orphan control; combine with existing runtime feasibility measurements. | Only authenticated C07 caller, no private egress/store/secret access, controlled scratch, attributable output and known supervision limits. Failure blocks selection/use; no inference results invented. |

## 16. Focused review record

These are author review passes using [specialist responsibilities](../agents/README.md), not independent agent approvals, implementation tests or a penetration audit.

| Review | Finding and disposition |
| --- | --- |
| Security | Every TH-01–TH-12 and SG-01–SG-12 remains mapped. Added explicit bearer-theft limits, login CSRF, recovery-key rotation failure handling and no network-revocation dependency. Private CA custody is a real prerequisite, not an assumed safe default. |
| Architect | Browser form fits V0; no framework follows. Tailscale is replaceable transport; independent same-origin loopback preserves offline local use and equal client authority. CA operations add burden; source identities remain independent of DNS/host. |
| Backend | Opaque sessions and one access coordinator support current revocation. Identified and prohibited check-then-queued-write races. Boot-generation and lifetime-held exclusive-instance ownership prevent stale sessions/second authority; exact storage/transport bindings need proof. Runtime uncertainty still blocks new inference. |
| Frontend | Ordinary browser cookies are feasible across target families but copyable and profile-scoped. Defined multiple profiles per Device, tabs sharing a session, mobile enrollment and explicit iPhone root trust. No application-controlled hardware keychain claim; actual browser/offline/cache behavior requires MT-01/12. |
| Data & Memory | Dual bootstrap markers fail closed on partial loss. Recovery changes authenticators, not User/history/order/commit instants/provenance. Security journal limits do not prune canonical invalidation or V0-D03 data. No physical schema/timestamp datatype, backup guarantee or Memory subsystem added. |
| QA | Fourteen attack/failure flows specify layers, persisted effects and visible outcomes; fourteen objective test groups cover all eighteen prior ST cases. Release order is assessed at the server boundary, not client arrival time. Actual hardware/custody evidence is explicitly absent. |

## 17. Completion and next bounded task

The evaluation resolves the client form and access mechanisms and assigns every SD-01–SD-10 decision. New ADRs record only finalized choices; configuration/evidence gates remain in section 13. The project is still architecture/design, and real private use is not approved by this document. Baseline requirements, logical source model and threat model are unchanged.

Documentation validation on 2026-10-04 passed: local links/fences, all numbered sections and ADR structures; 14 failure flows, 14 future tests, 12 threat/control mappings, all 10 SD groups across 19 dispositions, six reviews and three diagrams. A before/after hash comparison confirmed exactly six new Markdown files (this evaluation, its plan and ADRs 0008–0011), with every pre-existing file unchanged. Manual lifecycle reviews checked replay, clock/restart, recovery interruption, delivery races and offline local use. No application/security/hardware tests ran.

Next bounded task: **collect the V0 access-environment and recovery-custody readiness record**, without app implementation or live security changes. Record actual Windows/macOS/iOS and browser versions, available platform encryption/offline key custody, feasible private-root trust and canonical-origin deployment procedure, Tailscale personal-plan/account eligibility, and the owner's recovery/CA custody choices. Prerequisites are access to actual device information and an owner custody decision; request targeted missing facts rather than fabricating them. Existing [runtime feasibility work](../evidence/runtime-feasibility-plan.md) is a separate actual-hardware task and must incorporate section 10/MT-14's containment/authentication evidence before a runtime is selected. Only after those gates and the selected coordinator's persistence/transport contracts are addressed should dependent API design be scoped. No such follow-on work begins here.
