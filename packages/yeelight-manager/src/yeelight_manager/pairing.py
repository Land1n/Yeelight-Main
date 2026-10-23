"""Pairing with the relay server.

Pairing exchanges a short one-time code (created in the web interface) for a
long-lived manager token.  The token is stored with
:mod:`yeelight_manager.secrets` and is never written to logs, the state file or
command output.  The server only ever sees the SHA-256 hash of the token.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from . import __version__
from .secrets import clear_token, save_token, token_fingerprint
from .settings import ManagerSettings, normalize_server_url

logger = logging.getLogger(__name__)

PAIR_TIMEOUT_SECONDS = 15.0
PAIR_PATH = "/api/v1/managers/pair"


class PairingError(RuntimeError):
    """Pairing could not be completed.

    ``status_code`` mirrors the HTTP status returned by the server, or ``0``
    when the server could not be reached at all.
    """

    def __init__(self, message: str, *, status_code: int = 0) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class PairingOutcome:
    """Result of a successful pairing exchange (never contains the token)."""

    token: str
    manager_id: str
    manager_name: str
    heartbeat_interval_seconds: float

    def describe(self) -> dict[str, Any]:
        return {
            "manager_id": self.manager_id,
            "manager_name": self.manager_name,
            "heartbeat_interval_seconds": self.heartbeat_interval_seconds,
        }


def pair_url(server_url: str) -> str:
    """Return the pairing endpoint for ``server_url``."""

    return f"{normalize_server_url(server_url)}{PAIR_PATH}"


def _server_detail(response: httpx.Response) -> str | None:
    try:
        payload = response.json()
    except ValueError:
        return None
    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()[:300]
    return None


def pair_with_server(
    settings: ManagerSettings,
    code: str,
    *,
    name: str | None = None,
    client: httpx.Client | None = None,
) -> PairingOutcome:
    """Exchange ``code`` for a manager token.

    The request body contains the manager name and the one-time code only; the
    returned token is validated before it is used or stored.
    """

    code = (code or "").strip()
    if not code:
        raise PairingError("Enter the pairing code shown on the server page.")
    manager_name = (name or settings.manager_name).strip() or "Yeelight Manager"

    url = pair_url(settings.server_url)
    payload = {"name": manager_name, "code": code, "version": __version__}
    try:
        if client is not None:
            response = client.post(url, json=payload)
        else:
            with httpx.Client(
                timeout=PAIR_TIMEOUT_SECONDS, verify=settings.verify_tls
            ) as owned:
                response = owned.post(url, json=payload)
    except httpx.HTTPError as exc:
        raise PairingError(
            f"Could not reach the server at {normalize_server_url(settings.server_url)}: "
            f"{exc.__class__.__name__}",
            status_code=0,
        ) from exc

    if response.status_code == 401:
        raise PairingError(
            "The pairing code is invalid or has expired.", status_code=401
        )
    if response.status_code == 409:
        raise PairingError(
            _server_detail(response)
            or "A manager with this name is already paired.",
            status_code=409,
        )
    if response.status_code == 422:
        raise PairingError(
            _server_detail(response) or "The server rejected the pairing request.",
            status_code=422,
        )
    if response.status_code >= 400:
        raise PairingError(
            _server_detail(response)
            or f"Server rejected pairing (HTTP {response.status_code}).",
            status_code=response.status_code,
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise PairingError(
            "The server returned an invalid pairing response.", status_code=502
        ) from exc
    if not isinstance(data, dict):
        raise PairingError(
            "The server returned an invalid pairing response.", status_code=502
        )

    token = data.get("token")
    if not isinstance(token, str) or not token.startswith("ylm_"):
        raise PairingError(
            "The server did not return a usable manager token.", status_code=502
        )
    manager = data.get("manager")
    manager = manager if isinstance(manager, dict) else {}
    try:
        heartbeat = float(data.get("heartbeat_interval_seconds") or 20.0)
    except (TypeError, ValueError):
        heartbeat = 20.0

    logger.info(
        "Paired as %r (token %s)",
        manager.get("name") or manager_name,
        token_fingerprint(token),
    )
    return PairingOutcome(
        token=token,
        manager_id=str(manager.get("id") or ""),
        manager_name=str(manager.get("name") or manager_name),
        heartbeat_interval_seconds=max(5.0, min(heartbeat, 120.0)),
    )


def pair_and_store(
    settings: ManagerSettings,
    code: str,
    *,
    name: str | None = None,
    client: httpx.Client | None = None,
) -> PairingOutcome:
    """Pair and persist the token in the protected token file."""

    outcome = pair_with_server(settings, code, name=name, client=client)
    save_token(settings.token_file, outcome.token)
    return outcome


def unpair(settings: ManagerSettings) -> bool:
    """Remove the stored manager token.  Returns ``True`` when one existed."""

    existed = settings.token_file.is_file()
    clear_token(settings.token_file)
    return existed


__all__ = [
    "PAIR_TIMEOUT_SECONDS",
    "PairingError",
    "PairingOutcome",
    "pair_and_store",
    "pair_url",
    "pair_with_server",
    "unpair",
]
