"""FastAPI application factory and routes (C02).

Routes only validate shape, resolve the acting owner, call an application service and project the
result to DTOs. Business rules live in the application and domain layers.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from anonymous.api import schemas
from anonymous.api.guards import LocalOnlyGuard
from anonymous.application.ports.model import RuntimePort, SynchronousModel
from anonymous.application.ports.persistence import Clock
from anonymous.application.supervisor import ExecutionSettings
from anonymous.composition import Application, build_application
from anonymous.config import Settings
from anonymous.domain import errors
from anonymous.domain.ids import UserId

logger = logging.getLogger("anonymous.api")

_STATUS_BY_CODE: dict[type[errors.AnonymousError], int] = {
    errors.InvalidIdentifier: 400,
    errors.InvalidMessage: 422,
    errors.InvalidTitle: 422,
    errors.ConversationNotFound: 404,
    errors.ConversationBusy: 409,
    errors.IdempotencyConflict: 409,
    errors.RunStateConflict: 409,
    errors.GenerationBlocked: 409,
    errors.RuntimeQuarantined: 409,
    errors.LegacyUnresolvedBlock: 409,
    errors.ConfigurationUnavailable: 409,
    errors.ConfigurationUnbound: 409,
    errors.ExecutionUnresolved: 409,
    errors.RetryNotEligible: 409,
    errors.StorageFailure: 503,
    errors.StorageOutcomeUnknown: 503,
}

_STORAGE_MESSAGES = {
    errors.StorageFailure.code: (
        "Storage was unavailable, so the operation was not completed. Reload the conversation to"
        " see exactly what was saved; retrying with the same submission id is safe."
    ),
    errors.StorageOutcomeUnknown.code: (
        "The server could not confirm whether the change was saved. Reload the conversation to"
        " see what was saved; retrying with the same submission id will not duplicate it."
    ),
}


def _error_response(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def get_application(request: Request) -> Application:
    application: Application = request.app.state.application
    return application


AppDep = Annotated[Application, Depends(get_application)]


def current_owner(application: AppDep) -> UserId:
    """DEVELOPMENT ONLY seam: slice 0A has no authentication, so the acting owner is the single
    provisioned dev owner. C03 (device + session + resource authorization) replaces this."""
    return application.owner


OwnerDep = Annotated[UserId, Depends(current_owner)]

router = APIRouter(prefix="/api/v1")


@router.get("/health", response_model=schemas.HealthDto)
def health(application: AppDep) -> JSONResponse:
    security = (
        "none: development slice 0A, loopback only, no authentication; use synthetic data only"
    )
    try:
        version = application.store.schema_version()
        state = application.store.generation_state()
    except errors.AnonymousError:
        body = schemas.HealthDto(
            status="unavailable", schema_version=None, storage="unavailable", security=security
        )
        return JSONResponse(status_code=503, content=body.model_dump())
    reason = (
        errors.LegacyUnresolvedBlock.code
        if state.legacy_blockers
        else (errors.RuntimeQuarantined.code if state.quarantined_runs else None)
    )
    generation = schemas.GenerationDto(
        state="blocked" if reason else "open",
        reason=reason,
        legacy_unresolved_runs=len(state.legacy_blockers),
        quarantined_runs=len(state.quarantined_runs),
    )
    body = schemas.HealthDto(
        status="ok", schema_version=version, storage="ok", security=security, generation=generation
    )
    return JSONResponse(content=body.model_dump())


@router.post("/conversations", status_code=201, response_model=schemas.ConversationDto)
def create_conversation(
    body: schemas.CreateConversationRequest, application: AppDep, owner: OwnerDep
) -> schemas.ConversationDto:
    conversation = application.conversations.create_conversation(owner, body.title)
    return schemas.conversation_dto(conversation)


@router.get("/conversations", response_model=schemas.ConversationListDto)
def list_conversations(application: AppDep, owner: OwnerDep) -> schemas.ConversationListDto:
    items = application.conversations.list_conversations(owner)
    return schemas.ConversationListDto(conversations=[schemas.conversation_dto(c) for c in items])


@router.get("/conversations/{conversation_id}", response_model=schemas.ConversationDetailDto)
def get_conversation(
    conversation_id: str, application: AppDep, owner: OwnerDep
) -> schemas.ConversationDetailDto:
    return schemas.detail_dto(application.conversations.open_conversation(owner, conversation_id))


@router.post(
    "/conversations/{conversation_id}/messages",
    status_code=201,
    response_model=schemas.SubmissionResultDto,
)
def send_message(
    conversation_id: str,
    body: schemas.SendMessageRequest,
    response: Response,
    application: AppDep,
    owner: OwnerDep,
) -> schemas.SubmissionResultDto:
    outcome = application.conversations.send_message(
        owner, conversation_id, body.submission_id, body.content
    )
    if outcome.replayed:
        response.status_code = 200  # an already accepted submission; nothing new was created
    return schemas.submission_dto(body.submission_id, outcome)


@router.post(
    "/conversations/{conversation_id}/retry",
    status_code=201,
    response_model=schemas.SubmissionResultDto,
)
def retry_generation(
    conversation_id: str,
    body: schemas.RetryRequest,
    response: Response,
    application: AppDep,
    owner: OwnerDep,
) -> schemas.SubmissionResultDto:
    """Explicit retry: a new attempt on the same saved user message; never a new message."""
    outcome = application.conversations.retry_generation(
        owner, conversation_id, body.retry_id, body.message_id
    )
    if outcome.replayed:
        response.status_code = 200
    return schemas.submission_dto(body.retry_id, outcome)


def create_app(
    settings: Settings | None = None,
    *,
    model: SynchronousModel | None = None,
    runtime: RuntimePort | None = None,
    clock: Clock | None = None,
    execution_settings: ExecutionSettings | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        application = build_application(
            settings,
            model=model,
            runtime=runtime,
            clock=clock,
            execution_settings=execution_settings,
        )
        app.state.application = application
        app.state.shutdown_incomplete = False
        try:
            yield
        finally:
            # Ownership is released only if every worker ended; otherwise the process must exit.
            app.state.shutdown_incomplete = not application.shutdown()

    app = FastAPI(
        title="Anonymous (slice 0B-1 — development, no authentication)",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.include_router(router)

    @app.exception_handler(errors.AnonymousError)
    async def handle_domain_error(_: Request, error: errors.AnonymousError) -> JSONResponse:
        status = _STATUS_BY_CODE.get(type(error), 500)
        message = _STORAGE_MESSAGES.get(error.code, error.public_message)
        if status >= 500:
            logger.error("request failed code=%s", error.code)
        return _error_response(status, error.code, message)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, error: RequestValidationError) -> JSONResponse:
        # Report which fields are wrong, never the submitted values (they may be private).
        fields = sorted({".".join(str(p) for p in e["loc"][1:]) or "body" for e in error.errors()})
        return _error_response(
            422, "invalid_request", "The request was malformed: " + ", ".join(fields) + "."
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, error: Exception) -> JSONResponse:
        logger.error("unhandled error type=%s", type(error).__name__)
        return _error_response(500, "internal_error", "An internal error occurred.")

    _mount_client(app, settings.client_dist)
    # Added last so it wraps everything, including the static client.
    app.add_middleware(
        LocalOnlyGuard,
        allowed_hosts=settings.allowed_hosts(),
        allowed_origins=settings.allowed_origins(),
    )
    return app


def _mount_client(app: FastAPI, dist: Path | None) -> None:
    if dist is not None and (dist / "index.html").is_file():
        app.mount("/", StaticFiles(directory=dist, html=True), name="client")
