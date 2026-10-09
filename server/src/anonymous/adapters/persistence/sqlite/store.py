"""SqliteStore — fulfils the application-owned persistence ports with SQLite.

Transaction boundaries (each is one ``BEGIN IMMEDIATE`` ... ``COMMIT``):

* ``create_conversation``  — conversation row (CB-01).
* ``admit_submission``     — replay/conflict check, ownership + admission check, user message,
                             pending run, submission association (CB-02/CB-03 prefix).
* ``record_dispatch``      — pending -> in_flight with model/runtime identity.
* ``publish_response``     — assistant message + run succeeded together (CB-04).
* ``settle_failed``        — run failed; no message.
* ``recover_unsettled_runs`` — startup disposition.

Reads use one deferred transaction per call so related rows come from a single snapshot. A new
short-lived connection is used per operation (no connection is shared across threads).
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
    ConversationHistory,
    PublishedResponse,
    RecoveryReport,
    SubmissionOutcome,
)
from anonymous.domain.errors import (
    ConversationBusy,
    ConversationNotFound,
    IdempotencyConflict,
    RunStateConflict,
    StorageFailure,
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
    Conversation,
    Message,
    MessageRole,
    ModelRun,
    RunStatus,
)

_UNSETTLED_SQL = "('pending', 'in_flight', 'indeterminate')"


def _message(row: sqlite3.Row) -> Message:
    return Message(
        id=MessageId(row["id"]),
        conversation_id=ConversationId(row["conversation_id"]),
        position=row["position"],
        role=MessageRole(row["role"]),
        content=row["content"],
        committed_at=decode_instant(row["committed_at"]),
        produced_by_run_id=RunId(row["produced_by_run_id"]) if row["produced_by_run_id"] else None,
    )


def _run(row: sqlite3.Row) -> ModelRun:
    def instant(column: str) -> Any:
        return decode_instant(row[column]) if row[column] is not None else None

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
    )


def _conversation(row: sqlite3.Row) -> Conversation:
    return Conversation(
        id=ConversationId(row["id"]),
        owner_id=UserId(row["owner_user_id"]),
        title=row["title"],
        created_at=decode_instant(row["created_at"]),
    )


class SqliteStore:
    """Implements ``ConversationStore``, ``ExecutionStore`` and ``HistorySource``."""

    def __init__(self, db_path: str | Path, clock: Clock) -> None:
        self._path = db_path
        self._clock = clock

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
                    "INSERT INTO users (id, created_at) VALUES (?, ?)",
                    (user_id, encode_instant(self._clock.now())),
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

    def create_conversation(self, owner: UserId, title: str | None) -> Conversation:
        conn = connect(self._path)
        try:
            with write_transaction(conn):
                conversation_id = ConversationId(new_uuid())
                created_at = self._clock.now()
                conn.execute(
                    "INSERT INTO conversations (id, owner_user_id, title, created_at)"
                    " VALUES (?, ?, ?, ?)",
                    (conversation_id, owner, title, encode_instant(created_at)),
                )
            return Conversation(
                conversation_id, owner, title, decode_instant(encode_instant(created_at))
            )
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
                    " ORDER BY requested_at, rowid",
                    (conversation_id,),
                ).fetchall()
                return ConversationHistory(
                    conversation=_conversation(row),
                    messages=tuple(_message(r) for r in messages),
                    runs=tuple(_run(r) for r in runs),
                )
        finally:
            conn.close()

    # -- ExecutionStore ------------------------------------------------------------------------

    def admit_submission(
        self,
        *,
        owner: UserId,
        conversation_id: ConversationId,
        submission_id: SubmissionId,
        content: str,
        content_sha256: str,
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
                    return self._outcome(conn, existing, replayed=True)

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

                now = encode_instant(self._clock.now())
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
                    " requested_at) VALUES (?, ?, ?, 'pending', ?)",
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
                user_row = conn.execute(
                    "SELECT * FROM messages WHERE id = ?", (message_id,)
                ).fetchone()
                run_row = conn.execute(
                    "SELECT * FROM model_runs WHERE id = ?", (run_id,)
                ).fetchone()
                outcome = SubmissionOutcome(
                    user_message=_message(user_row),
                    run=_run(run_row),
                    assistant_message=None,
                    replayed=False,
                )
            return outcome
        finally:
            conn.close()

    def record_dispatch(self, run_id: RunId, model_id: str, runtime_id: str) -> ModelRun:
        conn = connect(self._path)
        try:
            with write_transaction(conn):
                now = encode_instant(self._clock.now())
                cursor = conn.execute(
                    "UPDATE model_runs SET status = 'in_flight', model_id = ?, runtime_id = ?,"
                    " dispatched_at = ? WHERE id = ? AND status = 'pending'",
                    (model_id, runtime_id, now, run_id),
                )
                if cursor.rowcount != 1:
                    raise RunStateConflict("The run is not awaiting dispatch.")
                row = conn.execute("SELECT * FROM model_runs WHERE id = ?", (run_id,)).fetchone()
                run = _run(row)
            return run
        finally:
            conn.close()

    def publish_response(self, run_id: RunId, content: str) -> PublishedResponse:
        conn = connect(self._path)
        try:
            with write_transaction(conn):
                run_row = conn.execute(
                    "SELECT * FROM model_runs WHERE id = ?", (run_id,)
                ).fetchone()
                if run_row is None or run_row["status"] != "in_flight":
                    raise RunStateConflict("The run is not in flight; no response was saved.")
                conversation_id = run_row["conversation_id"]
                now = encode_instant(self._clock.now())
                message_id = MessageId(new_uuid())
                position = self._next_position(conn, conversation_id)
                conn.execute(
                    "INSERT INTO messages (id, conversation_id, position, role, content,"
                    " committed_at, produced_by_run_id) VALUES (?, ?, ?, 'assistant', ?, ?, ?)",
                    (message_id, conversation_id, position, content, now, run_id),
                )
                cursor = conn.execute(
                    "UPDATE model_runs SET status = 'succeeded', settled_at = ?"
                    " WHERE id = ? AND status = 'in_flight'",
                    (now, run_id),
                )
                if cursor.rowcount != 1:
                    raise RunStateConflict("The run changed while publishing; nothing was saved.")
                message = _message(
                    conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
                )
                run = _run(
                    conn.execute("SELECT * FROM model_runs WHERE id = ?", (run_id,)).fetchone()
                )
            return PublishedResponse(message=message, run=run)
        finally:
            conn.close()

    def settle_failed(self, run_id: RunId, code: str, message: str) -> ModelRun:
        conn = connect(self._path)
        try:
            with write_transaction(conn):
                now = encode_instant(self._clock.now())
                cursor = conn.execute(
                    "UPDATE model_runs SET status = 'failed', failure_code = ?,"
                    " failure_message = ?, settled_at = ?"
                    " WHERE id = ? AND status IN ('pending', 'in_flight')",
                    (code, message, now, run_id),
                )
                if cursor.rowcount != 1:
                    raise RunStateConflict("The run cannot be settled as failed.")
                run = _run(
                    conn.execute("SELECT * FROM model_runs WHERE id = ?", (run_id,)).fetchone()
                )
            return run
        finally:
            conn.close()

    def recover_unsettled_runs(self) -> RecoveryReport:
        conn = connect(self._path)
        try:
            with write_transaction(conn):
                now = encode_instant(self._clock.now())
                failed = conn.execute(
                    "UPDATE model_runs SET status = 'failed',"
                    " failure_code = 'interrupted_before_dispatch',"
                    " failure_message = 'The server stopped before this attempt was dispatched.',"
                    " settled_at = ? WHERE status = 'pending'",
                    (now,),
                ).rowcount
                indeterminate = conn.execute(
                    "UPDATE model_runs SET status = 'indeterminate' WHERE status = 'in_flight'"
                ).rowcount
            return RecoveryReport(settled_failed=failed, marked_indeterminate=indeterminate)
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

    # -- helpers -------------------------------------------------------------------------------

    @staticmethod
    def _next_position(conn: sqlite3.Connection, conversation_id: str) -> int:
        row = conn.execute(
            "SELECT COALESCE(MAX(position), 0) + 1 AS next FROM messages WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        return int(row["next"])

    @staticmethod
    def _outcome(
        conn: sqlite3.Connection, submission_row: sqlite3.Row, *, replayed: bool
    ) -> SubmissionOutcome:
        user_row = conn.execute(
            "SELECT * FROM messages WHERE id = ?", (submission_row["user_message_id"],)
        ).fetchone()
        run_row = conn.execute(
            "SELECT * FROM model_runs WHERE id = ?", (submission_row["run_id"],)
        ).fetchone()
        assistant_row = conn.execute(
            "SELECT * FROM messages WHERE produced_by_run_id = ?", (submission_row["run_id"],)
        ).fetchone()
        return SubmissionOutcome(
            user_message=_message(user_row),
            run=_run(run_row),
            assistant_message=_message(assistant_row) if assistant_row is not None else None,
            replayed=replayed,
        )
