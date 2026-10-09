from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from anonymous.api.app import create_app
from anonymous.application.ports.model import ModelPort
from anonymous.application.ports.persistence import Clock
from anonymous.config import Settings
from tests.doubles import ManualClock

BASE_URL = "http://127.0.0.1:8000"


@contextmanager
def open_client(
    db_path: Path,
    *,
    model: ModelPort | None = None,
    clock: Clock | None = None,
    client_dist: Path | None = None,
) -> Iterator[TestClient]:
    settings = Settings(db_path=db_path, port=8000, client_dist=client_dist)
    app = create_app(settings, model=model, clock=clock or ManualClock())
    with TestClient(app, base_url=BASE_URL) as client:
        yield client


@pytest.fixture
def client(db_path: Path) -> Iterator[TestClient]:
    with open_client(db_path) as c:
        yield c
