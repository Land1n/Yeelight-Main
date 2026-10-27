"""FastAPI-приложение: очередь действий, состояние manager и статика сайта."""

from __future__ import annotations

import secrets
import time
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from protocol import Action, PollRequest, PollResponse

from server.db import Store

ONLINE_WINDOW_SECONDS = 5
DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


def create_app(access_key: str, db_path: str) -> FastAPI:
    if not access_key:
        raise RuntimeError("ACCESS_KEY не задан")
    store = Store(db_path)
    app = FastAPI(title="Yeelight server")

    def check_key(x_access_key: str | None = Header(default=None)):
        if x_access_key is None or not secrets.compare_digest(x_access_key, access_key):
            raise HTTPException(status_code=401, detail="неверный ключ доступа")

    @app.post("/agent/poll", response_model=PollResponse, dependencies=[Depends(check_key)])
    def poll(request: PollRequest):
        store.save_state(request.state.model_dump())
        store.apply_results([r.model_dump() for r in request.results])
        return PollResponse(actions=store.take_pending())

    @app.get("/api/state")
    def get_state():
        state, updated = store.load_state()
        online = updated is not None and time.time() - updated < ONLINE_WINDOW_SECONDS
        return {"online": online, "updated": updated, **(state or {"lamps": [], "modes": [],
                                                                 "log": []})}

    @app.post("/api/actions")
    def post_action(action: Action):
        if action.kind == "command" and not action.command:
            raise HTTPException(status_code=422, detail="для команды нужен объект command")
        return {"id": store.add_action(action.model_dump(exclude={"id"}))}

    @app.get("/api/actions/{action_id}")
    def get_action(action_id: int):
        item = store.get_action(action_id)
        if item is None:
            raise HTTPException(status_code=404, detail="действие не найдено")
        return item

    if DIST.is_dir():
        app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

        @app.get("/{path:path}")
        def spa(path: str):
            target = DIST / path
            if path and target.is_file():
                return FileResponse(target)
            return FileResponse(DIST / "index.html")

    return app
