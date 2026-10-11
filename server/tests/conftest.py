from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from anonymous.adapters.model.inprocess import InProcessRuntime
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
from anonymous.application.supervisor import Checkpoint, ExecutionSettings, no_checkpoint
from anonymous.domain.ids import UserId
from tests.doubles import BoundStore, ManualClock

FAST = ExecutionSettings(
    deadline_seconds=10.0,
    handoff_deadline_seconds=1.0,
    control_deadline_seconds=1.0,
    slot_wait_seconds=2.0,
    slot_poll_seconds=0.005,
    closure_gate_wait_seconds=3.0,
    probe_attempts=2,
    probe_interval_seconds=0.01,
    republish_attempts=3,
    shutdown_join_seconds=2.0,
)


def register_default_configuration(db_path: Path) -> ConfigurationCatalog:
    """Register the shipped configuration with a clock of its own, so the test's clock is not
    consumed (several tests assert exact instants)."""
    catalog = ConfigurationCatalog(shipped_configurations())
    frozen = ManualClock(datetime(2025, 1, 1, tzinfo=UTC), step=timedelta(0))
    ConfigurationService(BoundStore(db_path, frozen), catalog).startup()
    return catalog


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.sqlite3"


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock()


@pytest.fixture
def catalog(db_path: Path) -> ConfigurationCatalog:
    migrate(db_path)
    return register_default_configuration(db_path)


@pytest.fixture
def store(
    db_path: Path, clock: ManualClock, catalog: ConfigurationCatalog
) -> Iterator[SqliteStore]:
    yield BoundStore(db_path, clock)


@pytest.fixture
def config_digest(catalog: ConfigurationCatalog) -> str:
    return catalog.default_digest


@pytest.fixture
def owner(store: SqliteStore) -> UserId:
    return store.ensure_dev_owner()


class Services:
    """Wires real application services over a store and a runtime (or an in-process model)."""

    def __init__(
        self,
        store: object,
        model: SynchronousModel | RuntimePort,
        *,
        catalog: ConfigurationCatalog | None = None,
        settings: ExecutionSettings = FAST,
        boot_id: str | None = None,
        checkpoint: Checkpoint = no_checkpoint,
        guard_held: bool = True,
    ) -> None:
        self.runtime: RuntimePort = (
            model  # type: ignore[assignment]
            if hasattr(model, "describe")
            else InProcessRuntime(model)
        )
        self.model = model
        self.boot_id = boot_id or str(uuid.uuid4())
        self.catalog = catalog or ConfigurationCatalog(shipped_configurations())
        self.router = BindingControlRouter(
            [self.runtime], current_boot_id=self.boot_id, guard_held=lambda: guard_held
        )
        self.coordinator = ExecutionCoordinator(
            store=store,  # type: ignore[arg-type]
            history=store,  # type: ignore[arg-type]
            runtime=self.runtime,
            router=self.router,
            catalog=self.catalog,
            settings=settings,
            boot_id=self.boot_id,
            checkpoint=checkpoint,
        )
        self.configuration = ConfigurationService(store, self.catalog)  # type: ignore[arg-type]
        self.conversations = ConversationService(
            store,  # type: ignore[arg-type]
            self.coordinator,
            self.catalog,
            self.configuration,
        )
