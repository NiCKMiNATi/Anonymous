"""The run record as arbiter (LD-04 §4.1): each transition has its own source predicate.

Exercised directly against the store, below the coordinator, so every race is a deterministic
sequence of conditional writes. The same admissibility table is enforced again by a trigger; one
test compares the trigger with the pure domain function over every combination.
"""

from __future__ import annotations

import hashlib
import itertools
import sqlite3
from pathlib import Path

import pytest

from anonymous.adapters.persistence.sqlite.connection import connect
from anonymous.adapters.persistence.sqlite.store import SqliteStore
from anonymous.application.ports.persistence import SubmissionOutcome, WriteResult
from anonymous.domain.errors import StorageFailure
from anonymous.domain.evidence import (
    ClosureReason,
    CompletionObserved,
    EvidenceBasis,
    Handoff,
    HandoffOutcome,
    RecordEpoch,
    admissible_bases,
)
from anonymous.domain.ids import ConversationId, RunId, SubmissionId, UserId, new_uuid
from anonymous.domain.models import RunStatus
from tests.dispatching import BOOT, authorize, dispatch, record

B = EvidenceBasis


def admit(
    store: SqliteStore, owner: UserId, cid: ConversationId, text: str = "q"
) -> SubmissionOutcome:
    return store.admit_submission(
        owner=owner,
        conversation_id=cid,
        submission_id=SubmissionId(new_uuid()),
        content=text,
        content_sha256=hashlib.sha256(text.encode()).hexdigest(),
    )


def new_run(store: SqliteStore, owner: UserId) -> tuple[ConversationId, RunId]:
    cid = store.create_conversation(owner, None).id
    return cid, admit(store, owner, cid).run.id


def settle(store: SqliteStore, run_id: RunId, basis: EvidenceBasis, **kw):  # type: ignore[no-untyped-def]
    return store.settle_in_flight(
        run_id,
        basis=basis,
        code="c",
        message="m",
        completion=CompletionObserved.UNKNOWN,
        reason=kw.get("reason", ClosureReason.DEADLINE),
        expected_version=kw.get("expected_version"),
    )


# -- T3b / closure ordering (problem A and the marker half of problem B) -------------------------


def test_closure_before_the_handoff_marker_makes_start_impossible(
    store: SqliteStore, owner: UserId
) -> None:
    _, run_id = new_run(store, owner)
    authorize(store, run_id)
    assert store.close_run(run_id, ClosureReason.SHUTDOWN).result is WriteResult.APPLIED
    refused = store.mark_handoff_started(run_id, BOOT)
    assert refused.result is WriteResult.FENCE_CLOSED  # the invoker must NOT call start
    assert refused.run.handoff is Handoff.NONE and refused.run.closed_at is not None
    # Durable proof of non-invocation: settle on B1 with no external action.
    done = settle(store, run_id, B.NEVER_DISPATCHED)
    assert done.result is WriteResult.APPLIED and done.run.status is RunStatus.FAILED


def test_the_handoff_marker_moves_once_and_only_for_the_owning_boot(
    store: SqliteStore, owner: UserId
) -> None:
    _, run_id = new_run(store, owner)
    authorize(store, run_id)
    assert store.mark_handoff_started(run_id, "another-boot").result is WriteResult.WRONG_SOURCE
    assert store.mark_handoff_started(run_id, BOOT).result is WriteResult.APPLIED
    assert store.mark_handoff_started(run_id, BOOT).result is WriteResult.ALREADY_STARTED


def test_publication_requires_an_open_fence_and_a_started_handoff(
    store: SqliteStore, owner: UserId
) -> None:
    _, run_id = new_run(store, owner)
    authorize(store, run_id)
    assert store.publish_response(run_id, "x").result is WriteResult.WRONG_SOURCE  # not started
    store.mark_handoff_started(run_id, BOOT)
    store.close_run(run_id, ClosureReason.DEADLINE)
    assert store.publish_response(run_id, "late").result is WriteResult.ALREADY_CLOSED
    assert (
        len(
            store.read_messages_through(
                store.get_run(run_id).conversation_id, store.get_run(run_id).triggering_message_id
            )
        )
        == 1
    )


def test_publication_wins_and_a_later_closure_cannot_undo_it(
    store: SqliteStore, owner: UserId
) -> None:
    cid, run_id = new_run(store, owner)
    dispatch(store, run_id)
    won = store.publish_response(run_id, "answer")
    assert won.result is WriteResult.APPLIED and won.published is not None
    assert store.close_run(run_id, ClosureReason.DEADLINE).result is WriteResult.PUBLISHED
    assert settle(store, run_id, B.RUNTIME_REPORTED_TERMINAL).result is WriteResult.PUBLISHED
    assert store.get_run(run_id).status is RunStatus.SUCCEEDED
    assert [m.content for m in store.get_history(owner, cid).messages] == ["q", "answer"]


