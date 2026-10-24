"""Runtime configuration from environment variables. Development defaults only."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
DEFAULT_PORT = 8000
DEFAULT_DEV_CLIENT_ORIGINS = (
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://[::1]:5173",
)
# URL authority forms of the loopback names above. An IPv6 literal is bracketed in a Host header
# and in an Origin (RFC 3986/6454), unlike the bare ``::1`` accepted by the CLI.
_LOOPBACK_AUTHORITIES = ("127.0.0.1", "localhost", "[::1]")


RUNTIME_FAKE = "fake"
RUNTIME_LLAMA_DEV = "llama-dev"  # ADR-0015: dev-only external llama.cpp runtime, explicit opt-in
DEV_DATASET_SUFFIX = "-dev.sqlite3"
DEFAULT_LLAMA_MAX_TOKENS = 384
DEFAULT_LLAMA_MAX_INPUT_CHARS = 1400  # conservative for a 2048-token context (see ADR-0015)
MAX_LLAMA_MAX_TOKENS = 1024
MAX_LLAMA_MAX_INPUT_CHARS = 4000
# The launcher fixes ``-c 2048 -np 1`` (the E2-B/E3 profile); a test keeps the two equal.
PINNED_CONTEXT_TOKENS = 2048
# Allowance for chat-template tokens (about 5 per message plus the generation prompt). An
# engineering allowance covering dozens of messages, not a measurement.
TEMPLATE_RESERVE_TOKENS = 256


def llama_budget_fits(max_tokens: int, max_input_chars: int) -> bool:
    """Whether the input cap and the output cap can share the pinned context window.

    The input cap counts characters, so this treats one character as at most one token. That
    holds for single-byte text and is not a worst case for other scripts (a token never covers
    less than one byte), so passing it does not prove that a prompt fits; it only refuses
    combinations that cannot fit even under that assumption. Anything beyond the window ends in
    an HTTP error or a ``length`` finish, and both quarantine the dataset (ADR-0015)."""
    return max_input_chars + max_tokens + TEMPLATE_RESERVE_TOKENS <= PINNED_CONTEXT_TOKENS


class RuntimeConfigurationError(Exception):
    """The runtime selection is inconsistent or unsafe. The message is fixed text, no values."""


def require_dev_dataset(db_path: Path) -> None:
    """The real-model adapter may only run on a dedicated, canonical development dataset.

    The path must already be absolute-canonical as given (no ``..``, no symlink anywhere in it) and
    name a ``*-dev.sqlite3`` file. This guards against accidents; it cannot know what the dataset
    contains. Synthetic development data only.
    """
    raw = Path(db_path).expanduser()
    if ".." in raw.parts:
        raise RuntimeConfigurationError("the dev dataset path must not contain '..'")
    absolute = Path(os.path.abspath(raw))
    name = absolute.name
    if not name.endswith(DEV_DATASET_SUFFIX) or name == DEV_DATASET_SUFFIX:
        raise RuntimeConfigurationError(
            f"the external runtime needs a dedicated dev dataset named '*{DEV_DATASET_SUFFIX}'"
        )
    for candidate in (absolute, *absolute.parents):
        if candidate.is_symlink():
            raise RuntimeConfigurationError("the dev dataset path must not contain a symlink")
    if Path(os.path.realpath(absolute)) != absolute:
        raise RuntimeConfigurationError("the dev dataset path must be canonical")


def validate_runtime_settings(settings: Settings) -> None:
    """Fail closed before anything is opened. The fake model is the default and needs nothing."""
    if settings.runtime == RUNTIME_FAKE:
        if settings.llama_launch_record is not None:
            raise RuntimeConfigurationError(
                "a llama launch record is set but the runtime is not 'llama-dev'"
            )
        return
    if settings.runtime != RUNTIME_LLAMA_DEV:
        raise RuntimeConfigurationError("unknown runtime selection")
    record = settings.llama_launch_record
    if record is None or not Path(record).expanduser().is_absolute():
        raise RuntimeConfigurationError("'llama-dev' needs an absolute launch record path")
    if not 1 <= settings.llama_max_tokens <= MAX_LLAMA_MAX_TOKENS:
        raise RuntimeConfigurationError("llama max tokens is out of range")
    if not 1 <= settings.llama_max_input_chars <= MAX_LLAMA_MAX_INPUT_CHARS:
        raise RuntimeConfigurationError("llama max input characters is out of range")
    if not llama_budget_fits(settings.llama_max_tokens, settings.llama_max_input_chars):
        raise RuntimeConfigurationError(
            "llama max input characters and max tokens do not fit the context window"
        )
    require_dev_dataset(settings.db_path)


@dataclass(frozen=True, slots=True)
class Settings:
    db_path: Path = Path(".anonymous-data/anonymous-0b1-dev.sqlite3")
    host: str = "127.0.0.1"
    port: int = DEFAULT_PORT
    client_dist: Path | None = None
    fake_delay_seconds: float = 0.0
    runtime: str = RUNTIME_FAKE
    llama_launch_record: Path | None = None
    llama_max_tokens: int = DEFAULT_LLAMA_MAX_TOKENS
    llama_max_input_chars: int = DEFAULT_LLAMA_MAX_INPUT_CHARS
    extra_allowed_origins: tuple[str, ...] = field(
        default_factory=lambda: DEFAULT_DEV_CLIENT_ORIGINS
    )

    @classmethod
    def from_env(cls) -> Settings:
        defaults = cls()
        dist = os.environ.get("ANONYMOUS_CLIENT_DIST")
        return cls(
            db_path=Path(os.environ.get("ANONYMOUS_DB_PATH", str(defaults.db_path))),
            host=os.environ.get("ANONYMOUS_HOST", defaults.host),
            port=int(os.environ.get("ANONYMOUS_PORT", defaults.port)),
            client_dist=Path(dist) if dist else None,
            fake_delay_seconds=float(os.environ.get("ANONYMOUS_FAKE_DELAY_SECONDS", "0")),
            runtime=os.environ.get("ANONYMOUS_RUNTIME", defaults.runtime),
            llama_launch_record=(
                Path(record)
                if (record := os.environ.get("ANONYMOUS_LLAMA_LAUNCH_RECORD"))
                else None
            ),
            llama_max_tokens=int(
                os.environ.get("ANONYMOUS_LLAMA_MAX_TOKENS", defaults.llama_max_tokens)
            ),
            llama_max_input_chars=int(
                os.environ.get("ANONYMOUS_LLAMA_MAX_INPUT_CHARS", defaults.llama_max_input_chars)
            ),
        )

    def allowed_hosts(self) -> tuple[str, ...]:
        """Host header values (without port) accepted. Loopback names only (DNS-rebinding guard)."""
        return _LOOPBACK_AUTHORITIES

    def allowed_origins(self) -> frozenset[str]:
        """Exact origins accepted: this server's own loopback origins plus the dev client origins.

        Same-origin forms mirror ``allowed_hosts`` (including bracketed IPv6) on the configured
        port, so a page served from any supported loopback address can make its own requests.
        Nothing is matched by wildcard or prefix.
        """
        same_origin = {f"http://{authority}:{self.port}" for authority in _LOOPBACK_AUTHORITIES}
        return frozenset(same_origin | set(self.extra_allowed_origins))
