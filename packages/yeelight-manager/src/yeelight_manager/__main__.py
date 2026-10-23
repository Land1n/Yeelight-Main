"""CLI entry point: ``python -m yeelight_manager`` or ``yeelight-manager``."""

from __future__ import annotations

import argparse
import getpass
import json
import logging
import sys
from dataclasses import replace

from . import __version__
from .pairing import PairingError
from .runtime import ManagerRuntime
from .secrets import SecretError
from .service import ManagerService
from .settings import ManagerSettings


def _print_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _build_service(settings: ManagerSettings) -> ManagerService:
    return ManagerService(settings)


def _run_pair(settings: ManagerSettings, code: str | None, name: str | None) -> int:
    if not code:
        if not sys.stdin.isatty():
            print("--pair requires a pairing code.", file=sys.stderr)
            return 2
        code = getpass.getpass("Pairing code: ").strip()
    service = _build_service(settings)
    try:
        outcome = service.pair(code, name=name)
    except PairingError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        service.stop()
    print(
        f"Paired as {outcome.manager_name!r} "
        f"(manager id: {outcome.manager_id or 'unknown'})."
    )
    return 0


def _run_unpair(settings: ManagerSettings) -> int:
    service = _build_service(settings)
    try:
        existed = service.unpair()
    finally:
        service.stop()
    print("Manager token removed." if existed else "No stored manager token.")
    return 0


def _run_status(settings: ManagerSettings) -> int:
    service = _build_service(settings)
    try:
        _print_json(service.snapshot())
    finally:
        service.stop()
    return 0


def _run_discover(settings: ManagerSettings) -> int:
    runtime = ManagerRuntime(settings)
    try:
        result = runtime.discover()
        _print_json(result.to_dict())
        return 0 if result.ok else 1
    finally:
        runtime.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="yeelight-manager",
        description="Local Yeelight agent: relays typed commands from the server.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument(
        "--pair",
        metavar="CODE",
        nargs="?",
        const="",
        help="Pair with the server using a one-time code and exit",
    )
    parser.add_argument(
        "--name",
        help="Manager name used with --pair (default from YEELIGHT_MANAGER_NAME)",
    )
    parser.add_argument(
        "--unpair",
        action="store_true",
        help="Remove the stored manager token and exit",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print the manager status as JSON and exit",
    )
    parser.add_argument(
        "--discover",
        action="store_true",
        help="Discover lamps on the local network and print the result",
    )
    parser.add_argument(
        "--no-ui",
        action="store_true",
        help="Run without the desktop window (headless relay)",
    )
    parser.add_argument(
        "--no-local-api",
        action="store_true",
        help="Do not start the loopback HTTP API",
    )
    parser.add_argument(
        "--log-level",
        default=None,
        choices=["critical", "error", "warning", "info", "debug"],
        help="Logging verbosity (default from YEELIGHT_MANAGER_LOG_LEVEL)",
    )
    parser.add_argument(
        "--server",
        help="Relay server URL, for example http://192.168.1.10:8000",
    )
    args = parser.parse_args(argv)

    try:
        settings = ManagerSettings.from_env()
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    if args.server:
        from .settings import normalize_server_url

        settings = replace(settings, server_url=normalize_server_url(args.server))
    if args.no_ui:
        settings = replace(settings, ui_enabled=False)
    if args.no_local_api:
        settings = replace(settings, local_api_enabled=False)

    logging.basicConfig(
        level=getattr(
            logging,
            (args.log_level or settings.log_level or "INFO").upper(),
            logging.INFO,
        ),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        if args.pair is not None:
            return _run_pair(settings, args.pair, args.name)
        if args.unpair:
            return _run_unpair(settings)
        if args.status:
            return _run_status(settings)
        if args.discover:
            return _run_discover(settings)
        return ManagerService(settings).run()
    except SecretError as exc:
        print(f"Secure storage error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
