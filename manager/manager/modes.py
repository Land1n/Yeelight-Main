"""Режимы: сохранение, запуск и остановка циклов команд. Миксин для Core."""

from __future__ import annotations

import threading

from lamp import Command, LampError

from manager.base import MAX_MODE_FAILURES, write_json


class ModesMixin:
    """Ожидает атрибуты Core: _lock, _modes, _modes_path, _runs, _errors, _send, _lamp, log."""

    def save_mode(self, name, steps, delay_seconds):
        name = str(name or "").strip()
        if not name or "/" in name or "\\" in name:
            raise ValueError("некорректное имя режима")
        if not 1 <= len(steps) <= 50:
            raise ValueError("в режиме от 1 до 50 шагов")
        delay = float(delay_seconds)
        if not 0.1 <= delay <= 3600:
            raise ValueError("пауза от 0.1 до 3600 с")
        clean = []
        for step in steps:
            cmd = Command.from_dict({**step, "ip": "0.0.0.0"})  # проверка параметров
            data = cmd.to_dict()
            data.pop("ip")
            clean.append(data)
        with self._lock:
            self._modes[name] = {"steps": clean, "delay_seconds": delay}
            write_json(self._modes_path, self._modes)
        self.log(f"режим «{name}» сохранён")

    def delete_mode(self, name):
        self.stop_mode(name)
        with self._lock:
            if name not in self._modes:
                raise ValueError(f"режим «{name}» не найден")
            del self._modes[name]
            self._errors.pop(name, None)
            write_json(self._modes_path, self._modes)
        self.log(f"режим «{name}» удалён")

    def start_mode(self, name, ip):
        with self._lock:
            if name not in self._modes:
                raise ValueError(f"режим «{name}» не найден")
            if name in self._runs:
                raise ValueError(f"режим «{name}» уже запущен")
            self._lamp(ip)
            stop = threading.Event()
            self._runs[name] = {"stop": stop, "ip": ip}
            self._errors[name] = None
        threading.Thread(target=self._run_mode, args=(name, ip, stop), daemon=True).start()
        self.log(f"режим «{name}» запущен на {ip}")

    def stop_mode(self, name):
        with self._lock:
            run = self._runs.get(name)
        if run is not None:
            run["stop"].set()
            self.log(f"режим «{name}» остановлен")

    def _run_mode(self, name, ip, stop):
        failures = 0
        try:
            while not stop.is_set():
                with self._lock:
                    mode = self._modes.get(name)
                if mode is None:
                    return
                for step in mode["steps"]:
                    if stop.is_set():
                        return
                    try:
                        cmd = Command.from_dict({**step, "ip": ip}, lamp=self._lamp_for(ip))
                        self._send(cmd)
                        failures = 0
                        self._set_error(name, None)
                    except (LampError, ValueError) as ex:
                        failures += 1
                        self._set_error(name, str(ex))
                        if failures >= MAX_MODE_FAILURES:
                            self.log(f"режим «{name}» остановлен после {failures} ошибок")
                            return
                        stop.wait(max(mode["delay_seconds"], 1.0))
                        continue
                    stop.wait(mode["delay_seconds"])
        finally:
            with self._lock:
                if self._runs.get(name, {}).get("stop") is stop:
                    del self._runs[name]

    def _lamp_for(self, ip):
        with self._lock:
            return self._lamp(ip)

    def _set_error(self, name, error):
        with self._lock:
            self._errors[name] = error
