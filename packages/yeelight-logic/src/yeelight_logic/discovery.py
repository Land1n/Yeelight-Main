"""SSDP discovery wrapper."""

from __future__ import annotations

from typing import Any

from .exceptions import DiscoveryError


def discover_bulbs(
    timeout: float = 2.0, interface: str | None = None
) -> list[dict[str, Any]]:
    """Find Yeelight lamps in the local network through SSDP."""

    try:
        from yeelight import discover_bulbs as _discover

        return _discover(timeout=timeout, interface=interface)
    except Exception as exc:
        raise DiscoveryError(f"Yeelight discovery failed: {exc}") from exc
