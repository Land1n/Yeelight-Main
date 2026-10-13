from __future__ import annotations

import asyncio
import json
import os
import re
from collections.abc import Awaitable, Callable

import flet as ft

from yeelight_app.api_client import YeelightApiClient
from yeelight_app.widgets import bulb_card, empty_bulbs_card
from yeelight_config import load_project_env


HELP_TEXT = """Доступные команды

Лампы
  discover                         найти Yeelight в локальной сети
  list                             показать добавленные лампы
  add <IP>                         добавить лампу по IPv4-адресу
  remove <IP>                      удалить лампу из списка сервера
  status <IP>                      получить состояние лампы
  on <IP> / off <IP>               включить или выключить лампу
  toggle <IP>                      переключить состояние
  brightness <IP> <1-100>          установить яркость
  color <IP> <R> <G> <B>           установить RGB-цвет (каналы 0-255)
  color <IP> <#RRGGBB>             установить цвет шестнадцатеричным кодом
  temp <IP> <1700-6500>            установить цветовую температуру

Консоль
  help                             показать эту справку
  clear                            очистить вывод консоли"""


def local_command(text: str) -> str | None:
    """Вернуть локальное действие консоли или None для команды серверу."""
    command = text.strip().casefold()
    if command in {"help", "?"}:
        return "help"
    if command in {"clear", "cls"}:
        return "clear"
    return None


