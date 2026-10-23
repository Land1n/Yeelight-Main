"""Server-rendered shell pages for the browser UI."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .deps import get_optional_session

router = APIRouter(include_in_schema=False)


def _templates_dir(request: Request) -> Path:
    return request.app.state.ctx.settings.frontend_dir / "templates"


def _safe_next(value: str | None) -> str:
    if not value or not value.startswith("/") or value.startswith("//"):
        return "/"
    if "\\" in value or "\r" in value or "\n" in value:
        return "/"
    return value


def _page(request: Request, template: str, *, page: str, title: str, **extra):
    path = request.url.path
    session = get_optional_session(request)
    if session is None:
        return RedirectResponse(f"/login?next={quote(path)}", status_code=303)
    templates = Jinja2Templates(directory=str(_templates_dir(request)))
    return templates.TemplateResponse(
        request,
        template,
        {
            "page": page,
            "title": title,
            "username": session["username"],
            **extra,
        },
    )


@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return _page(request, "home.html", page="home", title="Обзор")


@router.get("/bulbs", response_class=HTMLResponse)
async def bulbs(request: Request):
    return _page(request, "bulbs.html", page="bulbs", title="Лампы")


@router.get("/modes", response_class=HTMLResponse)
async def modes(request: Request):
    return _page(request, "modes.html", page="modes", title="Режимы")


@router.get("/console", response_class=HTMLResponse)
async def console(request: Request):
    return _page(request, "console.html", page="console", title="Консоль")


@router.get("/setup", response_class=HTMLResponse)
async def setup(request: Request):
    return _page(request, "setup.html", page="setup", title="Менеджеры и настройка")


@router.get("/help", response_class=HTMLResponse)
async def help_page(request: Request):
    return _page(request, "help.html", page="help", title="Инструкция")


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: str | None = None):
    if get_optional_session(request) is not None:
        return RedirectResponse("/", status_code=303)
    templates = Jinja2Templates(directory=str(_templates_dir(request)))
    return templates.TemplateResponse(
        request,
        "login.html",
        {"page": "login", "title": "Вход", "next": _safe_next(next)},
    )


__all__ = ["router"]
