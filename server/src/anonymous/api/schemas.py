"""API DTOs. Deliberately separate from domain objects so the wire contract can evolve
independently (the contract is an implementation decision of slice 0A, not the accepted API
design)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from anonymous.application.ports.persistence import ConversationHistory, SubmissionOutcome
from anonymous.domain.instants import encode_instant
from anonymous.domain.models import Conversation, Message, ModelRun


class CreateConversationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = None


class SendMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    submission_id: str
    content: str


class ConversationDto(BaseModel):
    id: str
    title: str | None
    created_at: str  # absolute UTC instant, ISO-8601 with 'Z'


class ConversationListDto(BaseModel):
    conversations: list[ConversationDto]


class MessageDto(BaseModel):
    id: str
    position: int  # authoritative order; clients must not sort by time
    role: Literal["user", "assistant"]
    content: str
    committed_at: str  # authoritative commit instant (absolute UTC)
    produced_by_run_id: str | None


class RunDto(BaseModel):
    id: str
    triggering_message_id: str
    status: Literal["pending", "in_flight", "succeeded", "failed", "indeterminate"]
    model_id: str | None
    runtime_id: str | None
    failure_code: str | None
    failure_message: str | None
    kind: Literal["initial", "retry"] = "initial"
    retry_of_run_id: str | None = None
    termination_basis: str | None = None
    completion_observed: str | None = None


class RetryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    retry_id: str
    message_id: str


class ConversationDetailDto(BaseModel):
    conversation: ConversationDto
    messages: list[MessageDto]
    runs: list[RunDto]


class SubmissionResultDto(BaseModel):
    submission_id: str
    replayed: bool
    user_message: MessageDto
    run: RunDto
    assistant_message: MessageDto | None


class GenerationDto(BaseModel):
    state: Literal["open", "blocked"]
    reason: str | None = None
    legacy_unresolved_runs: int = 0
    quarantined_runs: int = 0


class HealthDto(BaseModel):
    status: Literal["ok", "unavailable"]
    schema_version: int | None
    storage: Literal["ok", "unavailable"]
    security: str
    generation: GenerationDto | None = None


def conversation_dto(c: Conversation) -> ConversationDto:
    return ConversationDto(id=c.id, title=c.title, created_at=encode_instant(c.created_at))


def message_dto(m: Message) -> MessageDto:
    return MessageDto(
        id=m.id,
        position=m.position,
        role=m.role.value,
        content=m.content,
        committed_at=encode_instant(m.committed_at),
        produced_by_run_id=m.produced_by_run_id,
    )


def run_dto(r: ModelRun) -> RunDto:
    return RunDto(
        id=r.id,
        triggering_message_id=r.triggering_message_id,
        status=r.status.value,
        model_id=r.model_id,
        runtime_id=r.runtime_id,
        failure_code=r.failure_code,
        failure_message=r.failure_message,
        kind=r.kind.value,
        retry_of_run_id=r.retry_of_run_id,
        termination_basis=r.termination_basis.value if r.termination_basis else None,
        completion_observed=r.completion_observed.value if r.completion_observed else None,
    )


def detail_dto(h: ConversationHistory) -> ConversationDetailDto:
    return ConversationDetailDto(
        conversation=conversation_dto(h.conversation),
        messages=[message_dto(m) for m in h.messages],
        runs=[run_dto(r) for r in h.runs],
    )


def submission_dto(submission_id: str, o: SubmissionOutcome) -> SubmissionResultDto:
    return SubmissionResultDto(
        submission_id=submission_id,
        replayed=o.replayed,
        user_message=message_dto(o.user_message),
        run=run_dto(o.run),
        assistant_message=message_dto(o.assistant_message) if o.assistant_message else None,
    )