def main(page: ft.Page) -> None:
    load_project_env()
    page.title = "Yeelight"
    page.padding = 20
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = "#0b1018"
    page.scroll = ft.ScrollMode.AUTO
    preferences = ft.SharedPreferences()
    page.services.append(preferences)
    default_server_url = os.getenv("YEELIGHT_SERVER_URL", "http://127.0.0.1:8000")
    default_api_token = os.getenv("YEELIGHT_API_TOKEN", "")
    api = YeelightApiClient(default_server_url, default_api_token)

    async def close_api_client(_event) -> None:
        await api.aclose()

    page.on_close = close_api_client
    page.on_disconnect = close_api_client

    server_url = ft.TextField(
        label="Адрес сервера",
        value=default_server_url,
        keyboard_type=ft.KeyboardType.URL,
        autocorrect=False,
        expand=True,
        border_color="#344153",
        focused_border_color="#b6e36b",
        text_size=14,
    )
    api_token = ft.TextField(
        label="API-токен",
        hint_text="Не нужен, если сервер запущен без токена",
        password=True,
        can_reveal_password=True,
        value=default_api_token,
        expand=True,
        border_color="#344153",
        focused_border_color="#b6e36b",
        text_size=14,
    )
    status = ft.Text("Подключаемся…", size=12, color="#f6c85f")
    output = ft.ListView(expand=True, spacing=8, auto_scroll=True)
    bulbs = ft.Column(spacing=10)
    command = ft.TextField(
        label="Команда",
        hint_text="Например: discover, help или on 192.168.1.45",
        autocorrect=False,
        expand=True,
        border_color="#344153",
        focused_border_color="#b6e36b",
        text_size=14,
    )
    send_button = ft.Button(
        content=ft.Text("Выполнить"),
        icon=ft.Icons.PLAY_ARROW,
        style=ft.ButtonStyle(
            bgcolor="#b6e36b",
            color="#15200e",
            shape=ft.RoundedRectangleBorder(radius=12),
        ),
    )
    busy = False

    def card(content: ft.Control, *, padding: int = 18) -> ft.Container:
        return ft.Container(
            content=content,
            padding=padding,
            bgcolor="#151e2a",
            border=ft.Border.all(1, "#293747"),
            border_radius=18,
        )

    def section_title(title: str, subtitle: str | None = None) -> ft.Column:
        items = [ft.Text(title, size=17, weight=ft.FontWeight.BOLD, color="#f3f6fb")]
        if subtitle:
            items.append(ft.Text(subtitle, size=12, color="#91a0b3"))
        return ft.Column(items, spacing=4, tight=True)

    def log(message: str, color: str = "#d6deea") -> None:
        output.controls.append(
            ft.Text(
                message,
                selectable=True,
                color=color,
                font_family="monospace",
                size=12,
            )
        )
        if len(output.controls) > 100:
            del output.controls[:-100]

    def configure_api() -> None:
        # Поля можно менять до сохранения, поэтому синхронизируем настройки перед запросом.
        api.configure(server_url.value or "", api_token.value or "")

    async def refresh_bulbs() -> None:
        configure_api()
        bulb_list = await api.list_bulbs()
        existing = {
            control.data["ip"]: control
            for control in bulbs.controls
            if isinstance(control, ft.Container)
            and isinstance(control.data, dict)
            and "ip" in control.data
        }
        incoming = {bulb["ip"] for bulb in bulb_list}
        if (
            not bulb_list
            and len(bulbs.controls) == 1
            and getattr(bulbs.controls[0], "data", None) is None
        ):
            return
        if existing and set(existing) == incoming:
            for bulb in bulb_list:
                card_data = existing[bulb["ip"]].data
                color, label = {
                    True: ("#b6e36b", "Есть ответ"),
                    False: ("#ff6b6b", "Нет ответа"),
                    None: ("#748197", "Проверяем связь…"),
                }[bulb.get("online")]
                card_data["status_dot"].bgcolor = color
                card_data["status_label"].value = label
            return
        bulbs.controls.clear()
        if not bulb_list:
            bulbs.controls.append(empty_bulbs_card())
            return

        bulbs.controls.extend(
            bulb_card(bulb["ip"], command_handler, bulb.get("online"))
            for bulb in bulb_list
        )

    async def run_command(text: str) -> None:
        nonlocal busy
        text = text.strip()
        if not text:
            return

        local_action = local_command(text)
        if local_action == "clear":
            output.controls.clear()
            page.update()
            return
        if local_action == "help":
            log(f"> {text}", "#b6e36b")
            log(HELP_TEXT, "#d6deea")
            page.update()
            return
        if busy:
            return

        busy = True
        send_button.disabled = True
        log(f"> {text}", "#b6e36b")
        page.update()
        try:
            configure_api()
            result = await api.execute(text)
            log(json.dumps(result, ensure_ascii=False, indent=2))
            status.value = "Сервер подключён"
            status.color = "#b6e36b"
            if re.match(r"^(discover|add|remove|list)\b", text):
                try:
                    await refresh_bulbs()
                except (RuntimeError, ValueError, KeyError) as exc:
                    log(f"Список ламп не обновлён: {exc}", "#ff8585")
        except (RuntimeError, ValueError, KeyError) as exc:
            log(f"Ошибка: {exc}", "#ff8585")
            status.value = "Нет подключения"
            status.color = "#ff8585"
        finally:
            busy = False
            send_button.disabled = False
            page.update()

    async def submit_command(_event) -> None:
        text = command.value or ""
        command.value = ""
        await run_command(text)

    async def refresh_clicked(_event) -> None:
        await run_command("list")

    async def connect_clicked(_event) -> None:
        server_value = (server_url.value or "").strip().rstrip("/")
        token_value = (api_token.value or "").strip()
        if not re.fullmatch(r"https?://[^/]+", server_value, re.IGNORECASE):
            status.value = "Проверьте адрес сервера"
            status.color = "#ff8585"
            log(
                "Укажите адрес компьютера в локальной сети, например "
                "http://192.168.1.10:8000.",
                "#ff8585",
            )
            page.update()
            return

        connect_button.disabled = True
        status.value = "Сохраняем настройки…"
        status.color = "#f6c85f"
        page.update()
        try:
            url_saved = await preferences.set("server_url", server_value)
            token_saved = await preferences.set("api_token", token_value)
            if not url_saved or not token_saved:
                raise RuntimeError("Не удалось сохранить настройки на устройстве")
            server_url.value = server_value
            api_token.value = token_value
            api.configure(server_value, token_value)
        except Exception as exc:
            status.value = "Не удалось сохранить настройки"
            status.color = "#ff8585"
            log(f"Настройки не сохранены на устройстве: {exc}", "#ff8585")
            connect_button.disabled = False
            page.update()
            return

        try:
            await api.check_health()
            await refresh_bulbs()
            status.value = "Подключено • настройки сохранены"
            status.color = "#b6e36b"
            log(f"Подключено к {server_value}; настройки сохранены на этом устройстве.")
        except (RuntimeError, ValueError, KeyError) as exc:
            status.value = "Не удалось подключиться"
            status.color = "#ff8585"
            log(
                f"Настройки сохранены, но сервер недоступен или отклонил запрос: {exc}",
                "#ff8585",
            )
        finally:
            connect_button.disabled = False
            page.update()

    def command_handler(text: str) -> Callable[[ft.ControlEvent], Awaitable[None]]:
        async def handler(_event: ft.ControlEvent) -> None:
            await run_command(text)

        return handler

    command.on_submit = submit_command
    send_button.on_click = submit_command
    refresh_button = ft.Button(
        content=ft.Text("Обновить"),
        icon=ft.Icons.REFRESH,
        on_click=refresh_clicked,
    )
    connect_button = ft.Button(
        content=ft.Text("Сохранить и подключиться"),
        icon=ft.Icons.LINK,
        on_click=connect_clicked,
        style=ft.ButtonStyle(
            bgcolor="#b6e36b",
            color="#15200e",
            shape=ft.RoundedRectangleBorder(radius=12),
        ),
    )
    discover_button = ft.Button(
        content=ft.Text("Найти лампы"),
        icon=ft.Icons.SEARCH,
        on_click=command_handler("discover"),
    )
    clear_button = ft.Button(
        content=ft.Text("Очистить"),
        icon=ft.Icons.DELETE_OUTLINE,
        on_click=command_handler("clear"),
    )
    help_button = ft.Button(
        content=ft.Text("Справка"),
        icon=ft.Icons.HELP_OUTLINE,
        on_click=command_handler("help"),
    )

    header = card(
        ft.Row(
            [
                ft.Row(
                    [
                        ft.Container(
                            content=ft.Icon(ft.Icons.LIGHTBULB, color="#17210f", size=25),
                            padding=11,
                            bgcolor="#b6e36b",
                            border_radius=14,
                        ),
                        ft.Column(
                            [
                                ft.Text("Yeelight", size=23, weight=ft.FontWeight.BOLD),
                                ft.Text("Управление освещением", size=12, color="#91a0b3"),
                            ],
                            spacing=2,
                            tight=True,
                        ),
                    ],
                    spacing=13,
                ),
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Container(width=8, height=8, bgcolor="#b6e36b", border_radius=4),
                            status,
                        ],
                        spacing=8,
                    ),
                    padding=ft.Padding.symmetric(horizontal=12, vertical=8),
                    bgcolor="#202b25",
                    border_radius=20,
                ),
            ],
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            wrap=True,
            spacing=12,
        )
    )

    connection_card = card(
        ft.Column(
            [
                section_title("Подключение", "Настройте адрес API и авторизацию"),
                ft.Column(
                    [
                        server_url,
                        api_token,
                        connect_button,
                        ft.Text(
                            "Введите LAN-адрес компьютера, например "
                            "http://192.168.1.10:8000 — адрес покажется в окне сервера. "
                            "127.0.0.1 на телефоне указывает на сам телефон.",
                            size=11,
                            color="#91a0b3",
                        ),
                    ],
                    spacing=10,
                ),
            ],
            spacing=14,
        )
    )
    bulbs_card = card(
        ft.Column(
            [
                ft.Row(
                    [
                        section_title("Мои лампы", "Управляйте устройствами в вашей сети"),
                        ft.Row([discover_button, refresh_button], wrap=True, spacing=8),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    wrap=True,
                    spacing=12,
                ),
                bulbs,
            ],
            spacing=16,
        )
    )
    console_card = card(
        ft.Column(
            [
                ft.Row(
                    [
                        section_title("Командная строка", "Введите команду или воспользуйтесь справкой"),
                        ft.Row([help_button, clear_button], wrap=True, spacing=8),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    wrap=True,
                    spacing=12,
                ),
                ft.Container(
                    content=output,
                    height=260,
                    padding=14,
                    bgcolor="#0b111a",
                    border=ft.Border.all(1, "#263548"),
                    border_radius=14,
                ),
                ft.Row([command, send_button], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ft.Row(
                    [
                        ft.Text("Локальные команды:", size=11, color="#91a0b3"),
                        ft.TextButton("help", on_click=command_handler("help")),
                        ft.TextButton("clear", on_click=command_handler("clear")),
                    ],
                    spacing=2,
                ),
            ],
            spacing=13,
        )
    )

    page.add(
        ft.Container(
            content=ft.Column([header, connection_card, bulbs_card, console_card], spacing=16),
            padding=ft.Padding.symmetric(horizontal=4, vertical=6),
        )
    )

    async def initial_load() -> None:
        try:
            try:
                saved_url = await preferences.get("server_url")
                saved_token = await preferences.get("api_token")
                if isinstance(saved_url, str) and saved_url:
                    server_url.value = saved_url
                if isinstance(saved_token, str):
                    api_token.value = saved_token
            except Exception as exc:
                log(f"Не удалось загрузить сохранённые настройки: {exc}", "#ff8585")
            status.value = "Проверяем сохранённое подключение…"
            page.update()
            configure_api()
            await api.check_health()
            status.value = "Сервер подключён"
            status.color = "#b6e36b"
            await refresh_bulbs()
        except (RuntimeError, ValueError, KeyError) as exc:
            status.value = "Нет подключения"
            status.color = "#ff8585"
            log(
                f"Подключение: {exc}. Укажите адрес компьютера и нажмите "
                "«Сохранить и подключиться».",
                "#ff8585",
            )
        page.update()

    async def refresh_status_loop() -> None:
        while True:
            await asyncio.sleep(5)
            if busy:
                continue
            try:
                configure_api()
                await api.check_health()
                await refresh_bulbs()
                status.value = "Сервер подключён"
                status.color = "#b6e36b"
            except (RuntimeError, ValueError, KeyError) as exc:
                status.value = f"Нет подключения: {exc}"
                status.color = "#ff8585"
            page.update()

    async def start_app() -> None:
        await initial_load()
        page.run_task(refresh_status_loop)

    page.run_task(start_app)


if __name__ == "__main__":
    ft.run(main)
