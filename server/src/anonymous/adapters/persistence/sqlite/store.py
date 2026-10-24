"""SqliteStore — fulfils the application-owned persistence ports with SQLite.

Every public method is ONE short ``BEGIN IMMEDIATE`` ... ``COMMIT`` (or one deferred read
transaction). Nothing is held open across an external call (model start/await/stop/probe).

The run record is the **arbiter** (LD-04 §4.1): publication, closure and settlement are
conditional writes on it, each with its own source predicate, applied atomically per run by the
write lock. The same predicates are enforced again by triggers in migration 0002 as a backstop;
the Python checks exist to return a *specific* result (``WriteResult``) instead of an error.

A new short-lived connection is used per operation (no connection is shared across threads).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from anonymous.adapters.persistence.sqlite.connection import (
    connect,
    read_transaction,
    write_transaction,
)
from anonymous.application.ports.persistence import (
    Clock,
    ConfigurationBinding,
    ConversationHistory,
    DispatchRecord,
    GenerationState,
    LegacyBlocker,
    PublishedResponse,
    PublishOutcome,
    SubmissionOutcome,
    Transition,
    WriteResult,
)
from anonymous.domain.binding import ExecutionBinding
from anonymous.domain.configuration import BindingOrigin
from anonymous.domain.errors import (
    ConfigurationUnavailable,
    ConfigurationUnbound,
    ConversationBusy,
    ConversationNotFound,
    ExecutionUnresolved,
    IdempotencyConflict,
    LegacyUnresolvedBlock,
    RetryNotEligible,
    RunStateConflict,
    RuntimeQuarantined,
    StorageFailure,
)
from anonymous.domain.evidence import (
    ClosureReason,
    CompletionObserved,
    EvidenceBasis,
    Handoff,
    HandoffOutcome,
    LifetimeScope,
    RecordEpoch,
    RunKind,
    admissible_bases,
    basis_permitted_for_binding,
)
from anonymous.domain.ids import (
    ConversationId,
    MessageId,
    RunId,
    SubmissionId,
    UserId,
    new_uuid,
)
from anonymous.domain.instants import decode_instant, encode_instant
from anonymous.domain.models import (
    Completeness,
    Conversation,
    Message,
    MessageRole,
    ModelRun,
    RunStatus,
)
from anonymous.domain.provenance import ExecutionProvenance

_UNSETTLED_SQL = "('pending', 'in_flight', 'indeterminate')"
_LEGACY_BLOCKER_SQL = (
    "SELECT 1 FROM model_runs WHERE record_epoch = 'legacy_0a'"
    " AND status IN ('in_flight', 'indeterminate') LIMIT 1"
)
_QUARANTINE_SQL = (
    "SELECT 1 FROM model_runs WHERE record_epoch = '0b' AND status = 'indeterminate' LIMIT 1"
)


def _message(row: sqlite3.Row) -> Message:
    return Message(
        id=MessageId(row["id"]),
        conversation_id=ConversationId(row["conversation_id"]),
        position=row["position"],
        role=MessageRole(row["role"]),
        content=row["content"],
        committed_at=decode_instant(row["committed_at"]),
        produced_by_run_id=RunId(row["produced_by_run_id"]) if row["produced_by_run_id"] else None,
        completeness=Completeness(row["completeness"]) if row["completeness"] else None,
    )


def _binding(row: sqlite3.Row) -> ExecutionBinding | None:
    if row["binding_format"] is None:
        return None
    bases = frozenset(EvidenceBasis(b) for b in row["binding_declared_bases"].split(",") if b)
    return ExecutionBinding(
        format=row["binding_format"],
        adapter_id=row["binding_adapter_id"],
        adapter_version=row["binding_adapter_version"],
        instance_ref=row["binding_instance_ref"],
        lifetime_scope=LifetimeScope(row["binding_lifetime_scope"]),
        declared_bases=bases,
        late_delivery_excluded=bool(row["binding_late_delivery_excluded"]),
        model_label=row["model_id"],
        runtime_label=row["runtime_id"],
        control_ref=row["binding_control_ref"],
    )


def _run(row: sqlite3.Row) -> ModelRun:
    def instant(column: str) -> Any:
        return decode_instant(row[column]) if row[column] is not None else None

    def maybe(column: str, kind: Any) -> Any:
        return kind(row[column]) if row[column] is not None else None

    return ModelRun(
        id=RunId(row["id"]),
        conversation_id=ConversationId(row["conversation_id"]),
        triggering_message_id=MessageId(row["triggering_message_id"]),
        status=RunStatus(row["status"]),
        model_id=row["model_id"],
        runtime_id=row["runtime_id"],
        failure_code=row["failure_code"],
        failure_message=row["failure_message"],
        requested_at=decode_instant(row["requested_at"]),
        dispatched_at=instant("dispatched_at"),
        settled_at=instant("settled_at"),
        record_epoch=RecordEpoch(row["record_epoch"]),
        state_version=row["state_version"],
        kind=RunKind(row["kind"]),
        retry_of_run_id=maybe("retry_of_run_id", RunId),
        closed_at=instant("closed_at"),
        closure_reason=maybe("closure_reason", ClosureReason),
        handoff=maybe("handoff", Handoff),
        handoff_outcome=maybe("handoff_outcome", HandoffOutcome),
        execution_boot_id=row["execution_boot_id"],
        slot_id=row["slot_id"],
        binding=_binding(row),
        configuration_digest=row["configuration_digest"],
        provenance=(
            ExecutionProvenance.from_json(row["provenance_json"])
            if row["provenance_json"] is not None
            else None
        ),
        termination_basis=maybe("termination_basis", EvidenceBasis),
        completion_observed=maybe("completion_observed", CompletionObserved),
    )


def _conversation(row: sqlite3.Row) -> Conversation:
    return Conversation(
        id=ConversationId(row["id"]),
        owner_id=UserId(row["owner_user_id"]),
        title=row["title"],
        created_at=decode_instant(row["created_at"]),
    )


def _config_binding(row: sqlite3.Row) -> ConfigurationBinding:
    return ConfigurationBinding(
        conversation_id=ConversationId(row["conversation_id"]),
        seq=row["seq"],
        configuration_digest=row["configuration_digest"],
        origin=BindingOrigin(row["origin"]),
        baseline_evidence=row["baseline_evidence"],
        created_at=decode_instant(row["created_at"]),
    )


class SqliteStore:
    """Implements ``ConversationStore``, ``ExecutionStore`` and ``HistorySource``."""

    def __init__(self, db_path: str | Path, clock: Clock) -> None:
        self._path = db_path
        self._clock = clock

    def _now(self) -> str:
        return encode_instant(self._clock.now())

    # -- bootstrap / health (adapter-specific; not part of the application ports) ------------

    def ensure_dev_owner(self) -> UserId:
        """Return the single development owner, creating it on first start.

        DEVELOPMENT ONLY. This is not the owner bootstrap ceremony (ADR-0010); it exists so that
        conversation ownership (FR-14) is stored independently of any device or session.
        """
        conn = connect(self._path)
        try:
            with write_transaction(conn):
                rows = conn.execute("SELECT id FROM users ORDER BY created_at, id").fetchall()
                if len(rows) > 1:
                    raise StorageFailure("More than one user exists; the dev owner is ambiguous.")
                if rows:
                    return UserId(rows[0]["id"])
                user_id = UserId(new_uuid())
                conn.execute(
                    "INSERT INTO users (id, created_at) VALUES (?, ?)", (user_id, self._now())
                )
                return user_id
        finally:
            conn.close()

    def schema_version(self) -> int:
        conn = connect(self._path)
        try:
            with read_transaction(conn):
                row = conn.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()
                return int(row["v"] or 0)
        finally:
            conn.close()

    # -- ConversationStore ---------------------------------------------------------------------

    def create_conversation(
        self, owner: UserId, title: str | None, configuration_digest: str | None = None
    ) -> Conversation:
        conn = connect(self._path)
        try:
            with write_transaction(conn):
                conversation_id = ConversationId(new_uuid())
                created_at = self._clock.now()
                encoded = encode_instant(created_at)
                conn.execute(
                    "INSERT INTO conversations (id, owner_user_id, title, created_at, record_epoch)"
                    " VALUES (?, ?, ?, ?, '0b')",
                    (conversation_id, owner, title, encoded),
                )
                if configuration_digest is not None:
                    conn.execute(
                        "INSERT INTO conversation_configuration_bindings (conversation_id, seq,"
                        " configuration_digest, origin, created_at) VALUES (?, 1, ?, 'initial', ?)",
                        (conversation_id, configuration_digest, encoded),
                    )
            return Conversation(conversation_id, owner, title, decode_instant(encoded))
        finally:
            conn.close()

    def list_conversations(self, owner: UserId) -> tuple[Conversation, ...]:
        conn = connect(self._path)
        try:
            with read_transaction(conn):
                rows = conn.execute(
                    "SELECT * FROM conversations WHERE owner_user_id = ?"
                    " ORDER BY created_at DESC, rowid DESC",
                    (owner,),
                ).fetchall()
                return tuple(_conversation(r) for r in rows)
        finally:
            conn.close()

    def get_history(self, owner: UserId, conversation_id: ConversationId) -> ConversationHistory:
        conn = connect(self._path)
        try:
            with read_transaction(conn):
                row = conn.execute(
                    "SELECT * FROM conversations WHERE id = ? AND owner_user_id = ?",
                    (conversation_id, owner),
                ).fetchone()
                if row is None:
                    raise ConversationNotFound("Conversation not found.")
                messages = conn.execute(
                    "SELECT * FROM messages WHERE conversation_id = ? ORDER BY position",
                    (conversation_id,),
                ).fetchall()
                runs = conn.execute(
                    "SELECT * FROM model_runs WHERE conversation_id = ?"
                    " ORDER BY rowid",  # insertion order; instants never decide order
                    (conversation_id,),
                ).fetchall()
                return ConversationHistory(
                    conversation=_conversation(row),
                    messages=tuple(_message(r) for r in messages),
                    runs=tuple(_run(r) for r in runs),
                )
        finally:
            conn.close()

    # -- shared helpers ------------------------------------------------------------------------

    @staticmethod
    def _run_row(conn: sqlite3.Connection, run_id: str) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM model_runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise RunStateConflict("The run does not exist.")
        return row  # type: ignore[no-any-return]

    @staticmethod
    def _update_run(
        conn: sqlite3.Connection,
        run_id: str,
        assignments: dict[str, Any],
        where: str,
        where_params: tuple[Any, ...] = (),
    ) -> bool:
        # Column names come from constants in this module, never from caller input.
        columns = ", ".join(f"{column} = ?" for column in assignments)
        cursor = conn.execute(
            f"UPDATE model_runs SET {columns}, state_version = state_version + 1"
            f" WHERE id = ? AND {where}",
            (*assignments.values(), run_id, *where_params),
        )
        return cursor.rowcount == 1

    def _transition(
        self, conn: sqlite3.Connection, run_id: str, result: WriteResult, **extra: Any
    ) -> Transition:
        return Transition(result=result, run=_run(self._run_row(conn, run_id)), **extra)

    @staticmethod
    def _next_position(conn: sqlite3.Connection, conversation_id: str) -> int:
        row = conn.execute(
            "SELECT COALESCE(MAX(position), 0) + 1 AS next FROM messages WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        return int(row["next"])

    @staticmethod
    def _outcome(
        conn: sqlite3.Connection, user_message_id: str, run_id: str, *, replayed: bool
    ) -> SubmissionOutcome:
        user_row = conn.execute(
            "SELECT * FROM messages WHERE id = ?", (user_message_id,)
        ).fetchone()
        run_row = conn.execute("SELECT * FROM model_runs WHERE id = ?", (run_id,)).fetchone()
        assistant_row = conn.execute(
            "SELECT * FROM messages WHERE produced_by_run_id = ?", (run_id,)
        ).fetchone()
        return SubmissionOutcome(
            user_message=_message(user_row),
            run=_run(run_row),
            assistant_message=_message(assistant_row) if assistant_row is not None else None,
            replayed=replayed,
        )

    @staticmethod
    def _check_generation_blocks(
        conn: sqlite3.Connection,
        conversation_id: str,
        executable_digests: frozenset[str] | None,
    ) -> None:
        """Global and per-conversation reasons new generation is refused (design §5.4)."""
        if conn.execute(_LEGACY_BLOCKER_SQL).fetchone() is not None:
            raise LegacyUnresolvedBlock(
                "New generation is blocked: an execution recorded before this version is still"
                " unresolved and cannot be shown to have ended. Reading history still works."
            )
        if conn.execute(_QUARANTINE_SQL).fetchone() is not None:
            raise RuntimeQuarantined(
                "New generation is blocked: an earlier execution could not be shown to have ended."
                " Reading history still works."
            )
        bound = conn.execute(
            "SELECT configuration_digest FROM conversation_configuration_bindings"
            " WHERE conversation_id = ? ORDER BY seq DESC LIMIT 1",
            (conversation_id,),
        ).fetchone()
        if bound is None:
            raise ConfigurationUnbound(
                "This conversation has no confirmed configuration, so generation is blocked until"
                " one is explicitly adopted. History is readable."
            )
        if (
            executable_digests is not None
            and bound["configuration_digest"] not in executable_digests
        ):
            raise ConfigurationUnavailable(
                "The configuration this conversation uses is not available in this version, so"
                " generation is blocked rather than substituted. History is readable."
            )

    # -- T1 ------------------------------------------------------------------------------------

    def find_submission(
        self,
        *,
        owner: UserId,
        conversation_id: ConversationId,
        submission_id: SubmissionId,
        content_sha256: str,
    ) -> SubmissionOutcome | None:
        conn = connect(self._path)
        try:
            with read_transaction(conn):
                existing = conn.execute(
                    "SELECT * FROM submissions WHERE owner_user_id = ? AND submission_id = ?",
                    (owner, submission_id),
                ).fetchone()
                if existing is None:
                    return None
                if (
                    existing["conversation_id"] != conversation_id
                    or existing["content_sha256"] != content_sha256
                ):
                    raise IdempotencyConflict(
                        "This submission id was already used for a different message."
                    )
                return self._outcome(
                    conn, existing["user_message_id"], existing["run_id"], replayed=True
                )
        finally:
            conn.close()

    def admit_submission(
        self,
        *,
        owner: UserId,
        conversation_id: ConversationId,
        submission_id: SubmissionId,
        content: str,
        content_sha256: str,
        executable_digests: frozenset[str] | None = None,
    ) -> SubmissionOutcome:
        conn = connect(self._path)
        try:
            with write_transaction(conn):
                existing = conn.execute(
                    "SELECT * FROM submissions WHERE owner_user_id = ? AND submission_id = ?",
                    (owner, submission_id),
                ).fetchone()
                if existing is not None:
                    if (
                        existing["conversation_id"] != conversation_id
                        or existing["content_sha256"] != content_sha256
                    ):
                        raise IdempotencyConflict(
                            "This submission id was already used for a different message."
                        )
                    return self._outcome(
                        conn, existing["user_message_id"], existing["run_id"], replayed=True
                    )

                owned = conn.execute(
                    "SELECT 1 FROM conversations WHERE id = ? AND owner_user_id = ?",
                    (conversation_id, owner),
                ).fetchone()
                if owned is None:
                    raise ConversationNotFound("Conversation not found.")

                busy = conn.execute(
                    "SELECT 1 FROM model_runs WHERE conversation_id = ?"
                    f" AND status IN {_UNSETTLED_SQL}",
                    (conversation_id,),
                ).fetchone()
                if busy is not None:
                    raise ConversationBusy(
                        "A response is already being generated or is unresolved for this"
                        " conversation."
                    )
                self._check_generation_blocks(conn, conversation_id, executable_digests)

                now = self._now()
                message_id = MessageId(new_uuid())
                run_id = RunId(new_uuid())
                position = self._next_position(conn, conversation_id)
                conn.execute(
                    "INSERT INTO messages (id, conversation_id, position, role, content,"
                    " committed_at, produced_by_run_id) VALUES (?, ?, ?, 'user', ?, ?, NULL)",
                    (message_id, conversation_id, position, content, now),
                )
                conn.execute(
                    "INSERT INTO model_runs (id, conversation_id, triggering_message_id, status,"
                    " requested_at, record_epoch, kind) VALUES (?, ?, ?, 'pending', ?, '0b',"
                    " 'initial')",
                    (run_id, conversation_id, message_id, now),
                )
                conn.execute(
                    "INSERT INTO submissions (owner_user_id, submission_id, conversation_id,"
                    " content_sha256, user_message_id, run_id, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        owner,
                        submission_id,
                        conversation_id,
                        content_sha256,
                        message_id,
                        run_id,
                        now,
                    ),
                )
                return self._outcome(conn, message_id, run_id, replayed=False)
        finally:
            conn.close()

    def admit_retry(
        self,
        *,
        owner: UserId,
        conversation_id: ConversationId,
        retry_id: str,
        message_id: MessageId,
        executable_digests: frozenset[str] | None = None,
    ) -> SubmissionOutcome:
        conn = connect(self._path)
        try:
            with write_transaction(conn):
                intent = conn.execute(
                    "SELECT * FROM retry_intents WHERE owner_user_id = ? AND retry_id = ?",
                    (owner, retry_id),
                ).fetchone()
                if intent is not None:
                    if (
                        intent["conversation_id"] != conversation_id
                        or intent["message_id"] != message_id
                    ):
                        raise IdempotencyConflict(
                            "This retry id was already used for a different message."
                        )
                    return self._outcome(conn, message_id, intent["run_id"], replayed=True)

                owned = conn.execute(
                    "SELECT 1 FROM conversations WHERE id = ? AND owner_user_id = ?",
                    (conversation_id, owner),
                ).fetchone()
                if owned is None:
                    raise ConversationNotFound("Conversation not found.")

                latest = conn.execute(
                    "SELECT * FROM messages WHERE conversation_id = ?"
                    " ORDER BY position DESC LIMIT 1",
                    (conversation_id,),
                ).fetchone()
                if latest is None or latest["id"] != message_id or latest["role"] != "user":
                    raise RetryNotEligible(
                        "Only the latest saved user message can be retried, and only when no later"
                        " message exists."
                    )
                unsettled = conn.execute(
                    "SELECT status FROM model_runs WHERE conversation_id = ?"
                    f" AND status IN {_UNSETTLED_SQL}",
                    (conversation_id,),
                ).fetchone()
                if unsettled is not None:
                    if unsettled["status"] == "indeterminate":
                        raise ExecutionUnresolved(
                            "The earlier attempt could not be shown to have ended, so a retry is"
                            " not allowed yet."
                        )
                    raise ConversationBusy("A response is already being generated.")
                last_run = conn.execute(
                    "SELECT * FROM model_runs WHERE triggering_message_id = ?"
                    " ORDER BY requested_at DESC, rowid DESC LIMIT 1",
                    (message_id,),
                ).fetchone()
                if last_run is None or last_run["status"] != "failed":
                    raise RetryNotEligible("Only a settled failed attempt can be retried.")
                self._check_generation_blocks(conn, conversation_id, executable_digests)

                now = self._now()
                run_id = RunId(new_uuid())
                conn.execute(
                    "INSERT INTO model_runs (id, conversation_id, triggering_message_id, status,"
                    " requested_at, record_epoch, kind, retry_of_run_id)"
                    " VALUES (?, ?, ?, 'pending', ?, '0b', 'retry', ?)",
                    (run_id, conversation_id, message_id, now, last_run["id"]),
                )
                conn.execute(
                    "INSERT INTO retry_intents (owner_user_id, retry_id, conversation_id,"
                    " message_id, run_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (owner, retry_id, conversation_id, message_id, run_id, now),
                )
                return self._outcome(conn, message_id, run_id, replayed=False)
        finally:
            conn.close()

    # -- reads ---------------------------------------------------------------------------------

    def get_run(self, run_id: RunId) -> ModelRun:
        conn = connect(self._path)
        try:
            with read_transaction(conn):
                return _run(self._run_row(conn, run_id))
        finally:
            conn.close()

    def get_outcome(self, run_id: RunId) -> tuple[ModelRun, Message, Message | None]:
        conn = connect(self._path)
        try:
            with read_transaction(conn):
                run_row = self._run_row(conn, run_id)
                user_row = conn.execute(
                    "SELECT * FROM messages WHERE id = ?", (run_row["triggering_message_id"],)
                ).fetchone()
                assistant_row = conn.execute(
                    "SELECT * FROM messages WHERE produced_by_run_id = ?", (run_id,)
                ).fetchone()
                return (
                    _run(run_row),
                    _message(user_row),
                    _message(assistant_row) if assistant_row is not None else None,
                )
        finally:
            conn.close()

    def list_pending_runs(self) -> tuple[ModelRun, ...]:
        conn = connect(self._path)
        try:
            with read_transaction(conn):
                rows = conn.execute(
                    "SELECT * FROM model_runs WHERE status = 'pending' ORDER BY rowid"
                ).fetchall()
                return tuple(_run(r) for r in rows)
        finally:
            conn.close()

    def list_unresolved_runs(self) -> tuple[ModelRun, ...]:
        conn = connect(self._path)
        try:
            with read_transaction(conn):
                rows = conn.execute(
                    "SELECT * FROM model_runs WHERE status IN ('in_flight', 'indeterminate')"
                    " ORDER BY requested_at, rowid"
                ).fetchall()
                return tuple(_run(r) for r in rows)
        finally:
            conn.close()

    def generation_state(self) -> GenerationState:
        conn = connect(self._path)
        try:
            with read_transaction(conn):
                legacy = conn.execute(
                    "SELECT id, conversation_id, status, runtime_id FROM model_runs"
                    " WHERE record_epoch = 'legacy_0a' AND status IN ('in_flight', 'indeterminate')"
                    " ORDER BY requested_at, rowid"
                ).fetchall()
                quarantined = conn.execute(
                    "SELECT id FROM model_runs"
                    " WHERE record_epoch = '0b' AND status = 'indeterminate'"
                ).fetchall()
                return GenerationState(
                    legacy_blockers=tuple(
                        LegacyBlocker(
                            run_id=RunId(r["id"]),
                            conversation_id=ConversationId(r["conversation_id"]),
                            status=RunStatus(r["status"]),
                            runtime_label=r["runtime_id"],
                        )
                        for r in legacy
                    ),
                    quarantined_runs=tuple(RunId(r["id"]) for r in quarantined),
                )
        finally:
            conn.close()

    # -- T2 ------------------------------------------------------------------------------------

    def settle_pending(self, run_id: RunId, code: str, message: str) -> Transition:
        conn = connect(self._path)
        try:
            with write_transaction(conn):
                row = self._run_row(conn, run_id)
                if row["status"] != "pending":
                    return self._transition(conn, run_id, WriteResult.WRONG_SOURCE)
                self._update_run(
                    conn,
                    run_id,
                    {
                        "status": "failed",
                        "failure_code": code,
                        "failure_message": message,
                        "settled_at": self._now(),
                        "termination_basis": EvidenceBasis.NEVER_DISPATCHED.value,
                        "completion_observed": CompletionObserved.NO.value,
                    },
                    "status = 'pending'",
                )
                return self._transition(conn, run_id, WriteResult.APPLIED)
        finally:
            conn.close()

    def recover_pending_runs(self) -> int:
        conn = connect(self._path)
        try:
            with write_transaction(conn):
                rows = conn.execute("SELECT id FROM model_runs WHERE status = 'pending'").fetchall()
                now = self._now()
                for row in rows:
                    self._update_run(
                        conn,
                        row["id"],
                        {
                            "status": "failed",
                            "failure_code": "interrupted_before_dispatch",
                            "failure_message": "The server stopped before this attempt was"
                            " dispatched.",
                            "settled_at": now,
                            "termination_basis": EvidenceBasis.NEVER_DISPATCHED.value,
                            "completion_observed": CompletionObserved.NO.value,
                        },
                        "status = 'pending'",
                    )
                return len(rows)
        finally:
            conn.close()

    # -- T3 / T3b / T3c ------------------------------------------------------------------------

    def authorize_dispatch(self, run_id: RunId, record: DispatchRecord) -> Transition:
        conn = connect(self._path)
        try:
            with write_transaction(conn):
                row = self._run_row(conn, run_id)
                if row["status"] != "pending" or row["record_epoch"] != "0b":
                    return self._transition(conn, run_id, WriteResult.WRONG_SOURCE)
                if conn.execute(_LEGACY_BLOCKER_SQL).fetchone() is not None:
                    return self._transition(conn, run_id, WriteResult.LEGACY_BLOCKED)
                holder = conn.execute(
                    "SELECT status FROM model_runs WHERE slot_id = ?"
                    " AND status IN ('in_flight', 'indeterminate')",
                    (record.slot_id,),
                ).fetchone()
                if holder is not None:
                    return self._transition(
                        conn,
                        run_id,
                        WriteResult.SLOT_BUSY,
                        holder_status=RunStatus(holder["status"]),
                    )
                binding = record.binding
                self._update_run(
                    conn,
                    run_id,
                    {
                        "status": "in_flight",
                        "model_id": binding.model_label,
                        "runtime_id": binding.runtime_label,
                        "dispatched_at": self._now(),
                        "handoff": Handoff.NONE.value,
                        "slot_id": record.slot_id,
                        "execution_boot_id": record.boot_id,
                        "binding_format": binding.format,
                        "binding_adapter_id": binding.adapter_id,
                        "binding_adapter_version": binding.adapter_version,
                        "binding_instance_ref": binding.instance_ref,
                        "binding_control_ref": binding.control_ref,
                        "binding_declared_bases": ",".join(
                            sorted(b.value for b in binding.declared_bases)
                        ),
                        "binding_lifetime_scope": binding.lifetime_scope.value,
                        "binding_late_delivery_excluded": 1
                        if binding.late_delivery_excluded
                        else 0,
                        "configuration_digest": record.configuration_digest,
                        "provenance_json": record.provenance.to_json(),
                    },
                    "status = 'pending'",
                )
                return self._transition(conn, run_id, WriteResult.APPLIED)
        finally:
            conn.close()

    def mark_handoff_started(self, run_id: RunId, boot_id: str) -> Transition:
        conn = connect(self._path)
        try:
            with write_transaction(conn):
                row = self._run_row(conn, run_id)
                if row["status"] != "in_flight" or row["record_epoch"] != "0b":
                    return self._transition(conn, run_id, WriteResult.WRONG_SOURCE)
                if row["closed_at"] is not None:
                    return self._transition(conn, run_id, WriteResult.FENCE_CLOSED)
                if row["handoff"] == Handoff.STARTED.value:
                    return self._transition(conn, run_id, WriteResult.ALREADY_STARTED)
                if row["execution_boot_id"] != boot_id:
                    return self._transition(conn, run_id, WriteResult.WRONG_SOURCE)
                self._update_run(
                    conn,
                    run_id,
                    {"handoff": Handoff.STARTED.value},
                    "status = 'in_flight' AND closed_at IS NULL AND handoff = 'NONE'"
                    " AND execution_boot_id = ?",
                    (boot_id,),
                )
                return self._transition(conn, run_id, WriteResult.APPLIED)
        finally:
            conn.close()

    def record_handoff_outcome(self, run_id: RunId, outcome: HandoffOutcome) -> Transition:
        conn = connect(self._path)
        try:
            with write_transaction(conn):
                row = self._run_row(conn, run_id)
                if (
                    row["status"] != "in_flight"
                    or row["handoff"] != Handoff.STARTED.value
                    or row["handoff_outcome"] is not None
                ):
                    return self._transition(conn, run_id, WriteResult.WRONG_SOURCE)
                self._update_run(
                    conn,
                    run_id,
                    {"handoff_outcome": outcome.value},
                    "status = 'in_flight' AND handoff = 'STARTED' AND handoff_outcome IS NULL",
                )
                return self._transition(conn, run_id, WriteResult.APPLIED)
        finally:
            conn.close()

    # -- T4 ------------------------------------------------------------------------------------

    def publish_response(
        self, run_id: RunId, content: str, completeness: Completeness | None = None
    ) -> PublishOutcome:
        conn = connect(self._path)
        try:
            with write_transaction(conn):
                row = self._run_row(conn, run_id)
                run = _run(row)
                status = row["status"]
                if status == "succeeded":
                    message_row = conn.execute(
                        "SELECT * FROM messages WHERE produced_by_run_id = ?", (run_id,)
                    ).fetchone()
                    return PublishOutcome(
                        WriteResult.PUBLISHED, run, PublishedResponse(_message(message_row), run)
                    )
                if status == "failed":
                    return PublishOutcome(WriteResult.SETTLED, run)
                if status == "indeterminate" or row["closed_at"] is not None:
                    return PublishOutcome(WriteResult.ALREADY_CLOSED, run)
                if (
                    status != "in_flight"
                    or row["handoff"] != Handoff.STARTED.value
                    or row["record_epoch"] != "0b"
                ):
                    return PublishOutcome(WriteResult.WRONG_SOURCE, run)

                conversation_id = row["conversation_id"]
                now = self._now()
                message_id = MessageId(new_uuid())
                position = self._next_position(conn, conversation_id)
                conn.execute(
                    "INSERT INTO messages (id, conversation_id, position, role, content,"
                    " committed_at, produced_by_run_id, completeness)"
                    " VALUES (?, ?, ?, 'assistant', ?, ?, ?, ?)",
                    (
                        message_id,
                        conversation_id,
                        position,
                        content,
                        now,
                        run_id,
                        completeness.value if completeness is not None else None,
                    ),
                )
                applied = self._update_run(
                    conn,
                    run_id,
                    {
                        "status": "succeeded",
                        "settled_at": now,
                        "termination_basis": EvidenceBasis.RUNTIME_REPORTED_TERMINAL.value,
                        "completion_observed": CompletionObserved.YES.value,
                    },
                    "status = 'in_flight' AND closed_at IS NULL AND handoff = 'STARTED'",
                )
                if not applied:
                    raise RunStateConflict("The run changed while publishing; nothing was saved.")
                message = _message(
                    conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
                )
                new_run = _run(self._run_row(conn, run_id))
                return PublishOutcome(
                    WriteResult.APPLIED, new_run, PublishedResponse(message, new_run)
                )
        finally:
            conn.close()

    # -- T5c / T5 / T6 / T7 --------------------------------------------------------------------

    def _terminal_result(self, conn: sqlite3.Connection, row: sqlite3.Row) -> Transition | None:
        """Common answer when the run has already left the states a settlement can act on."""
        run_id = row["id"]
        if row["status"] == "succeeded":
            return self._transition(conn, run_id, WriteResult.PUBLISHED)
        if row["status"] == "failed":
            return self._transition(conn, run_id, WriteResult.SETTLED)
        if row["status"] == "pending" or row["record_epoch"] != "0b":
            return self._transition(conn, run_id, WriteResult.WRONG_SOURCE)
        return None

    def close_run(
        self, run_id: RunId, reason: ClosureReason, expected_version: int | None = None
    ) -> Transition:
        conn = connect(self._path)
        try:
            with write_transaction(conn):
                row = self._run_row(conn, run_id)
                done = self._terminal_result(conn, row)
                if done is not None:
                    return done
                if row["status"] == "indeterminate" or row["closed_at"] is not None:
                    return self._transition(conn, run_id, WriteResult.ALREADY_CLOSED)
                if expected_version is not None and row["state_version"] != expected_version:
                    return self._transition(conn, run_id, WriteResult.STALE_VERSION)
                self._update_run(
                    conn,
                    run_id,
                    {"closed_at": self._now(), "closure_reason": reason.value},
                    "status = 'in_flight' AND closed_at IS NULL",
                )
                return self._transition(conn, run_id, WriteResult.APPLIED)
        finally:
            conn.close()

    def _settle_failed(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
        *,
        basis: EvidenceBasis,
        code: str,
        message: str,
        completion: CompletionObserved,
        reason: ClosureReason | None,
        expected_version: int | None,
        source_status: str,
    ) -> Transition:
        run_id = row["id"]
        run = _run(row)
        if expected_version is not None and row["state_version"] != expected_version:
            return self._transition(conn, run_id, WriteResult.STALE_VERSION)
        allowed = admissible_bases(
            epoch=run.record_epoch,
            handoff=run.handoff,
            outcome=run.handoff_outcome,
            late_delivery_excluded=bool(row["binding_late_delivery_excluded"]),
        )
        has_message = conn.execute(
            "SELECT 1 FROM messages WHERE produced_by_run_id = ?", (run_id,)
        ).fetchone()
        binding = _binding(row)
        if basis not in allowed or (
            binding is not None
            and not basis_permitted_for_binding(
                basis, scope=binding.lifetime_scope, declared=binding.declared_bases
            )
        ):
            # ADR-0015: an EXTERNAL binding cannot be settled on a runtime-asserting basis its
            # adapter did not declare, whoever the caller is. No schema change: a Python check in
            # the one transaction that settle_in_flight and settle_indeterminate share.
            return self._transition(conn, run_id, WriteResult.NO_ADMISSIBLE_BASIS)
        if has_message is not None:
            return self._transition(conn, run_id, WriteResult.WRONG_SOURCE)
        now = self._now()
        closed_at = row["closed_at"] or now
        closure_reason = row["closure_reason"] or (
            reason.value if reason is not None else ClosureReason.ORPHAN_RECONCILE.value
        )
        applied = self._update_run(
            conn,
            run_id,
            {
                "status": "failed",
                "failure_code": code,
                "failure_message": message,
                "settled_at": now,
                "closed_at": closed_at,
                "closure_reason": closure_reason,
                "termination_basis": basis.value,
                "completion_observed": completion.value,
            },
            f"status = '{source_status}' AND NOT EXISTS"
            " (SELECT 1 FROM messages WHERE produced_by_run_id = model_runs.id)",
        )
        if not applied:
            return self._transition(conn, run_id, WriteResult.WRONG_SOURCE)
        return self._transition(conn, run_id, WriteResult.APPLIED)

    def settle_in_flight(
        self,
        run_id: RunId,
        *,
        basis: EvidenceBasis,
        code: str,
        message: str,
        completion: CompletionObserved,
        reason: ClosureReason,
        expected_version: int | None = None,
    ) -> Transition:
        conn = connect(self._path)
        try:
            with write_transaction(conn):
                row = self._run_row(conn, run_id)
                done = self._terminal_result(conn, row)
                if done is not None:
                    if row["record_epoch"] != "0b" and row["status"] in (
                        "in_flight",
                        "indeterminate",
                    ):
                        return self._transition(conn, run_id, WriteResult.NO_ADMISSIBLE_BASIS)
                    return done
                if row["status"] == "indeterminate":
                    return self._transition(conn, run_id, WriteResult.ALREADY_INDETERMINATE)
                return self._settle_failed(
                    conn,
                    row,
                    basis=basis,
                    code=code,
                    message=message,
                    completion=completion,
                    reason=reason,
                    expected_version=expected_version,
                    source_status="in_flight",
                )
        finally:
            conn.close()

    def mark_indeterminate(self, run_id: RunId, expected_version: int) -> Transition:
        conn = connect(self._path)
        try:
            with write_transaction(conn):
                row = self._run_row(conn, run_id)
                done = self._terminal_result(conn, row)
                if done is not None:
                    return done
                if row["status"] == "indeterminate":
                    return self._transition(conn, run_id, WriteResult.ALREADY_INDETERMINATE)
                if row["closed_at"] is None:
                    return self._transition(conn, run_id, WriteResult.WRONG_SOURCE)
                if row["state_version"] != expected_version:
                    return self._transition(conn, run_id, WriteResult.STALE_VERSION)
                self._update_run(
                    conn,
                    run_id,
                    {"status": "indeterminate"},
                    "status = 'in_flight' AND closed_at IS NOT NULL",
                )
                return self._transition(conn, run_id, WriteResult.APPLIED)
        finally:
            conn.close()

    def settle_indeterminate(
        self,
        run_id: RunId,
        *,
        basis: EvidenceBasis,
        code: str,
        message: str,
        completion: CompletionObserved,
        expected_version: int,
    ) -> Transition:
        conn = connect(self._path)
        try:
            with write_transaction(conn):
                row = self._run_row(conn, run_id)
                if row["status"] == "succeeded":
                    return self._transition(conn, run_id, WriteResult.PUBLISHED)
                if row["status"] == "failed":
                    return self._transition(conn, run_id, WriteResult.SETTLED)  # idempotent
                if row["record_epoch"] != "0b":
                    return self._transition(conn, run_id, WriteResult.NO_ADMISSIBLE_BASIS)
                if row["status"] != "indeterminate":
                    return self._transition(conn, run_id, WriteResult.WRONG_SOURCE)
                return self._settle_failed(
                    conn,
                    row,
                    basis=basis,
                    code=code,
                    message=message,
                    completion=completion,
                    reason=None,
                    expected_version=expected_version,
                    source_status="indeterminate",
                )
        finally:
            conn.close()

    # -- configuration -------------------------------------------------------------------------

    def register_configuration(self, digest: str, canonical: str) -> bool:
        conn = connect(self._path)
        try:
            with write_transaction(conn):
                row = conn.execute(
                    "SELECT manifest FROM effective_configurations WHERE digest = ?", (digest,)
                ).fetchone()
                if row is None:
                    conn.execute(
                        "INSERT INTO effective_configurations (digest, manifest, created_at)"
                        " VALUES (?, ?, ?)",
                        (digest, canonical, self._now()),
                    )
                elif row["manifest"] != canonical:
                    return False  # the stored (immutable) manifest differs: do not trust it
                return True
        finally:
            conn.close()

    def get_configuration_manifest(self, digest: str) -> str | None:
        conn = connect(self._path)
        try:
            with read_transaction(conn):
                row = conn.execute(
                    "SELECT manifest FROM effective_configurations WHERE digest = ?", (digest,)
                ).fetchone()
                return None if row is None else str(row["manifest"])
        finally:
            conn.close()

    def get_current_binding(self, conversation_id: ConversationId) -> ConfigurationBinding | None:
        conn = connect(self._path)
        try:
            with read_transaction(conn):
                row = conn.execute(
                    "SELECT * FROM conversation_configuration_bindings WHERE conversation_id = ?"
                    " ORDER BY seq DESC LIMIT 1",
                    (conversation_id,),
                ).fetchone()
                return None if row is None else _config_binding(row)
        finally:
            conn.close()

    def bind_legacy_conversations(self, digest: str, evidence: str) -> int:
        conn = connect(self._path)
        try:
            with write_transaction(conn):
                rows = conn.execute(
                    "SELECT c.id FROM conversations c WHERE c.record_epoch = 'legacy_0a'"
                    " AND NOT EXISTS (SELECT 1 FROM conversation_configuration_bindings b"
                    " WHERE b.conversation_id = c.id)"
                ).fetchall()
                now = self._now()
                for row in rows:
                    conn.execute(
                        "INSERT INTO conversation_configuration_bindings (conversation_id, seq,"
                        " configuration_digest, origin, baseline_evidence, created_at)"
                        " VALUES (?, 1, ?, 'legacy_baseline', ?, ?)",
                        (row["id"], digest, evidence, now),
                    )
                return len(rows)
        finally:
            conn.close()

    def adopt_configuration(
        self, owner: UserId, conversation_id: ConversationId, adoption_id: str, digest: str
    ) -> ConfigurationBinding:
        conn = connect(self._path)
        try:
            with write_transaction(conn):
                prior = conn.execute(
                    "SELECT * FROM conversation_configuration_bindings"
                    " WHERE owner_user_id = ? AND adoption_id = ?",
                    (owner, adoption_id),
                ).fetchone()
                if prior is not None:
                    if (
                        prior["conversation_id"] != conversation_id
                        or prior["configuration_digest"] != digest
                    ):
                        raise IdempotencyConflict(
                            "This adoption id was already used for a different change."
                        )
                    return _config_binding(prior)
                owned = conn.execute(
                    "SELECT 1 FROM conversations WHERE id = ? AND owner_user_id = ?",
                    (conversation_id, owner),
                ).fetchone()
                if owned is None:
                    raise ConversationNotFound("Conversation not found.")
                if conn.execute(
                    "SELECT 1 FROM model_runs WHERE conversation_id = ?"
                    f" AND status IN {_UNSETTLED_SQL}",
                    (conversation_id,),
                ).fetchone():
                    raise ConversationBusy(
                        "A configuration cannot change while a run is unsettled."
                    )
                if (
                    conn.execute(
                        "SELECT 1 FROM effective_configurations WHERE digest = ?", (digest,)
                    ).fetchone()
                    is None
                ):
                    raise ConfigurationUnavailable("That configuration is not known.")
                last = conn.execute(
                    "SELECT COALESCE(MAX(seq), 0) AS s FROM conversation_configuration_bindings"
                    " WHERE conversation_id = ?",
                    (conversation_id,),
                ).fetchone()
                seq = int(last["s"]) + 1
                conn.execute(
                    "INSERT INTO conversation_configuration_bindings (conversation_id, seq,"
                    " configuration_digest, origin, owner_user_id, adoption_id, created_at)"
                    " VALUES (?, ?, ?, 'adoption', ?, ?, ?)",
                    (conversation_id, seq, digest, owner, adoption_id, self._now()),
                )
                row = conn.execute(
                    "SELECT * FROM conversation_configuration_bindings"
                    " WHERE conversation_id = ? AND seq = ?",
                    (conversation_id, seq),
                ).fetchone()
                return _config_binding(row)
        finally:
            conn.close()

    # -- HistorySource -------------------------------------------------------------------------

    def read_messages_through(
        self, conversation_id: ConversationId, last_message_id: MessageId
    ) -> tuple[Message, ...]:
        conn = connect(self._path)
        try:
            with read_transaction(conn):
                rows = conn.execute(
                    "SELECT * FROM messages WHERE conversation_id = ? AND position <="
                    " (SELECT position FROM messages WHERE id = ? AND conversation_id = ?)"
                    " ORDER BY position",
                    (conversation_id, last_message_id, conversation_id),
                ).fetchall()
                return tuple(_message(r) for r in rows)
        finally:
            conn.close()