def test_closure_wins_and_publication_is_refused(store: SqliteStore, owner: UserId) -> None:
    cid, run_id = new_run(store, owner)
    dispatch(store, run_id)
    assert store.close_run(run_id, ClosureReason.DEADLINE).result is WriteResult.APPLIED
    assert store.close_run(run_id, ClosureReason.SHUTDOWN).result is WriteResult.ALREADY_CLOSED
    assert store.publish_response(run_id, "answer").result is WriteResult.ALREADY_CLOSED
    assert [m.content for m in store.get_history(owner, cid).messages] == ["q"]
    assert store.get_run(run_id).closure_reason is ClosureReason.DEADLINE  # the first reason stands


# -- T5 / T6 / T7: own source predicates, admissible bases, idempotence --------------------------


def test_settlement_needs_a_basis_admissible_for_the_durable_handoff_state(
    store: SqliteStore, owner: UserId
) -> None:
    _, run_id = new_run(store, owner)
    dispatch(store, run_id, outcome=HandoffOutcome.ACCEPTED)
    for wrong in (B.NEVER_DISPATCHED, B.ADAPTER_NEVER_REACHED):
        assert settle(store, run_id, wrong).result is WriteResult.NO_ADMISSIBLE_BASIS
    assert store.get_run(run_id).status is RunStatus.IN_FLIGHT
    assert settle(store, run_id, B.RUNTIME_REPORTED_TERMINAL).result is WriteResult.APPLIED


def test_unrecorded_outcome_is_not_claimed_uninvoked_and_b5_needs_late_delivery_exclusion(
    store: SqliteStore, owner: UserId
) -> None:
    _, run_id = new_run(store, owner)
    dispatch(store, run_id, outcome=None, late_excluded=False)  # T3c lost: outcome unrecorded
    store.close_run(run_id, ClosureReason.ORPHAN_RECONCILE)
    for refused in (B.NEVER_DISPATCHED, B.ADAPTER_NEVER_REACHED, B.EXECUTION_TERMINATED_VERIFIED):
        assert settle(store, run_id, refused).result is WriteResult.NO_ADMISSIBLE_BASIS
    assert settle(store, run_id, B.PROCESS_EXIT_VERIFIED).result is WriteResult.APPLIED


def test_t7_settles_an_indeterminate_closed_run_and_is_idempotent(
    store: SqliteStore, owner: UserId
) -> None:
    cid, run_id = new_run(store, owner)
    dispatch(store, run_id, outcome=HandoffOutcome.UNKNOWN, late_excluded=False)
    store.close_run(run_id, ClosureReason.DEADLINE)
    version = store.get_run(run_id).state_version
    indeterminate = store.mark_indeterminate(run_id, version)
    assert indeterminate.result is WriteResult.APPLIED
    run = indeterminate.run
    assert run.status is RunStatus.INDETERMINATE and run.slot_id == "slot-1"
    # T5 is the wrong transition for an indeterminate run; T7 is its own.
    assert (
        settle(store, run_id, B.PROCESS_EXIT_VERIFIED).result is WriteResult.ALREADY_INDETERMINATE
    )
    stale = store.settle_indeterminate(
        run_id,
        basis=B.PROCESS_EXIT_VERIFIED,
        code="c",
        message="m",
        completion=CompletionObserved.UNKNOWN,
        expected_version=run.state_version - 1,
    )
    assert stale.result is WriteResult.STALE_VERSION and stale.run.status is RunStatus.INDETERMINATE
    refused = store.settle_indeterminate(
        run_id,
        basis=B.EXECUTION_TERMINATED_VERIFIED,
        code="c",
        message="m",
        completion=CompletionObserved.UNKNOWN,
        expected_version=run.state_version,
    )
    assert refused.result is WriteResult.NO_ADMISSIBLE_BASIS  # B5 after UNKNOWN without exclusion
    first = store.settle_indeterminate(
        run_id,
        basis=B.PROCESS_EXIT_VERIFIED,
        code="c",
        message="m",
        completion=CompletionObserved.UNKNOWN,
        expected_version=run.state_version,
    )
    assert first.result is WriteResult.APPLIED and first.run.status is RunStatus.FAILED
    again = store.settle_indeterminate(
        run_id,
        basis=B.RUNTIME_REPORTED_TERMINAL,
        code="other",
        message="m",
        completion=CompletionObserved.YES,
        expected_version=run.state_version,
    )
    assert again.result is WriteResult.SETTLED  # idempotent: the stored result stands
    assert again.run.termination_basis is B.PROCESS_EXIT_VERIFIED
    assert again.run.failure_code == "c" and again.run.state_version == first.run.state_version
    admit(store, owner, cid, "next")  # admission released together with the settlement


