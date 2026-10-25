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
from anonymous.adapters.model.llama_http import LlamaHttpRuntime
from anonymous.adapters.model.llama_launch_record import LaunchRecordError, read_key, read_record
from anonymous.adapters.persistence.sqlite.instance_guard import InstanceGuard
from anonymous.adapters.persistence.sqlite.migrations import migrate
from anonymous.adapters.persistence.sqlite.store import SqliteStore
from anonymous.application.configuration import (
    ConfigurationCatalog,
    ConfigurationService,
    default_configuration_digest,
    shipped_configurations,
)
from anonymous.application.control import BindingControlRouter
from anonymous.application.conversations import ConversationService
from anonymous.application.execution import ExecutionCoordinator
from anonymous.application.ports.model import RuntimePort, SynchronousModel
from anonymous.application.ports.persistence import Clock
from anonymous.application.reconcile import ReconcileReport
from anonymous.application.supervisor import Checkpoint, ExecutionSettings, no_checkpoint
from anonymous.config import (
    RUNTIME_LLAMA_DEV,
    RuntimeConfigurationError,
    Settings,
    validate_runtime_settings,
)
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


def preflight_runtime(settings: Settings) -> None:
    """Everything about the runtime selection that can be checked before any side effect.

    For the dev-only external runtime this includes loading the launch record and key file:
    missing, unsafe or malformed launch metadata refuses startup before the dataset is created or
    migrated (ADR-0015). Whether the recorded process is live is checked per attempt, not here.
    """
    validate_runtime_settings(settings)
    if settings.runtime == RUNTIME_LLAMA_DEV:
        assert settings.llama_launch_record is not None  # validated above
        try:
            read_key(read_record(settings.llama_launch_record))
        except LaunchRecordError as error:
            raise RuntimeConfigurationError(
                f"the llama launch record or its key file is missing or invalid ({error.code})"
            ) from error


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
    preflight_runtime(settings)  # before anything is opened or created; fails closed (ADR-0015)
    _prepare_data_dir(settings.db_path)
    guard = InstanceGuard(settings.db_path)
    guard.acquire()
    try:
        db_path = guard.identity.path  # one canonical path for every component
        schema_version = migrate(db_path)
        store = SqliteStore(db_path, clock or SystemClock())
        owner = store.ensure_dev_owner()
        chosen_catalog = catalog or ConfigurationCatalog(
            shipped_configurations(), default_digest=default_configuration_digest()
        )
        configuration = ConfigurationService(store, chosen_catalog)
        configuration.startup()

        chosen_runtime: RuntimePort
        if runtime is not None:
            chosen_runtime = runtime
        elif settings.runtime == RUNTIME_LLAMA_DEV:
            assert settings.llama_launch_record is not None  # validated above
            logger.warning(
                "EXTERNAL RUNTIME (dev, ADR-0015): synthetic data only; a non-clean outcome can"
                " quarantine this dataset permanently"
            )
            chosen_runtime = LlamaHttpRuntime(
                settings.llama_launch_record,
                max_tokens=settings.llama_max_tokens,
                max_input_chars=settings.llama_max_input_chars,
            )
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
