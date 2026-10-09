"""Composition root (C10): the only module that names concrete adapters and wires them."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from anonymous.adapters.clock import SystemClock
from anonymous.adapters.model.fake import FakeModelAdapter
from anonymous.adapters.persistence.sqlite.instance_guard import InstanceGuard
from anonymous.adapters.persistence.sqlite.migrations import migrate
from anonymous.adapters.persistence.sqlite.store import SqliteStore
from anonymous.application.context import ContextBuilder
from anonymous.application.conversations import ConversationService
from anonymous.application.execution import ExecutionCoordinator
from anonymous.application.ports.model import ModelPort
from anonymous.application.ports.persistence import Clock
from anonymous.config import Settings
from anonymous.domain.ids import UserId

logger = logging.getLogger("anonymous.composition")


@dataclass(slots=True)
class Application:
    conversations: ConversationService
    owner: UserId  # DEVELOPMENT: stands in for the authenticated principal (C03, not implemented)
    store: SqliteStore
    model: ModelPort
    guard: InstanceGuard
    schema_version: int

    def shutdown(self) -> None:
        self.guard.release()


def build_application(
    settings: Settings, *, model: ModelPort | None = None, clock: Clock | None = None
) -> Application:
    """Start the application: guard, migrate, provision dev owner, apply startup disposition.

    Readiness is only reached after this returns, i.e. after recovery (architecture C10).
    """
    db_path = settings.db_path
    _prepare_data_dir(db_path)
    guard = InstanceGuard(db_path)
    guard.acquire()
    try:
        schema_version = migrate(db_path)
        store = SqliteStore(db_path, clock or SystemClock())
        owner = store.ensure_dev_owner()
        report = store.recover_unsettled_runs()
        if report.settled_failed or report.marked_indeterminate:
            logger.warning(
                "startup disposition: settled_failed=%d marked_indeterminate=%d",
                report.settled_failed,
                report.marked_indeterminate,
            )
        chosen_model = model or FakeModelAdapter(delay_seconds=settings.fake_delay_seconds)
        coordinator = ExecutionCoordinator(store, ContextBuilder(store), chosen_model)
        return Application(
            conversations=ConversationService(store, coordinator),
            owner=owner,
            store=store,
            model=chosen_model,
            guard=guard,
            schema_version=schema_version,
        )
    except BaseException:
        guard.release()
        raise


def _prepare_data_dir(db_path: Path) -> None:
    parent = db_path.parent
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