def test_indeterminate_requires_a_closed_fence_and_in_flight_settlement_rejects_it(
    store: SqliteStore, owner: UserId
) -> None:
    _, run_id = new_run(store, owner)
    dispatch(store, run_id)
    run = store.get_run(run_id)
    assert store.mark_indeterminate(run_id, run.state_version).result is WriteResult.WRONG_SOURCE
    store.close_run(run_id, ClosureReason.DEADLINE)
    assert (
        store.settle_indeterminate(
            run_id,
            basis=B.PROCESS_EXIT_VERIFIED,
            code="c",
            message="m",
            completion=CompletionObserved.UNKNOWN,
            expected_version=1,
        ).result
        is WriteResult.WRONG_SOURCE  # T7 does not apply to an in-flight run
    )


def test_a_settlement_with_a_message_present_is_refused(
    store: SqliteStore, owner: UserId, db_path: Path
) -> None:
    _, run_id = new_run(store, owner)
    dispatch(store, run_id)
    store.publish_response(run_id, "x")
    assert settle(store, run_id, B.RUNTIME_REPORTED_TERMINAL).result is WriteResult.PUBLISHED


# -- the slot ------------------------------------------------------------------------------------


def test_the_slot_has_one_owner_and_a_pending_run_holds_none(
    store: SqliteStore, owner: UserId
) -> None:
    _, first = new_run(store, owner)
    _, second = new_run(store, owner)
    assert store.get_run(second).slot_id is None  # pending: admission only
    authorize(store, first)
    busy = store.authorize_dispatch(second, record())
    assert busy.result is WriteResult.SLOT_BUSY and busy.holder_status is RunStatus.IN_FLIGHT
    assert busy.run.status is RunStatus.PENDING
    store.mark_handoff_started(first, BOOT)
    store.publish_response(first, "done")  # releases the slot with the settlement
    assert store.authorize_dispatch(second, record()).result is WriteResult.APPLIED


def test_quarantine_holds_the_slot_and_blocks_other_conversations(
    store: SqliteStore, owner: UserId
) -> None:
    _, first = new_run(store, owner)
    _, other = new_run(store, owner)  # admitted (pending) before the quarantine began
    dispatch(store, first, outcome=HandoffOutcome.UNKNOWN, late_excluded=False)
    store.close_run(first, ClosureReason.DEADLINE)
    store.mark_indeterminate(first, store.get_run(first).state_version)
    held = store.authorize_dispatch(other, record())
    assert held.result is WriteResult.SLOT_BUSY and held.holder_status is RunStatus.INDETERMINATE
    assert store.generation_state().quarantined_runs == (first,)
    from anonymous.domain.errors import RuntimeQuarantined

    third = store.create_conversation(owner, None).id
    with pytest.raises(RuntimeQuarantined):
        admit(store, owner, third)


# -- trigger parity with the pure rule -----------------------------------------------------------


def _insert_run_in_state(
    conn: sqlite3.Connection, handoff: str, outcome: str | None, late: int
) -> str:
    rid = new_uuid()
    cid = new_uuid()
    mid = new_uuid()
    now = "2026-01-01T12:00:00.000000Z"
    uid = conn.execute("SELECT id FROM users").fetchone()[0]
    conn.execute(
        "INSERT INTO conversations (id, owner_user_id, created_at, record_epoch)"
        " VALUES (?, ?, ?, '0b')",
        (cid, uid, now),
    )
    conn.execute(
        "INSERT INTO messages (id, conversation_id, position, role, content, committed_at)"
        " VALUES (?, ?, 1, 'user', 'q', ?)",
        (mid, cid, now),
    )
    conn.execute(
        "INSERT INTO model_runs (id, conversation_id, triggering_message_id, status, requested_at,"
        " record_epoch) VALUES (?, ?, ?, 'pending', ?, '0b')",
        (rid, cid, mid, now),
    )
    digest = conn.execute("SELECT digest FROM effective_configurations").fetchone()[0]
    conn.execute(
        "UPDATE model_runs SET status='in_flight', model_id='m', runtime_id='r', dispatched_at=?,"
        " handoff='NONE', slot_id=?, execution_boot_id='b', binding_format='f',"
        " binding_adapter_id='a', binding_adapter_version='1', binding_instance_ref='i',"
        " binding_declared_bases='', binding_lifetime_scope='owning_process',"
        " binding_late_delivery_excluded=?, configuration_digest=?, provenance_json='{}',"
        " state_version=state_version+1 WHERE id=?",
        (now, f"slot-{rid}", late, digest, rid),
    )
    if handoff == "STARTED":
        conn.execute(
            "UPDATE model_runs SET handoff='STARTED', state_version=state_version+1 WHERE id=?",
            (rid,),
        )
        if outcome is not None:
            conn.execute(
                "UPDATE model_runs SET handoff_outcome=?, state_version=state_version+1 WHERE id=?",
                (outcome, rid),
            )
    conn.execute(
        "UPDATE model_runs SET closed_at=?, closure_reason='deadline',"
        " state_version=state_version+1 WHERE id=?",
        (now, rid),
    )
    return rid


