"""Ядро manager: лампы, undo, мониторинг, действия и состояние. Без UI и без сети."""

from __future__ import annotations

import shutil
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

from lamp import Command, Lamp, LampError
from lamp.network import discover
from protocol import Action, ActionResult, LampState, ManagerState

from manager.base import (
    DEFAULT_CONFIG, LOG_LINES, MAX_UNDO, PACE_SECONDS, bundle_dir,
    read_json, valid_ipv4, write_json,
    data_dir as default_data_dir,
)
from manager.modes import ModesMixin


class Core(ModesMixin):
    """Потокобезопасное ядро. UI и синхронизация вызывают только его методы."""

    def __init__(self, data_dir=None, lamp_factory=Lamp, discover_fn=discover):
        self.dir = Path(data_dir) if data_dir else default_data_dir()
        self.dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._lamp_factory = lamp_factory
        self._discover = discover_fn
        self.config = {**DEFAULT_CONFIG, **read_json(self.dir / "config.json", {})}
        self._ips = list(read_json(self.dir / "bulbs.json", []))
        self._lamps = {}
        self._device_locks = {}
        self._last_call = {}
        self._status = {}
        self._offline_since = {}
        self._undo = {}
        self._modes_path = self.dir / "modes.json"
        if not self._modes_path.exists():
            shutil.copyfile(bundle_dir() / "default_modes.json", self._modes_path)
        self._modes = read_json(self._modes_path, {})
        self._runs = {}
        self._errors = {}
        self._log = deque(maxlen=LOG_LINES)
        self._stop = threading.Event()

    # ---------- журнал и конфиг ----------

    def log(self, text):
        with self._lock:
            self._log.append(f"{datetime.now():%H:%M:%S} {text}")

    def update_config(self, **values):
        with self._lock:
            self.config.update(values)
            write_json(self.dir / "config.json", self.config)

    # ---------- лампы ----------

    def _lamp(self, ip):
        """Вернуть лампу из списка. Вызывать под self._lock."""
        if ip not in self._ips:
            raise ValueError(f"лампы {ip} нет в списке")
        if ip not in self._lamps:
            self._lamps[ip] = self._lamp_factory(ip)
            self._device_locks[ip] = threading.Lock()
        return self._lamps[ip]

    def _device_call(self, ip, fn):
        """Выполнить fn под блокировкой лампы с паузой PACE_SECONDS между вызовами."""
        with self._lock:
            self._lamp(ip)
            dev_lock = self._device_locks[ip]
        with dev_lock:
            wait = PACE_SECONDS - (time.monotonic() - self._last_call.get(ip, 0.0))
            if wait > 0:
                time.sleep(wait)
            try:
                return fn()
            finally:
                self._last_call[ip] = time.monotonic()

    def _send(self, cmd):
        """Отправить команду; при обрыве сокета повторить один раз (кроме toggle)."""

        def run():
            try:
                cmd.execute()
            except LampError:
                if cmd.name == "toggle":
                    raise
                cmd.execute()

        self._device_call(cmd.lamp.ip, run)

    def _apply(self, cmd):
        """Выполнить команду пользователя и сохранить её для undo."""
        self._send(cmd)
        with self._lock:
            stack = self._undo.setdefault(cmd.lamp.ip, [])
            stack.append(cmd)
            del stack[:-MAX_UNDO]

    def _command(self, data):
        ip = (data or {}).get("ip")
        if not ip:
            raise ValueError("в команде не указан ip лампы")
        with self._lock:
            lamp = self._lamp(ip)
        return Command.from_dict(data, lamp=lamp)

    def command(self, data):
        cmd = self._command(data)
        self._apply(cmd)
        return f"{cmd.name} выполнена для {cmd.lamp.ip}"

    def undo(self, ip):
        with self._lock:
            stack = self._undo.get(ip, [])
            if not stack:
                raise ValueError(f"нет действий для отмены у {ip}")
            cmd = stack.pop()
        try:
            self._device_call(ip, cmd.undo)
        except LampError:
            with self._lock:
                self._undo.setdefault(ip, []).append(cmd)
            raise
        return f"действие отменено у {ip}"

    def add(self, ip):
        ip = valid_ipv4(ip)
        with self._lock:
            if ip not in self._ips:
                self._ips.append(ip)
                write_json(self.dir / "bulbs.json", self._ips)
        self.log(f"лампа {ip} добавлена")
        return ip

    def remove(self, ip):
        with self._lock:
            if ip not in self._ips:
                raise ValueError(f"лампы {ip} нет в списке")
            self._ips.remove(ip)
            write_json(self.dir / "bulbs.json", self._ips)
            for pool in (self._lamps, self._device_locks, self._last_call, self._status,
                         self._offline_since, self._undo):
                pool.pop(ip, None)
            for run in self._runs.values():
                if run["ip"] == ip:
                    run["stop"].set()
        self.log(f"лампа {ip} удалена")

    def discover(self):
        found = self._discover(timeout=2)
        ips = [valid_ipv4(item["ip"]) for item in found if item.get("ip")]
        for ip in ips:
            self.add(ip)
        self.log(f"поиск: найдено {len(ips)}")
        return ips

    # ---------- мониторинг ----------

    def _monitor_once(self):
        with self._lock:
            ips = list(self._ips)
            timeout = float(self.config["offline_timeout"])
        for ip in ips:
            try:
                props = self._device_call(ip, lambda ip=ip: self._lamp_state(ip))
            except LampError as ex:
                now = time.time()
                with self._lock:
                    since = self._offline_since.setdefault(ip, now)
                    self._status.setdefault(ip, {}).update(online=False, props={})
                if now - since >= timeout:
                    self.log(f"лампа {ip} недоступна {int(timeout)} с, удаляю")
                    self.remove(ip)
                else:
                    self.log(f"лампа {ip} не отвечает: {ex}")
                continue
            with self._lock:
                self._offline_since.pop(ip, None)
                self._status[ip] = {"online": True, "last_seen": time.time(), "props": props}

    def _lamp_state(self, ip):
        with self._lock:
            lamp = self._lamp(ip)
        return lamp.state()

    def _monitor_loop(self):
        while True:
            try:
                self._monitor_once()
            except Exception as ex:  # фоновый поток не должен падать
                self.log(f"мониторинг: {ex}")
            if self._stop.wait(float(self.config["monitor_interval"])):
                return

    def start(self):
        threading.Thread(target=self._monitor_loop, daemon=True, name="monitor").start()

    def stop(self):
        self._stop.set()
        with self._lock:
            for run in self._runs.values():
                run["stop"].set()

    # ---------- действия из сервера и состояние ----------

    def handle(self, action: Action) -> ActionResult:
        try:
            message, ok = self._dispatch(action), True
        except Exception as ex:  # ошибка одного действия не должна ронять sync
            message, ok = str(ex), False
        self.log(f"действие {action.kind}: {'ok' if ok else 'ошибка'} {message}")
        return ActionResult(id=action.id or 0, ok=ok, message=message)

    def _dispatch(self, a: Action) -> str:
        kind = a.kind
        if kind == "command":
            return self.command(a.command)
        if kind == "undo":
            return self.undo(a.ip)
        if kind == "discover":
            return f"найдено ламп: {len(self.discover())}"
        if kind == "add":
            return f"лампа {self.add(a.ip)} добавлена"
        if kind == "remove":
            self.remove(a.ip)
            return f"лампа {a.ip} удалена"
        mode = a.mode or {}
        if kind == "mode_save":
            self.save_mode(mode.get("name") or a.name, mode.get("steps", []),
                           mode.get("delay_seconds", 1.0))
            return "режим сохранён"
        if kind == "mode_delete":
            self.delete_mode(a.name)
            return "режим удалён"
        if kind == "mode_start":
            self.start_mode(a.name, a.ip)
            return f"режим «{a.name}» запущен"
        self.stop_mode(a.name)
        return f"режим «{a.name}» остановлен"

    def state(self) -> ManagerState:
        with self._lock:
            lamps = []
            for ip in self._ips:
                st = self._status.get(ip, {})
                lamps.append(LampState(
                    ip=ip,
                    online=st.get("online"),
                    last_seen=st.get("last_seen"),
                    props=st.get("props", {}),
                ))
            modes = []
            for name, mode in sorted(self._modes.items()):
                run = self._runs.get(name)
                modes.append({
                    "name": name,
                    "steps": mode["steps"],
                    "delay_seconds": mode["delay_seconds"],
                    "running": run is not None,
                    "running_ip": run["ip"] if run else None,
                    "last_error": self._errors.get(name),
                })
            return ManagerState(lamps=lamps, modes=modes, log=list(self._log))
