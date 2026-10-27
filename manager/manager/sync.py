"""Синхронизация с сервером: раз в poll_interval отправляет состояние и забирает действия."""

from __future__ import annotations

import threading

import httpx

from protocol import ActionResult, PollRequest, PollResponse


class Syncer:
    """Фоновый polling-клиент. Ошибки сети пишутся в журнал, цикл продолжается."""

    def __init__(self, core):
        self.core = core
        self._thread = None
        self._stop = threading.Event()
        self._results = []
        self.connected = False

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        if self.running:
            return
        if not self.core.config["server_url"]:
            raise ValueError("не задан адрес сервера")
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="sync")
        self._thread.start()
        self.core.log("синхронизация запущена")

    def stop(self):
        self._stop.set()
        self.connected = False
        self.core.log("синхронизация остановлена")

    def poll_once(self, client):
        """Один цикл: отправить состояние и результаты, выполнить полученные действия."""
        url = self.core.config["server_url"].rstrip("/") + "/agent/poll"
        request = PollRequest(state=self.core.state(), results=self._results)
        response = client.post(
            url,
            json=request.model_dump(),
            headers={"X-Access-Key": self.core.config["access_key"]},
        )
        response.raise_for_status()
        actions = PollResponse.model_validate(response.json()).actions
        self._results = [self.core.handle(action) for action in actions]
        return len(actions)

    def _loop(self):
        interval = float(self.core.config["poll_interval"])
        with httpx.Client(timeout=10) as client:
            while not self._stop.is_set():
                try:
                    self.poll_once(client)
                    self.connected = True
                except (httpx.HTTPError, ValueError) as ex:
                    self.connected = False
                    self.core.log(f"сервер: {ex}")
                self._stop.wait(interval)
