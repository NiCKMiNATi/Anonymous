"""Development entry point: ``uv run anonymous-server`` (or ``python -m anonymous``).

Binds to loopback only. Non-loopback hosts are refused outright: until the approved security
system (device/session authority, protected transport) exists, this API must not be reachable
from a LAN or the public Internet.
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import replace
from pathlib import Path

import uvicorn

from anonymous.api.app import create_app
from anonymous.config import LOOPBACK_HOSTS, Settings

_DEFAULT_CLIENT_DIST = Path(__file__).resolve().parents[3] / "client" / "dist"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="anonymous-server",
        description="Anonymous slice 0A dev server (loopback only, NO authentication).",
    )
    parser.add_argument("--host", help="loopback address only (default 127.0.0.1)")
    parser.add_argument("--port", type=int)
    parser.add_argument("--db-path", type=Path, help="SQLite development database file")
    parser.add_argument("--client-dist", type=Path, help="built client directory to serve at /")
    parser.add_argument("--fake-delay-seconds", type=float, help="simulated fake-model latency")
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    overrides = {
        "host": args.host,
        "port": args.port,
        "db_path": args.db_path,
        "client_dist": args.client_dist,
        "fake_delay_seconds": args.fake_delay_seconds,
    }
    settings = replace(settings, **{k: v for k, v in overrides.items() if v is not None})
    if settings.client_dist is None and (_DEFAULT_CLIENT_DIST / "index.html").is_file():
        settings = replace(settings, client_dist=_DEFAULT_CLIENT_DIST)

    if settings.host not in LOOPBACK_HOSTS:
        print(
            f"Refusing to bind to {settings.host!r}: slice 0A has no authentication and may only"
            " listen on loopback (127.0.0.1, ::1, localhost).",
            file=sys.stderr,
        )
        return 2

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    log = logging.getLogger("anonymous")
    log.warning("DEVELOPMENT BUILD: no authentication; loopback only; use synthetic data only")
    log.info("database: %s", settings.db_path)
    log.info(
        "client: %s",
        settings.client_dist if settings.client_dist else "not built (use the Vite dev server)",
    )

    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_level="info",
        access_log=False,  # request paths contain private object ids; keep them out of logs
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
