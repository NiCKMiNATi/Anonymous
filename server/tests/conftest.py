from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from anonymous.adapters.persistence.sqlite.migrations import migrate
from anonymous.adapters.persistence.sqlite.store import SqliteStore
from anonymous.application.context import ContextBuilder
from anonymous.application.conversations import ConversationService
from anonymous.application.execution import ExecutionCoordinator
from anonymous.application.ports.model import ModelPort
from anonymous.domain.ids import UserId
from tests.doubles import ManualClock


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.sqlite3"


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock()


@pytest.fixture
def store(db_path: Path, clock: ManualClock) -> Iterator[SqliteStore]:
    migrate(db_path)
    yield SqliteStore(db_path, clock)


@pytest.fixture
def owner(store: SqliteStore) -> UserId:
    return store.ensure_dev_owner()


class Services:
    """Wires real application services over a store and a model double."""

    def __init__(self, store: object, model: ModelPort) -> None:
        self.model = model
        self.coordinator = ExecutionCoordinator(
            store,  # type: ignore[arg-type]
            ContextBuilder(store),  # type: ignore[arg-type]
            model,
        )
        self.conversations = ConversationService(store, self.coordinator)  # type: ignore[arg-type]
