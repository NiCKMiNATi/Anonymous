"""Runtime selection: the fake model is the default; the real adapter is explicit and fenced."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

from anonymous import __main__ as entry
from anonymous.composition import build_application
from anonymous.config import (
    DEV_DATASET_SUFFIX,
    RUNTIME_FAKE,
    RUNTIME_LLAMA_DEV,
    RuntimeConfigurationError,
    Settings,
    require_dev_dataset,
    validate_runtime_settings,
)
from anonymous.domain.evidence import EvidenceBasis, LifetimeScope
from anonymous.domain.ids import new_uuid
from anonymous.domain.models import RunStatus
from tests.adapters.llama_fakes import FakeLlamaServer, write_launch
from tests.conftest import FAST


def dev(tmp_path: Path, **changes: object) -> Settings:
    base = Settings(
        db_path=tmp_path / "chat-dev.sqlite3",
        runtime=RUNTIME_LLAMA_DEV,
        llama_launch_record=tmp_path / "launch" / "launch.json",
    )
    return replace(base, **changes)  # type: ignore[arg-type]


# -- default ---------------------------------------------------------------------------------------


def test_the_default_runtime_is_the_fake_model_and_needs_no_dev_dataset(tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "anything.sqlite3")
    assert settings.runtime == RUNTIME_FAKE and settings.llama_launch_record is None
    validate_runtime_settings(settings)
    app = build_application(settings, execution_settings=FAST)
    try:
        cid = app.conversations.create_conversation(app.owner).id
        outcome = app.conversations.send_message(app.owner, cid, new_uuid(), "hello")
        assert outcome.assistant_message is not None
        assert outcome.assistant_message.content.startswith("Fake reply to: hello")
        binding = outcome.run.binding
        assert binding is not None and binding.lifetime_scope is LifetimeScope.OWNING_PROCESS
    finally:
        assert app.shutdown()


def test_environment_variables_select_nothing_unless_set(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "ANONYMOUS_RUNTIME",
        "ANONYMOUS_LLAMA_LAUNCH_RECORD",
        "ANONYMOUS_LLAMA_MAX_TOKENS",
        "ANONYMOUS_LLAMA_MAX_INPUT_CHARS",
    ):
        monkeypatch.delenv(name, raising=False)
    settings = Settings.from_env()
    assert settings.runtime == RUNTIME_FAKE and settings.llama_launch_record is None
    monkeypatch.setenv("ANONYMOUS_RUNTIME", "llama-dev")
    monkeypatch.setenv("ANONYMOUS_LLAMA_LAUNCH_RECORD", "/x/launch.json")
    monkeypatch.setenv("ANONYMOUS_LLAMA_MAX_TOKENS", "64")
    selected = Settings.from_env()
    assert selected.runtime == RUNTIME_LLAMA_DEV and selected.llama_max_tokens == 64
    assert selected.llama_launch_record == Path("/x/launch.json")


# -- explicit configuration is required and fenced ----------------------------------------------


def test_a_complete_dev_configuration_is_accepted(tmp_path: Path) -> None:
    validate_runtime_settings(dev(tmp_path))


@pytest.mark.parametrize(
    "change",
    [
        {"runtime": "openai"},
        {"llama_launch_record": None},
        {"llama_launch_record": Path("relative/launch.json")},
        {"llama_max_tokens": 0},
        {"llama_max_tokens": 5000},
        {"llama_max_input_chars": 0},
        {"llama_max_input_chars": 100_000},
    ],
)
def test_incomplete_or_out_of_range_dev_settings_are_refused(
    tmp_path: Path, change: dict[str, object]
) -> None:
    with pytest.raises(RuntimeConfigurationError):
        validate_runtime_settings(dev(tmp_path, **change))


def test_a_stray_launch_record_with_the_fake_runtime_is_refused(tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "x.sqlite3", llama_launch_record=Path("/x/launch.json"))
    with pytest.raises(RuntimeConfigurationError):
        validate_runtime_settings(settings)


@pytest.mark.parametrize(
    "name",
    ["chat.sqlite3", "chat-dev.db", "chat-dev.sqlite3.bak", DEV_DATASET_SUFFIX, "dev.sqlite3"],
)
def test_only_a_dev_named_dataset_is_acceptable(tmp_path: Path, name: str) -> None:
    with pytest.raises(RuntimeConfigurationError):
        require_dev_dataset(tmp_path / name)


def test_symlinks_and_parent_references_in_the_dataset_path_are_refused(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    (real / "chat-dev.sqlite3").write_bytes(b"")
    (tmp_path / "file-link-dev.sqlite3").symlink_to(real / "chat-dev.sqlite3")
    (tmp_path / "dir-link").symlink_to(real)
    for bad in (
        tmp_path / "file-link-dev.sqlite3",
        tmp_path / "dir-link" / "chat-dev.sqlite3",
        real / ".." / "real" / "chat-dev.sqlite3",
    ):
        with pytest.raises(RuntimeConfigurationError):
            require_dev_dataset(bad)
    require_dev_dataset(real / "chat-dev.sqlite3")  # the canonical path is fine


def test_a_misconfigured_real_runtime_fails_before_anything_is_created(tmp_path: Path) -> None:
    target = tmp_path / "newdir" / "chat.sqlite3"  # not a dev dataset
    with pytest.raises(RuntimeConfigurationError):
        build_application(dev(tmp_path, db_path=target), execution_settings=FAST)
    assert not target.parent.exists()


def launched(tmp_path: Path) -> Settings:
    """Settings for the real adapter with a genuine (synthetic) launch record and key file."""
    server = FakeLlamaServer().start()
    try:
        record_path, _, _ = write_launch(tmp_path / "launch", server)
    finally:
        server.stop()
    return dev(tmp_path, llama_launch_record=record_path)


def test_a_missing_launch_record_refuses_startup_before_any_database_side_effect(
    tmp_path: Path,
) -> None:
    fresh = tmp_path / "newdir" / "chat-dev.sqlite3"
    settings = dev(tmp_path, db_path=fresh)  # the record does not exist
    with pytest.raises(RuntimeConfigurationError, match="launch record"):
        build_application(settings, execution_settings=FAST)
    assert not fresh.parent.exists()  # not even the data directory was created
    assert not any(tmp_path.glob("*.sqlite3*"))


def _no_key_file(settings: Settings) -> None:
    record = settings.llama_launch_record
    assert record is not None
    for key in record.parent.glob("key-*"):
        key.unlink()


def _public_key(settings: Settings) -> None:
    record = settings.llama_launch_record
    assert record is not None
    for key in record.parent.glob("key-*"):
        key.chmod(0o644)


def _public_record(settings: Settings) -> None:
    assert settings.llama_launch_record is not None
    settings.llama_launch_record.chmod(0o644)


def _malformed_record(settings: Settings) -> None:
    assert settings.llama_launch_record is not None
    settings.llama_launch_record.write_text("{not json")


def _non_loopback_record(settings: Settings) -> None:
    record = settings.llama_launch_record
    assert record is not None
    raw = json.loads(record.read_text())
    raw["host"] = "192.0.2.1"
    record.write_text(json.dumps(raw))


@pytest.mark.parametrize(
    "break_it",
    [_no_key_file, _public_key, _public_record, _malformed_record, _non_loopback_record],
)
def test_invalid_launch_metadata_refuses_startup_before_the_dataset_is_created(
    tmp_path: Path, break_it: Callable[[Settings], None]
) -> None:
    settings = launched(tmp_path)
    break_it(settings)
    with pytest.raises(RuntimeConfigurationError):
        build_application(settings, execution_settings=FAST)
    assert not settings.db_path.exists()
    assert not any(tmp_path.glob("*.sqlite3*"))


def test_a_valid_launch_record_starts_the_real_adapter_and_never_the_fake_model(
    tmp_path: Path,
) -> None:
    settings = launched(tmp_path)
    app = build_application(settings, execution_settings=FAST)  # the recorded process is not live
    try:
        cid = app.conversations.create_conversation(app.owner).id
        outcome = app.conversations.send_message(app.owner, cid, new_uuid(), "hello")
        assert outcome.assistant_message is None  # nothing fake was substituted
        assert outcome.run.status is RunStatus.FAILED
        assert outcome.run.failure_code == "binding_unavailable"  # per-attempt liveness check
        assert outcome.run.termination_basis is EvidenceBasis.NEVER_DISPATCHED
    finally:
        assert app.shutdown()


def test_the_entry_point_refuses_a_bad_real_runtime_configuration_before_starting(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = entry.main(["--runtime", "llama-dev", "--db-path", str(tmp_path / "chat.sqlite3")])
    assert code == 2
    assert "Refusing to start" in capsys.readouterr().err
    assert not os.path.exists(tmp_path / "chat.sqlite3")


def test_the_entry_point_refuses_a_missing_launch_record_before_any_side_effect(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "fresh" / "chat-dev.sqlite3"
    code = entry.main(
        [
            "--runtime",
            "llama-dev",
            "--db-path",
            str(db),
            "--llama-launch-record",
            str(tmp_path / "absent" / "launch.json"),
        ]
    )
    assert code == 2
    err = capsys.readouterr().err
    assert "Refusing to start" in err and str(tmp_path) not in err
    assert not db.parent.exists()
