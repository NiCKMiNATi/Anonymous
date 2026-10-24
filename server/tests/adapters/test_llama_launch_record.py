"""The launch record and key file: only private, owned, well-formed files are believed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from anonymous.adapters.model.llama_launch_record import (
    ArtifactIdentity,
    LaunchRecord,
    LaunchRecordError,
    read_key,
    read_record,
    write_record,
)
from tests.adapters.llama_fakes import KEY, NONCE


def make(tmp_path: Path) -> tuple[Path, LaunchRecord]:
    directory = tmp_path / "launch"
    directory.mkdir(mode=0o700)
    key_file = directory / "key"
    key_file.write_text(KEY)
    key_file.chmod(0o600)
    record = LaunchRecord(
        nonce=NONCE,
        pid=4242,
        start=(1, 2),
        host="127.0.0.1",
        port=18080,
        key_file=key_file,
        model=ArtifactIdentity("Qwen3-4B-Q4_K_M", "a" * 64, "verified"),
        runtime=ArtifactIdentity("llama.cpp-b11440", None, "unspecified"),
        created_utc=1.0,
    )
    path = directory / "launch.json"
    write_record(path, record)
    return path, record


def rewrite(path: Path, **changes: object) -> None:
    raw = json.loads(path.read_text())
    raw.update(changes)
    path.write_text(json.dumps(raw))


def code_of(path: Path) -> str:
    with pytest.raises(LaunchRecordError) as caught:
        read_record(path)
    return caught.value.code


def test_a_written_record_round_trips_and_is_private(tmp_path: Path) -> None:
    path, record = make(tmp_path)
    assert read_record(path) == record
    assert record.instance_ref == f"llama-{NONCE}"
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert read_key(record) == KEY


@pytest.mark.parametrize("mode", [0o644, 0o640, 0o604, 0o660])
def test_a_record_readable_by_others_is_refused(tmp_path: Path, mode: int) -> None:
    path, _ = make(tmp_path)
    path.chmod(mode)
    assert code_of(path) == "record_not_private"


def test_a_symlinked_record_is_refused(tmp_path: Path) -> None:
    path, _ = make(tmp_path)
    link = tmp_path / "link.json"
    link.symlink_to(path)
    assert code_of(link) == "record_not_regular"


def test_a_missing_or_malformed_record_is_refused(tmp_path: Path) -> None:
    assert code_of(tmp_path / "absent.json") == "record_missing"
    path, _ = make(tmp_path)
    path.write_text("{not json")
    assert code_of(path) == "record_malformed"
    path.write_text("[]")
    assert code_of(path) == "record_version"


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"v": 2}, "record_version"),
        ({"host": "0.0.0.0"}, "record_host_not_loopback"),
        ({"host": "localhost"}, "record_host_not_loopback"),
        ({"host": "192.0.2.1"}, "record_host_not_loopback"),
        ({"port": 80}, "record_port_invalid"),
        ({"port": True}, "record_port_invalid"),
        ({"port": 70000}, "record_port_invalid"),
        ({"pid": 1}, "record_pid_invalid"),
        ({"pid": "12"}, "record_pid_invalid"),
        ({"start": [1]}, "record_start_invalid"),
        ({"nonce": "xyz"}, "record_nonce_invalid"),
        ({"key_file": "relative/key"}, "record_key_file_invalid"),
        (
            {"model": {"label": "/etc/passwd", "sha256": None, "verification": "unspecified"}},
            "record_label_invalid",
        ),
        (
            {"model": {"label": "ok", "sha256": "zz", "verification": "asserted"}},
            "record_digest_invalid",
        ),
        (
            {"model": {"label": "ok", "sha256": None, "verification": "verified"}},
            "record_verification_invalid",
        ),
        (
            {"model": {"label": "ok", "sha256": "a" * 64, "verification": "unspecified"}},
            "record_digest_invalid",
        ),
        (
            {"model": {"label": "ok", "sha256": "a" * 64, "verification": "guessed"}},
            "record_verification_invalid",
        ),
    ],
)
def test_invalid_fields_are_refused_with_a_fixed_code(
    tmp_path: Path, change: dict[str, object], code: str
) -> None:
    path, _ = make(tmp_path)
    rewrite(path, **change)
    assert code_of(path) == code


def test_the_error_never_carries_a_value(tmp_path: Path) -> None:
    path, _ = make(tmp_path)
    rewrite(path, host="203.0.113.77")
    with pytest.raises(LaunchRecordError) as caught:
        read_record(path)
    assert "203.0.113.77" not in str(caught.value) and str(path) not in str(caught.value)


def test_an_oversized_record_is_refused(tmp_path: Path) -> None:
    path, _ = make(tmp_path)
    path.write_text(" " * 20_000)
    assert code_of(path) == "record_too_large"


@pytest.mark.parametrize("mode", [0o644, 0o640])
def test_a_key_file_readable_by_others_is_refused(tmp_path: Path, mode: int) -> None:
    path, record = make(tmp_path)
    record.key_file.chmod(mode)
    with pytest.raises(LaunchRecordError) as caught:
        read_key(read_record(path))
    assert caught.value.code == "key_not_private"


def test_a_short_or_blank_key_is_refused(tmp_path: Path) -> None:
    _, record = make(tmp_path)
    for content in ("short", "   \n", "has space inside the key value 0123456789"):
        record.key_file.write_text(content)
        with pytest.raises(LaunchRecordError) as caught:
            read_key(record)
        assert caught.value.code == "key_malformed"


def test_a_symlinked_key_file_is_refused(tmp_path: Path) -> None:
    path, record = make(tmp_path)
    real = record.key_file.with_name("real-key")
    record.key_file.rename(real)
    record.key_file.symlink_to(real)
    with pytest.raises(LaunchRecordError) as caught:
        read_key(read_record(path))
    assert caught.value.code == "key_not_regular"
