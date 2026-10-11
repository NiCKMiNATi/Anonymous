"""Stable failure codes and their sanitized, bounded public messages (LD-04 §3.4).

Runtime-supplied text is never copied through; adapters' ``public_message`` is bounded and used
only for codes this module does not know.
"""

from __future__ import annotations

from anonymous.domain.evidence import ClosureReason

MAX_FAILURE_MESSAGE_CHARS = 200

FAILURE_MESSAGES = {
    "context_unavailable": "The conversation history could not be read, so nothing was sent.",
    "context_exceeds_capacity": (
        "The conversation is longer than the model can accept; nothing was sent."
    ),
    "dispatch_not_recorded": "The attempt could not be recorded, so nothing was sent.",
    "binding_unavailable": "The model runtime could not be prepared, so nothing was sent.",
    "runtime_busy": "The model runtime was busy for too long, so nothing was sent.",
    "runtime_quarantined": (
        "An earlier execution could not be shown to have ended; nothing was sent."
    ),
    "generation_blocked_legacy_unresolved": (
        "An execution recorded before this version is unresolved; nothing was sent."
    ),
    "configuration_unavailable": (
        "The conversation's configuration is unavailable; nothing was sent."
    ),
    "interrupted_before_dispatch": "The attempt ended before it was dispatched.",
    "runtime_unavailable": "The model runtime did not accept the request.",
    "runtime_error": "The model runtime failed.",
    "empty_output": "The model returned no content.",
    "output_truncated": "The model's response was cut off and was not saved.",
    "model_identity_mismatch": "The model that responded did not match the one dispatched.",
    "runtime_instance_mismatch": (
        "A response came from a runtime instance other than the dispatched one."
    ),
    "response_not_saved": "The model responded but the response could not be saved.",
    "deadline_exceeded": "The attempt did not finish in time and was closed.",
    "connection_lost": "The connection to the model runtime was lost and the attempt was closed.",
    "supervisor_fault": "The attempt was closed after an internal fault.",
    "interrupted_shutdown": "The server shut down and the attempt was closed.",
    "interrupted_server_restart": "The server restarted and the attempt was closed.",
}

_CODE_FOR_REASON = {
    ClosureReason.DEADLINE: "deadline_exceeded",
    ClosureReason.SHUTDOWN: "interrupted_shutdown",
    ClosureReason.PUBLICATION_UNCONFIRMED: "response_not_saved",
    ClosureReason.CONNECTION_LOST: "connection_lost",
    ClosureReason.RUNTIME_FAILURE: "runtime_error",
    ClosureReason.INSTANCE_MISMATCH: "runtime_instance_mismatch",
    ClosureReason.SUPERVISOR_FAULT: "supervisor_fault",
    ClosureReason.ORPHAN_RECONCILE: "interrupted_server_restart",
}


def code_for_reason(reason: ClosureReason | None) -> str:
    return _CODE_FOR_REASON.get(reason, "supervisor_fault") if reason else "supervisor_fault"


def public_message(code: str, adapter_message: str | None = None) -> str:
    text = FAILURE_MESSAGES.get(code) or adapter_message or "Generation failed."
    return text[:MAX_FAILURE_MESSAGE_CHARS]
