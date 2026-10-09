# ADR-0010: V0 owner bootstrap and recovery

**Status:** Accepted ceremony and authority design; owner custody configuration remains a provisioning gate.  
**Date:** 2026-10-04.

## Context

A single owner must establish and recover access without public self-registration. Missing state cannot reopen first-owner mode, old approval cannot defeat later revocation, and recovery cannot change source ownership/history (ADR-0007, LM CB-07). All clients may be lost even while server data remains intact.

## Alternatives

First reachable caller/default passwords, localhost-only trust, password-only device approval and resetting ownership when storage is missing violate established semantics. Network-provider recovery alone would conflate authority and add an external dependency. Host administration alone is insufficient for the supported owner-recovery ceremony; a separately held proof reduces accidental/unauthorized reset risk even though fully compromised host administration remains outside the guarantee.

## Decision

Initial establishment requires explicit trusted host administration at a positively verified new dataset and a single-use, dataset/boot-bound random bootstrap proof entered at the validated local HTTPS origin. Keep a protected installation/dataset marker outside the dataset and a matching authoritative initialized-owner binding. Any missing/mismatched/partial state fails closed, never triggers normal first-owner mode.

Additional browser enrollment uses a server-generated pending credential, a short-lived request with cross-screen pairing proof, and fresh authorized owner confirmation bound to current target state. Pending proof grants no history. Approval/denial consumption and operation association are durable; replays cannot apply a transition again or supersede later revocation. Restoration creates fresh proof and sessions while retaining explicit stable Device identity where appropriate.

Establish a separate random 256-bit recovery proof; retain only its purpose/dataset-bound verifier. All-clients-lost recovery requires both trusted local host administration and this offline proof, with intact readable binding/access state. Make recovery-in-progress durable and close ordinary access before changes. Replace owner authentication, revoke all prior device/session/pending authority, rotate recovery proof and explicitly enroll a fresh usable browser. Preserve User identity, Device records, history, order, commit instants and provenance.

Verify retrieval of the new recovery copy before consuming the old verifier. Interrupted uncommitted recovery remains closed and resumes only the same ceremony; committed recovery accepts only the new proof. Lost acknowledgments never justify old-key reuse or fresh ownership. No automatic reset when all proofs are lost.

Custody is deliberately not finalized as a user choice. Before provisioning the owner must choose and demonstrate a secure separate paper copy, encrypted removable copy with independent unlocking material, or password-manager custody with independently recoverable offline copy. A same-device/cloud-only copy does not satisfy the gate. No particular storage location, password manager or existing backup is assumed. CA/disk/network-account keys have separate recovery requirements.

## Consequences

Recovery is possible after client loss without redefining the source dataset, provided owner proof and intact access state remain. It is not backup restoration, corruption repair or decryption-key recovery. With neither valid management authority nor recovery material, the dataset remains locked and preserved. Lost marker/access storage needs separate controlled repair, not this key as a magical reconstruction of ownership. Fully compromised host administration can still defeat software controls.

## Affected documents

The [evaluation section 7](../evaluations/v0-access-security-mechanisms.md) defines detailed user flows, failure handling and custody gates; sections 11/15 specify checks. This refines SD-02 and ADR-0007 without superseding the [security baseline](../07-security.md) or [logical preservation model](../05-data-model.md). No recovery tool, key, storage schema or API is created.
