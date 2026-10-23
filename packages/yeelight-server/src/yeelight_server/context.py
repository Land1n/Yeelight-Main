"""Runtime object graph shared by API routers."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .config import Settings
from .security.rate_limit import SlidingWindowLimiter
from .services.commands import CommandService
from .services.hub import ManagerHub
from .services.modes import ModeService
from .storage import Database


@dataclass
class AppContext:
    settings: Settings
    db: Database
    hub: ManagerHub
    commands: CommandService
    modes: ModeService
    started_at: float = field(default_factory=time.time)
    login_limiter: SlidingWindowLimiter = field(default_factory=SlidingWindowLimiter)
    pairing_limiter: SlidingWindowLimiter = field(default_factory=SlidingWindowLimiter)
    command_limiter: SlidingWindowLimiter = field(default_factory=SlidingWindowLimiter)

    @classmethod
    def create(cls, settings: Settings) -> "AppContext":
        db = Database(settings.db_path)
        hub = ManagerHub()
        commands = CommandService(
            db,
            hub,
            default_timeout=settings.command_timeout_seconds,
            max_wait=settings.max_command_wait_seconds,
        )
        modes = ModeService(db, commands)
        return cls(
            settings=settings,
            db=db,
            hub=hub,
            commands=commands,
            modes=modes,
        )


__all__ = ["AppContext"]