@pytest.mark.parametrize(
    ("handoff", "outcome", "late"),
    [
        (h, o, late)
        for h, o, late in itertools.product(
            ["NONE", "STARTED"], [None, "NOT_CALLED", "NOT_STARTED", "ACCEPTED", "UNKNOWN"], [0, 1]
        )
        if not (h == "NONE" and o is not None)
    ],
)
def test_sql_admissibility_matches_the_domain_rule_for_every_basis(
    store: SqliteStore, owner: UserId, db_path: Path, handoff: str, outcome: str | None, late: int
) -> None:
    expected = admissible_bases(
        epoch=RecordEpoch.CURRENT,
        handoff=Handoff(handoff),
        outcome=HandoffOutcome(outcome) if outcome else None,
        late_delivery_excluded=bool(late),
    )
    for basis in EvidenceBasis:
        conn = connect(db_path)
        try:
            rid = _insert_run_in_state(conn, handoff, outcome, late)
            sql = (
                "UPDATE model_runs SET status='failed', failure_code='x', settled_at=?,"
                " termination_basis=?, completion_observed='unknown',"
                " state_version=state_version+1 WHERE id=?"
            )
            args = ("2026-01-01T12:00:01.000000Z", basis.value, rid)
            if basis in expected:
                conn.execute(sql, args)
            else:
                with pytest.raises(sqlite3.IntegrityError, match="admissible"):
                    conn.execute(sql, args)
        finally:
            conn.close()


def test_triggers_protect_dispatch_facts_the_fence_and_the_epoch(
    store: SqliteStore, owner: UserId, db_path: Path
) -> None:
    _, run_id = new_run(store, owner)
    dispatch(store, run_id)
    conn = connect(db_path)
    try:
        bump = ", state_version = state_version + 1 WHERE id = ?"
        for column, value, message in [
            ("binding_instance_ref", "'other'", "immutable once recorded"),
            ("slot_id", "'slot-2'", "immutable once recorded"),
            ("provenance_json", "'{}'", "immutable once recorded"),
            ("record_epoch", "'legacy_0a'", "immutable"),
            ("handoff", "'NONE'", "handoff moves"),
            ("handoff_outcome", "'UNKNOWN'", "recorded once"),
        ]:
            with pytest.raises(sqlite3.IntegrityError, match=message):
                conn.execute(f"UPDATE model_runs SET {column} = {value}{bump}", (run_id,))
        with pytest.raises(sqlite3.IntegrityError, match="state_version"):
            conn.execute("UPDATE model_runs SET failure_message = 'x' WHERE id = ?", (run_id,))
    finally:
        conn.close()
    store.close_run(run_id, ClosureReason.DEADLINE)
    conn = connect(db_path)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="irreversible"):
            conn.execute(
                "UPDATE model_runs SET closed_at = NULL, closure_reason = NULL,"
                " state_version = state_version + 1 WHERE id = ?",
                (run_id,),
            )
    finally:
        conn.close()


def test_new_runs_are_current_epoch_and_begin_pending(
    store: SqliteStore, owner: UserId, db_path: Path
) -> None:
    cid, _ = new_run(store, owner)
    mid = store.get_history(owner, cid).messages[0].id
    conn = connect(db_path)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="current-epoch"):
            conn.execute(
                "INSERT INTO model_runs (id, conversation_id, triggering_message_id, status,"
                " requested_at, record_epoch) VALUES (?, ?, ?, 'pending', ?, 'legacy_0a')",
                (new_uuid(), cid, mid, "2026-01-01T12:00:00.000000Z"),
            )
    finally:
        conn.close()


def test_a_storage_failure_never_leaves_a_half_written_publication(
    store: SqliteStore, owner: UserId, db_path: Path
) -> None:
    cid, run_id = new_run(store, owner)
    dispatch(store, run_id)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TRIGGER sabotage BEFORE UPDATE ON model_runs WHEN NEW.status='succeeded'"
        " BEGIN SELECT RAISE(ABORT, 'sabotage'); END"
    )
    conn.commit()
    conn.close()
    with pytest.raises(StorageFailure):
        store.publish_response(run_id, "answer")
    assert [m.content for m in store.get_history(owner, cid).messages] == ["q"]
    assert store.get_run(run_id).status is RunStatus.IN_FLIGHT
