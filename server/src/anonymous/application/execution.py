"""Execution coordinator (C05): admission, dispatch, publication and settlement of one attempt.

Order of durable checkpoints (architecture §8, CB-02..CB-05):

1. the user message (and a ``pending`` run) is committed — nothing else happens before this;
2. the dispatch association (model/runtime identity) is committed — the model is not called
   before this;
3. the model is invoked with no transaction open;
4. the assistant message and the run's success are committed atomically, or the run is settled
   ``failed`` with no assistant message.

A response is reported only from what the store confirmed. If the store cannot confirm, the
coordinator raises rather than claiming success or absence.
"""

from __future__ import annotations

import hashlib
import logging

from anonymous.application.context import ContextBuilder
from anonymous.application.ports.model import (
    ModelExecutionError,
    ModelIdentity,
    ModelOutput,
    ModelPort,
)
from anonymous.application.ports.persistence import ExecutionStore, SubmissionOutcome
from anonymous.domain.errors import AnonymousError, StorageFailure
from anonymous.domain.ids import ConversationId, SubmissionId, UserId
from anonymous.domain.models import ModelRun, validate_message_content

logger = logging.getLogger("anonymous.execution")

FAILURE_MESSAGES = {
    "context_unavailable": "The conversation history could not be read, so nothing was sent.",
    "dispatch_not_recorded": "The attempt could not be recorded, so nothing was sent.",
    "runtime_error": "The model runtime failed.",
    "empty_output": "The model returned no content.",
    "runtime_identity_mismatch": "The model that responded did not match the one dispatched.",
    "response_not_saved": "The model responded but the response could not be saved.",
}
_MAX_FAILURE_MESSAGE_CHARS = 200


class ExecutionCoordinator:
    def __init__(
        self,
        store: ExecutionStore,
        context: ContextBuilder,
        model: ModelPort,
    ) -> None:
        self._store = store
        self._context = context
        self._model = model

    def submit(
        self,
        *,
        owner: UserId,
        conversation_id: ConversationId,
        submission_id: SubmissionId,
        content: str,
    ) -> SubmissionOutcome:
        content = validate_message_content(content)
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()

        # Checkpoint 1: committed user message + pending run, or replay/refusal.
        admitted = self._store.admit_submission(
            owner=owner,
            conversation_id=conversation_id,
            submission_id=submission_id,
            content=content,
            content_sha256=digest,
        )
        if admitted.replayed:
            return admitted  # resolves the original outcome; never starts new work

        user_message = admitted.user_message
        run = admitted.run

        try:
            request = self._context.build(user_message)
        except StorageFailure:
            return self._fail(admitted, run, "context_unavailable")

        # Checkpoint 2: identities durable before invocation.
        identity = self._model.identity
        try:
            run = self._store.record_dispatch(run.id, identity.model_id, identity.runtime_id)
        except StorageFailure:
            return self._fail(admitted, run, "dispatch_not_recorded")
        # StorageOutcomeUnknown propagates: the model is not invoked and nothing is claimed.

        # Checkpoint 3: invoke with no transaction open.
        try:
            output = self._model.generate(request)
        except ModelExecutionError as error:
            return self._fail(admitted, run, error.code, error.public_message)
        except Exception as error:  # adapter bug or vendor error; never log content
            logger.error("model adapter raised run=%s type=%s", run.id, type(error).__name__)
            return self._fail(admitted, run, "runtime_error")

        problem = self._check_output(output, identity)
        if problem is not None:
            return self._fail(admitted, run, problem)

        # Checkpoint 4: coherent publication.
        try:
            published = self._store.publish_response(run.id, output.content)
        except StorageFailure:
            return self._fail(admitted, run, "response_not_saved")
        # StorageOutcomeUnknown propagates: the response may be durable; a replay of the same
        # submission reports the real state.
        return SubmissionOutcome(
            user_message=user_message,
            run=published.run,
            assistant_message=published.message,
            replayed=False,
        )

    @staticmethod
    def _check_output(output: ModelOutput, dispatched: ModelIdentity) -> str | None:
        if output.identity != dispatched:
            return "runtime_identity_mismatch"
        if not output.content.strip():
            return "empty_output"
        return None

    def _fail(
        self,
        admitted: SubmissionOutcome,
        run: ModelRun,
        code: str,
        message: str | None = None,
    ) -> SubmissionOutcome:
        public = (message or FAILURE_MESSAGES.get(code) or "Generation failed.")[
            :_MAX_FAILURE_MESSAGE_CHARS
        ]
        logger.warning("generation failed run=%s code=%s", run.id, code)
        try:
            settled = self._store.settle_failed(run.id, code, public)
        except AnonymousError:
            # Could not durably record the failure: report that honestly instead of a made-up
            # terminal label. Startup disposition handles the run if the process ends first.
            logger.error("failure disposition not recorded run=%s code=%s", run.id, code)
            raise
        return SubmissionOutcome(
            user_message=admitted.user_message,
            run=settled,
            assistant_message=None,
            replayed=False,
        )
