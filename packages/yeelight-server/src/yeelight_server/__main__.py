"""CLI entry point: ``python -m yeelight_server`` or ``yeelight-server``."""

from __future__ import annotations

import argparse
import getpass
import logging
import sys
from dataclasses import replace

import uvicorn

from . import __version__
from .api.auth import set_password
from .app import create_app
from .config import Settings
from .storage import Database


def _set_password(settings: Settings, username: str | None) -> int:
    db = Database(settings.db_path)
    try:
        if db.count_users() == 0:
            print(
                "The database has no users yet. Start the server once with "
                "YEELIGHT_SERVER_ADMIN_PASSWORD set, or use tools/setup.bat.",
                file=sys.stderr,
            )
            return 2
        username = username or settings.admin_username
        password = getpass.getpass("New password: ")
        confirmation = getpass.getpass("Repeat password: ")
        if password != confirmation:
            print("Passwords do not match.", file=sys.stderr)
            return 2
        try:
            changed = set_password(db, username, password)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        if not changed:
            print(f"User {username!r} was not found.", file=sys.stderr)
            return 2
        db.audit(
            actor_type="system",
            actor_id=None,
            action="password_changed",
            target=username,
            outcome="success",
        )
        print("Password updated.")
        return 0
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="yeelight-server",
        description="Authenticated Yeelight relay and web interface.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--host", help="Listen address (default from env)")
    parser.add_argument("--port", type=int, help="Listen port (default from env)")
    parser.add_argument(
        "--set-password",
        action="store_true",
        help="Prompt for a new password for an existing user and exit",
    )
    parser.add_argument(
        "--username",
        help="Username used together with --set-password",
    )
    parser.add_argument(
        "--log-level",
        default="info",
        choices=["critical", "error", "warning", "info", "debug"],
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    settings = Settings.from_env()
    if args.host:
        settings = replace(settings, host=args.host)
    if args.port:
        settings = replace(settings, port=args.port)

    if args.set_password:
        return _set_password(settings, args.username)

    app = create_app(settings)
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level=args.log_level,
        server_header=False,
        proxy_headers=False,
        ws_max_size=1024 * 1024,
        ws_ping_interval=settings.heartbeat_interval_seconds,
        ws_ping_timeout=settings.heartbeat_interval_seconds,
        ssl_certfile=settings.tls_cert,
        ssl_keyfile=settings.tls_key,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
