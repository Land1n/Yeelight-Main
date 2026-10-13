from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import math
import re
import secrets
import shlex
import time
from contextlib import asynccontextmanager
from importlib.resources import files
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from yeelight_logic import CommandError, DeviceError, StorageError, YeelightController


logger = logging.getLogger(__name__)


class CommandRequest(BaseModel):
    command: str = Field(min_length=1, max_length=500)


class ModeRequest(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    steps: list[dict[str, Any]] = Field(min_length=1, max_length=50)
    delay_seconds: float = Field(default=1.0, ge=0.1, le=3600)


class ModeStartRequest(BaseModel):
    ip: str


def create_app(
    controller: YeelightController | None = None,
    api_token: str | None = None,
    poll_interval: float = 10.0,
    offline_timeout: float = 60.0,
    modes_path: str | Path | None = None,
) -> FastAPI:
    if not all(
        math.isfinite(value) and value > 0
        for value in (poll_interval, offline_timeout)
    ):
        raise ValueError("Polling interval and offline timeout must be positive")

    service = controller or YeelightController()
    last_seen: dict[str, float] = {}
    failed_since: dict[str, float] = {}
    bulb_status: dict[str, bool | None] = {}
    mode_file = Path(modes_path) if modes_path is not None else None
    modes: dict[str, dict[str, Any]] = {}
    mode_tasks: dict[str, asyncio.Task[None]] = {}

    if mode_file is not None and mode_file.is_file():
        try:
            loaded = json.loads(mode_file.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                raise ValueError("Modes file must contain a JSON object")
            for name, mode in loaded.items():
                if (
                    not isinstance(name, str)
                    or not isinstance(mode, dict)
                    or (
                        not isinstance(mode.get("steps"), list)
                        and not isinstance(mode.get("commands"), list)
                    )
                ):
                    raise ValueError("Modes file contains an invalid mode")
                steps = mode.get("steps")
                if steps is None:
                    steps = []
                    for command in mode["commands"]:
                        parts = shlex.split(command)
                        if len(parts) < 2:
                            raise ValueError("Legacy mode contains an invalid command")
                        action = parts[0]
                        args = parts[2:]
                        if action == "color" and len(args) == 1 and re.fullmatch(r"#?[0-9a-fA-F]{6}", args[0]):
                            rgb = int(args[0].lstrip("#"), 16)
                            args = [(rgb >> 16) & 255, (rgb >> 8) & 255, rgb & 255]
                        elif action == "color" and len(args) == 3:
                            args = [int(value) for value in args]
                        elif args:
                            args = [int(args[0]) if args[0].isdigit() else args[0]]
                        steps.append({"action": action, "values": args})
                for step in steps:
                    if (
                        not isinstance(step, dict)
                        or step.get("action") not in {
                            "on", "off", "toggle", "status",
                            "brightness", "color", "temp",
                        }
                        or not isinstance(step.get("values"), list)
                    ):
                        raise ValueError(f"Mode {name!r} contains an invalid task")
                modes[name] = {
                    "name": name,
                    "steps": steps,
                    "delay_seconds": float(mode.get("delay_seconds", 1.0)),
                    "last_error": None,
                    "running_ip": None,
                }
        except (OSError, ValueError, TypeError, KeyError, IndexError) as exc:
            raise RuntimeError(f"Could not load modes from {mode_file}: {exc}") from exc

    def save_modes() -> None:
        if mode_file is None:
            return
        mode_file.parent.mkdir(parents=True, exist_ok=True)
        content = {
            name: {
                "steps": mode["steps"],
                "delay_seconds": mode["delay_seconds"],
            }
            for name, mode in modes.items()
        }
        mode_file.write_text(
            json.dumps(content, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        monitor_task = asyncio.create_task(monitor_bulbs())
        try:
            yield
        finally:
            tasks = [*mode_tasks.values(), monitor_task]
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

    app = FastAPI(title="Yeelight Network", version="0.1.0", lifespan=lifespan)
    static_dir = Path(str(files("yeelight_app").joinpath("static")))
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    async def authorize(x_api_token: str | None = Header(default=None)) -> None:
        if api_token and (
            x_api_token is None or not secrets.compare_digest(x_api_token, api_token)
        ):
            raise HTTPException(status_code=401, detail="A valid X-API-Token is required")

    async def monitor_bulbs() -> None:
        while True:
            checked_at = time.monotonic()
            for item in service.known_bulbs():
                address = item["ip"]
                try:
                    await run_in_threadpool(service.execute, f"status {address}")
                    last_seen[address] = time.time()
                    failed_since.pop(address, None)
                    bulb_status[address] = True
                except (CommandError, DeviceError):
                    if address not in {
                        item["ip"] for item in service.known_bulbs()
                    }:
                        failed_since.pop(address, None)
                        last_seen.pop(address, None)
                        bulb_status.pop(address, None)
                        continue
                    bulb_status[address] = False
                    unavailable_at = failed_since.setdefault(address, checked_at)
                    if checked_at - unavailable_at >= offline_timeout:
                        try:
                            service.remove(address)
                        except CommandError:
                            logger.info(
                                "Lamp %s was removed while its status was being checked",
                                address,
                            )
                        except StorageError:
                            logger.exception(
                                "Could not persist removal of unavailable lamp %s",
                                address,
                            )
                            continue
                        failed_since.pop(address, None)
                        last_seen.pop(address, None)
                        bulb_status.pop(address, None)
            await asyncio.sleep(poll_interval)

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", include_in_schema=False)
    async def web_client() -> FileResponse:
        index = static_dir / "index.html"
        if not index.is_file():
            raise HTTPException(status_code=500, detail="Web client files are missing")
        return FileResponse(index, media_type="text/html")

    @app.get("/api/bulbs", dependencies=[Depends(authorize)])
    async def bulbs() -> dict[str, Any]:
        return {
            "bulbs": [
                {
                    **bulb,
                    "online": bulb_status.get(bulb["ip"]),
                    "last_seen": last_seen.get(bulb["ip"]),
                }
                for bulb in service.known_bulbs()
            ]
        }

    @app.get("/api/settings", dependencies=[Depends(authorize)])
    async def settings() -> dict[str, float]:
        return {
            "poll_interval_seconds": poll_interval,
            "offline_timeout_seconds": offline_timeout,
        }

    @app.post("/api/commands", dependencies=[Depends(authorize)])
    async def command(request: CommandRequest) -> dict[str, Any]:
        try:
            parts = shlex.split(request.command)
        except ValueError:
            parts = []
        address = parts[1] if len(parts) > 1 else None
        try:
            result = await run_in_threadpool(service.execute, request.command)
            if parts and parts[0] == "remove" and address is not None:
                bulb_status.pop(address, None)
                failed_since.pop(address, None)
                last_seen.pop(address, None)
            elif parts and parts[0] == "add" and address is not None:
                bulb_status.setdefault(address, None)
            elif address is not None and any(
                item["ip"] == address for item in service.known_bulbs()
            ):
                bulb_status[address] = True
                failed_since.pop(address, None)
                last_seen[address] = time.time()
            return {"ok": True, "result": result}
        except CommandError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except StorageError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        except DeviceError as exc:
            if address is not None and any(
                item["ip"] == address for item in service.known_bulbs()
            ):
                bulb_status[address] = False
                failed_since.setdefault(address, time.monotonic())
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/api/modes", dependencies=[Depends(authorize)])
    async def list_modes() -> dict[str, Any]:
        return {
            "modes": [
                {
                    **mode,
                    "running": name in mode_tasks and not mode_tasks[name].done(),
                }
                for name, mode in sorted(modes.items())
            ]
        }

    @app.post("/api/modes", dependencies=[Depends(authorize)])
    async def save_mode(request: ModeRequest) -> dict[str, Any]:
        name = request.name.strip()
        if not name:
            raise HTTPException(status_code=422, detail="Mode name cannot be blank")
        if "/" in name or "\\" in name:
            raise HTTPException(status_code=422, detail="Mode name cannot contain path separators")
        steps = []
        for step in request.steps:
            action = step.get("action")
            values = step.get("values", [])
            if not isinstance(values, list):
                raise HTTPException(status_code=422, detail="Task values must be a list")
            if action not in {"on", "off", "toggle", "status", "brightness", "color", "temp"}:
                raise HTTPException(status_code=422, detail=f"Unsupported task: {action}")
            expected = 0 if action in {"on", "off", "toggle", "status"} else 3 if action == "color" else 1
            if len(values) != expected:
                raise HTTPException(status_code=422, detail=f"Invalid values for task: {action}")
            if action == "brightness":
                values = [YeelightController._integer(str(values[0]), "brightness", 1, 100)]
            elif action == "temp":
                values = [YeelightController._integer(str(values[0]), "temperature", 1700, 6500)]
            elif action == "color":
                values = [
                    YeelightController._integer(str(value), channel, 0, 255)
                    for value, channel in zip(values, ("red", "green", "blue"))
                ]
            steps.append({"action": action, "values": values})

        if name in mode_tasks and not mode_tasks[name].done():
            raise HTTPException(status_code=409, detail="Stop the mode before editing it")
        modes[name] = {
            "name": name,
            "steps": steps,
            "delay_seconds": request.delay_seconds,
            "last_error": None,
            "running_ip": None,
        }
        save_modes()
        return {"ok": True, "mode": modes[name]}

    @app.delete("/api/modes/{name}", dependencies=[Depends(authorize)])
    async def delete_mode(name: str) -> dict[str, bool]:
        if name not in modes:
            raise HTTPException(status_code=404, detail="Mode not found")
        task = mode_tasks.pop(name, None)
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        del modes[name]
        save_modes()
        return {"ok": True}

    @app.post("/api/modes/{name}/start", dependencies=[Depends(authorize)])
    async def start_mode(name: str, request: ModeStartRequest) -> dict[str, str]:
        mode = modes.get(name)
        if mode is None:
            raise HTTPException(status_code=404, detail="Mode not found")
        try:
            parsed_address = ipaddress.ip_address(request.ip)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Enter a valid lamp IP address") from exc
        if parsed_address.version != 4:
            raise HTTPException(status_code=422, detail="Yeelight supports IPv4 addresses only")
        address = str(parsed_address)
        if address not in {item["ip"] for item in service.known_bulbs()}:
            raise HTTPException(status_code=404, detail="Add the lamp to the list before starting a mode")
        task = mode_tasks.get(name)
        if task is not None and not task.done():
            raise HTTPException(status_code=409, detail="Mode is already running")
        mode["last_error"] = None
        mode["running_ip"] = address

        async def repeat_commands() -> None:
            try:
                while True:
                    for step in mode["steps"]:
                        action = step["action"]
                        args = [address, *(str(value) for value in step["values"])]
                        line = " ".join([action, *args])
                        await run_in_threadpool(service.execute, line)
                        await asyncio.sleep(mode["delay_seconds"])
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                mode["last_error"] = str(exc)
            finally:
                mode["running_ip"] = None

        mode_tasks[name] = asyncio.create_task(repeat_commands())
        return {"status": "started", "ip": address}

    @app.post("/api/modes/{name}/stop", dependencies=[Depends(authorize)])
    async def stop_mode(name: str) -> dict[str, str]:
        if name not in modes:
            raise HTTPException(status_code=404, detail="Mode not found")
        task = mode_tasks.get(name)
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        return {"status": "stopped"}

    return app
