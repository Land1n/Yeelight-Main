"""Запуск: python -m server. Настройки читаются из server/.env (см. .env.example)."""

import os
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

from server.app import create_app

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
app = create_app(os.environ.get("ACCESS_KEY", ""), os.environ.get("DB_PATH", "server.db"))

if __name__ == "__main__":
    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"),
                port=int(os.environ.get("PORT", "8000")))
