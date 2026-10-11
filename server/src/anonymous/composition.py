"""Composition root (C10): the only module that names concrete adapters and wires them."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

from anonymous.adapters.clock import SystemClock
from anonymous.adapters.model.fake import FakeModelAdapter
from anonymous.adapters.model.inprocess import InProcessRuntime
from anonymous.adapters.persistence.sqlite.instance_guard import InstanceGuard
from anonymous.adapters.persistence.sqlite.migrations import migrate
from anonymous.adapters.persistence.sqlite.store import SqliteStore
from anonymous.application.configuration import (
    ConfigurationCatalog,
    ConfigurationService,
    shipped_configurations,
)
from anonymous.application.control import BindingControlRouter
from anonymous.application.conversations import ConversationService
from anonymous.application.execution import ExecutionCoordinator
from anonymous.application.ports.model import RuntimePort, SynchronousModel
from anonymous.application.ports.persistence import Clock
from anonymous.application.reconcile import ReconcileReport
from anonymous.application.supervisor import Checkpoint, ExecutionSettings, no_checkpoint
from anonymous.config import Settings
from anonymous.domain.ids import UserId
from anonymous.domain.provenance import ComponentIdentity

logger = logging.getLogger("anonymous.composition")


@dataclass(slots=True)
class Application:
    conversations: ConversationService
    owner: UserId  # DEVELOPMENT: stands in for the authenticated principal (C03, not implemented)
    store: SqliteStore
    execution: ExecutionCoordinator
    catalog: ConfigurationCatalog
    guard: InstanceGuard
    schema_version: int
    boot_id: str
    startup_report: ReconcileReport

    def shutdown(self, timeout_seconds: float | None = None) -> bool:
        """Close active attempts and release process ownership **only if every worker ended**.

        Returns ``False`` if a worker is still alive: ownership is retained (the guard stays held),
        and the caller must let the process exit — never release ownership to finish shutdown.
        """
        finished = self.execution.shutdown(timeout_seconds)
        if not finished:
            logger.error("shutdown incomplete: a supervised worker is still alive; ownership kept")
            return False
        self.guard.release_when_quiescent(lambda: bool(self.execution.threads.outstanding()))
        return not self.guard.held


def _application_build() -> ComponentIdentity:
    try:
        version = metadata.version("anonymous-server")
    except metadata.PackageNotFoundError:
        version = "unknown"
    return ComponentIdentity.label_only(f"anonymous-server {version}")


def build_application(
    settings: Settings,
    *,
    runtime: RuntimePort | None = None,
    model: SynchronousModel | None = None,
    clock: Clock | None = None,
    execution_settings: ExecutionSettings | None = None,
    checkpoint: Checkpoint = no_checkpoint,
    catalog: ConfigurationCatalog | None = None,
) -> Application:
    """Start the application: guard, migrate, provision dev owner, configuration, reconcile.

    Readiness is only reached after this returns, i.e. after recovery (architecture C10).
    """
    _prepare_data_dir(settings.db_path)
    guard = InstanceGuard(settings.db_path)
    guard.acquire()
    try:
        db_path = guard.identity.path  # one canonical path for every component
        schema_version = migrate(db_path)
        store = SqliteStore(db_path, clock or SystemClock())
        owner = store.ensure_dev_owner()
        chosen_catalog = catalog or ConfigurationCatalog(shipped_configurations())
        configuration = ConfigurationService(store, chosen_catalog)
        configuration.startup()

        chosen_runtime: RuntimePort
        if runtime is not None:
            chosen_runtime = runtime
        else:
            chosen_runtime = InProcessRuntime(
                model or FakeModelAdapter(delay_seconds=settings.fake_delay_seconds)
            )
        boot_id = str(uuid.uuid4())
        router = BindingControlRouter(
            [chosen_runtime], current_boot_id=boot_id, guard_held=lambda: guard.held
        )
        coordinator = ExecutionCoordinator(
            store=store,
            history=store,
            runtime=chosen_runtime,
            router=router,
            catalog=chosen_catalog,
            settings=execution_settings or ExecutionSettings(),
            boot_id=boot_id,
            checkpoint=checkpoint,
            app_build=_application_build(),
        )
        report = coordinator.startup()
        if (
            report.pending_settled
            or report.settled
            or report.still_unresolved
            or (report.legacy_blockers)
        ):
            logger.warning(
                "startup disposition: pending_settled=%d settled=%d unresolved=%d"
                " legacy_blockers=%d",
                report.pending_settled,
                report.settled,
                report.still_unresolved,
                report.legacy_blockers,
            )
        return Application(
            conversations=ConversationService(store, coordinator, chosen_catalog, configuration),
            owner=owner,
            store=store,
            execution=coordinator,
            catalog=chosen_catalog,
            guard=guard,
            schema_version=schema_version,
            boot_id=boot_id,
            startup_report=report,
        )
    except BaseException:
        # No worker can exist yet (none is spawned before this function returns).
        guard.release()
        raise


def _prepare_data_dir(db_path: Path) -> None:
    parent = Path(db_path).expanduser().parent
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
