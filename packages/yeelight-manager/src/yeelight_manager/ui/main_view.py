"""Flet desktop interface for the manager.

The UI talks to :class:`ManagerService` directly; lamp operations run on worker
threads so the window never freezes on network timeouts.  All labels are in
Russian to match the web interface.
"""

from __future__ import annotations

import asyncio
import functools
import logging
from collections.abc import Callable
from typing import Any

import flet as ft
from yeelight_logic import YeelightLogicError

from .. import __version__
from ..agent import agent_status_text
from ..pairing import PairingError
from ..service import ManagerService

logger = logging.getLogger(__name__)

PAGE_PADDING = 24


def _color_for_state(state: str) -> str:
    if state == "connected":
        return ft.Colors.GREEN_400
    if state in {"unauthorized", "removed", "error"}:
        return ft.Colors.RED_400
    if state in {"connecting", "disconnected"}:
        return ft.Colors.AMBER_400
    return ft.Colors.ON_SURFACE_VARIANT


def _format_rgb(value: Any) -> str:
    if isinstance(value, (list, tuple)) and len(value) == 3:
        try:
            return "#{:02X}{:02X}{:02X}".format(*(int(item) for item in value))
        except (TypeError, ValueError):
            return ""
    return ""


def _parse_hex(value: str) -> list[int] | None:
    text = (value or "").strip().lstrip("#")
    if len(text) != 6:
        return None
    try:
        number = int(text, 16)
    except ValueError:
        return None
    return [(number >> 16) & 255, (number >> 8) & 255, number & 255]


class ManagerView:
    def __init__(self, page: ft.Page, service: ManagerService) -> None:
        self.page = page
        self.service = service
        self._selected_ip: str | None = None
        self._states: dict[str, dict[str, Any]] = {}
        self._nav_buttons: dict[str, ft.TextButton] = {}

        self._connection_text = ft.Text("—", weight=ft.FontWeight.BOLD)
        self._server_text = ft.Text("—", selectable=True)
        self._name_text = ft.Text("—", selectable=True)
        self._manager_id_text = ft.Text("—", selectable=True)
        self._server_version_text = ft.Text("—", selectable=True)
        self._heartbeat_text = ft.Text("—", selectable=True)
        self._token_text = ft.Text("—", selectable=True)
        self._api_text = ft.Text("—", selectable=True)
        self._error_text = ft.Text("", color=ft.Colors.RED_400, selectable=True)
        self._summary_text = ft.Text("—", selectable=True)

        self._lamp_dropdown = ft.Dropdown(
            label="Лампа",
            width=320,
            options=[],
            on_select=self._on_lamp_selected,
        )
        self._lamp_info = ft.Text("Лампа не выбрана", selectable=True)
        self._lamp_power = ft.Text("—")
        self._brightness_slider = ft.Slider(
            min=1,
            max=100,
            divisions=99,
            value=50,
            label="{value}",
            disabled=True,
            on_change_end=self._on_brightness_end,
        )
        self._temperature_slider = ft.Slider(
            min=1700,
            max=6500,
            divisions=48,
            value=4000,
            label="{value} K",
            disabled=True,
            on_change_end=self._on_temperature_end,
        )
        self._color_field = ft.TextField(
            label="Цвет (#RRGGBB)",
            width=190,
            hint_text="#FFAA00",
            disabled=True,
        )
        self._remove_lamp_button = ft.OutlinedButton(
            content=ft.Text("Удалить лампу"),
            disabled=True,
            on_click=self._confirm_remove_lamp,
        )

        self._wifi_ip = ft.TextField(label="IP лампы", width=220)
        self._wifi_ssid = ft.TextField(label="SSID сети", width=260)
        self._wifi_password = ft.TextField(
            label="Пароль Wi-Fi",
            password=True,
            can_reveal_password=True,
            width=260,
        )
        self._wifi_lan_switch = ft.Switch(
            label="Также попробовать включить LAN Control", value=False
        )
        self._wifi_confirm = ft.Checkbox(
            label="Я подтверждаю настройку Wi-Fi на этом устройстве", value=False
        )
        self._wifi_button = ft.FilledButton(
            content=ft.Text("Настроить Wi-Fi"),
            disabled=True,
            on_click=self._start_wifi_setup,
        )
        self._wifi_result = ft.Text("", selectable=True)

        self._lan_ip = ft.TextField(label="IP лампы", width=220)
        self._lan_confirm = ft.Checkbox(
            label="Я подтверждаю включение LAN Control на этом устройстве",
            value=False,
        )
        self._lan_button = ft.FilledButton(
            content=ft.Text("Включить LAN Control"),
            disabled=True,
            on_click=self._start_lan_control,
        )
        self._lan_result = ft.Text("", selectable=True)

        self._wifi_confirm.on_change = self._refresh_provisioning_buttons
        self._lan_confirm.on_change = self._refresh_provisioning_buttons

        self._content = ft.Column(expand=True, spacing=16, scroll=ft.ScrollMode.AUTO)

    # ------------------------------------------------------------------
    # Page assembly
    # ------------------------------------------------------------------

    def build(self) -> None:
        page = self.page
        page.title = "Yeelight Manager"
        try:
            page.theme_mode = ft.ThemeMode.SYSTEM
            page.window.width = 1180
            page.window.height = 820
            page.window.min_width = 900
            page.window.min_height = 620
        except Exception:  # pragma: no cover - windowless / mobile targets
            logger.debug("Could not configure the window", exc_info=True)

        self._nav_buttons = {
            "status": ft.TextButton(
                content=ft.Text("Статус"),
                on_click=lambda _e: self._show("status"),
            ),
            "lamps": ft.TextButton(
                content=ft.Text("Лампы"),
                on_click=lambda _e: self._show("lamps"),
            ),
            "provisioning": ft.TextButton(
                content=ft.Text("Wi-Fi и LAN"),
                on_click=lambda _e: self._show("provisioning"),
            ),
            "help": ft.TextButton(
                content=ft.Text("Справка"),
                on_click=lambda _e: self._show("help"),
            ),
        }
        header = ft.Row(
            controls=[
                ft.Icon(ft.Icons.LIGHTBULB_OUTLINE, color=ft.Colors.AMBER_400, size=30),
                ft.Column(
                    controls=[
                        ft.Text("Yeelight Manager", size=24, weight=ft.FontWeight.BOLD),
                        ft.Text(
                            "Локальный агент: команды приходят с сервера, лампы "
                            "доступны только в этой сети.",
                            size=12,
                            color=ft.Colors.ON_SURFACE_VARIANT,
                        ),
                    ],
                    spacing=2,
                ),
                ft.Container(expand=True),
                ft.TextButton(
                    content=ft.Text("Обновить"),
                    icon=ft.Icons.REFRESH,
                    on_click=lambda _e: self._refresh_all(),
                ),
            ],
            alignment=ft.MainAxisAlignment.START,
        )
        nav = ft.Row(
            controls=[
                self._nav_buttons["status"],
                self._nav_buttons["lamps"],
                self._nav_buttons["provisioning"],
                self._nav_buttons["help"],
            ],
            spacing=4,
            wrap=True,
        )
        page.add(
            ft.Container(
                content=ft.Column(
                    controls=[header, nav, ft.Divider(), self._content],
                    expand=True,
                    spacing=8,
                ),
                padding=PAGE_PADDING,
                expand=True,
            )
        )
        self._show("status")
        self._refresh_all()
        self.page.run_task(self._ticker)

    def _show(self, name: str) -> None:
        builders: dict[str, Callable[[], list[ft.Control]]] = {
            "status": self._build_status,
            "lamps": self._build_lamps,
            "provisioning": self._build_provisioning,
            "help": self._build_help,
        }
        for key, button in self._nav_buttons.items():
            button.style = (
                ft.ButtonStyle(bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST)
                if key == name
                else None
            )
        self._content.controls = builders.get(name, self._build_status)()
        if name == "lamps":
            self._refresh_lamp_choices()
        elif name == "provisioning":
            self._refresh_provisioning_buttons()
        self._refresh_status_labels()
        self.page.update()

    # ------------------------------------------------------------------
    # Status tab
    # ------------------------------------------------------------------

    def _build_status(self) -> list[ft.Control]:
        def info_row(label: str, value: ft.Control) -> ft.Row:
            return ft.Row(
                controls=[
                    ft.Text(label, width=190, color=ft.Colors.ON_SURFACE_VARIANT),
                    value,
                ],
                spacing=12,
            )

        return [
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Text("Подключение", size=18, weight=ft.FontWeight.BOLD),
                        info_row("Состояние", self._connection_text),
                        info_row("Сервер", self._server_text),
                        info_row("Имя менеджера", self._name_text),
                        info_row("ID менеджера", self._manager_id_text),
                        info_row("Версия сервера", self._server_version_text),
                        info_row("Heartbeat", self._heartbeat_text),
                        info_row("Отпечаток токена", self._token_text),
                        info_row("Локальный API", self._api_text),
                        self._error_text,
                        ft.Row(
                            controls=[
                                ft.FilledButton(
                                    content=ft.Text("Привязать"),
                                    icon=ft.Icons.LINK,
                                    on_click=self._show_pair_dialog,
                                ),
                                ft.OutlinedButton(
                                    content=ft.Text("Переподключить"),
                                    icon=ft.Icons.REFRESH,
                                    on_click=lambda _e: self._reconnect(),
                                ),
                                ft.TextButton(
                                    content=ft.Text("Отвязать"),
                                    icon=ft.Icons.LINK_OFF,
                                    on_click=self._confirm_unpair,
                                ),
                            ],
                            wrap=True,
                            spacing=8,
                        ),
                    ],
                    spacing=10,
                ),
                padding=20,
                border_radius=12,
                bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            ),
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Text("Лампы", size=18, weight=ft.FontWeight.BOLD),
                        self._summary_text,
                        ft.Text(
                            "Состояние ламп обновляется автоматически. Для управления "
                            "откройте вкладку «Лампы».",
                            size=12,
                            color=ft.Colors.ON_SURFACE_VARIANT,
                        ),
                    ],
                    spacing=8,
                ),
                padding=20,
                border_radius=12,
                bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            ),
        ]

    def _refresh_status_labels(self) -> None:
        snapshot = self.service.snapshot()
        agent = snapshot["agent"]
        state = str(agent.get("state") or "")
        self._connection_text.value = agent_status_text(agent)
        self._connection_text.color = _color_for_state(state)
        self._server_text.value = str(snapshot["server_url"])
        self._name_text.value = str(snapshot["manager_name"])
        self._manager_id_text.value = str(agent.get("manager_id") or "—")
        self._server_version_text.value = str(agent.get("server_version") or "—")
        heartbeat = agent.get("heartbeat_interval_seconds")
        self._heartbeat_text.value = f"{heartbeat:g} с" if heartbeat else "—"
        fingerprint = snapshot.get("token_fingerprint") or ""
        self._token_text.value = (
            f"{fingerprint} (сохранён)" if fingerprint else "не сохранён"
        )
        local = snapshot.get("local_api") or {}
        if local.get("enabled"):
            self._api_text.value = (
                f"{local.get('url')} "
                f"({'работает' if local.get('running') else 'остановлен'})"
            )
        else:
            self._api_text.value = "выключен"
        errors = [str(agent.get("error") or ""), str(snapshot.get("token_error") or "")]
        error_text = " · ".join(item for item in errors if item)
        self._error_text.value = error_text
        online = sum(
            1 for lamp in snapshot.get("lamps", []) if lamp.get("online")
        )
        self._summary_text.value = (
            f"Всего: {snapshot.get('lamp_count', 0)}, в сети: {online}"
        )

    # ------------------------------------------------------------------
    # Lamps tab
    # ------------------------------------------------------------------

    def _build_lamps(self) -> list[ft.Control]:
        return [
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Row(
                            controls=[
                                self._lamp_dropdown,
                                ft.IconButton(
                                    icon=ft.Icons.REFRESH,
                                    tooltip="Обновить состояние",
                                    on_click=lambda _e: self._refresh_selected_lamp(),
                                ),
                                ft.OutlinedButton(
                                    content=ft.Text("Найти лампы"),
                                    icon=ft.Icons.SEARCH,
                                    on_click=lambda _e: self._discover(),
                                ),
                                ft.OutlinedButton(
                                    content=ft.Text("Добавить по IP"),
                                    icon=ft.Icons.ADD,
                                    on_click=self._show_add_lamp_dialog,
                                ),
                                self._remove_lamp_button,
                            ],
                            wrap=True,
                            spacing=8,
                        ),
                        ft.Divider(),
                        self._lamp_info,
                    ],
                    spacing=10,
                ),
                padding=20,
                border_radius=12,
                bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            ),
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Text("Питание", size=18, weight=ft.FontWeight.BOLD),
                        ft.Row(
                            controls=[
                                ft.FilledButton(
                                    content=ft.Text("Включить"),
                                    icon=ft.Icons.POWER,
                                    on_click=lambda _e: self._run_action("power", {"state": "on"}),
                                ),
                                ft.OutlinedButton(
                                    content=ft.Text("Выключить"),
                                    on_click=lambda _e: self._run_action("power", {"state": "off"}),
                                ),
                                ft.OutlinedButton(
                                    content=ft.Text("Переключить"),
                                    on_click=lambda _e: self._run_action("power", {"state": "toggle"}),
                                ),
                                self._lamp_power,
                            ],
                            wrap=True,
                            spacing=8,
                        ),
                        ft.Text("Яркость", size=18, weight=ft.FontWeight.BOLD),
                        self._brightness_slider,
                        ft.FilledButton(
                            content=ft.Text("Применить яркость"),
                            on_click=lambda _e: self._run_action(
                                "brightness",
                                {"value": int(self._brightness_slider.value or 50)},
                            ),
                        ),
                        ft.Text(
                            "Цветовая температура", size=18, weight=ft.FontWeight.BOLD
                        ),
                        self._temperature_slider,
                        ft.FilledButton(
                            content=ft.Text("Применить температуру"),
                            on_click=lambda _e: self._run_action(
                                "color_temperature",
                                {"value": int(self._temperature_slider.value or 4000)},
                            ),
                        ),
                        ft.Text("Цвет", size=18, weight=ft.FontWeight.BOLD),
                        ft.Row(
                            controls=[
                                self._color_field,
                                ft.FilledButton(
                                    content=ft.Text("Применить цвет"),
                                    on_click=self._apply_color,
                                ),
                            ],
                            wrap=True,
                            spacing=8,
                        ),
                    ],
                    spacing=10,
                ),
                padding=20,
                border_radius=12,
                bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            ),
        ]

    def _on_lamp_selected(self, _event: Any = None) -> None:
        self._selected_ip = self._lamp_dropdown.value
        self._load_lamp_controls()
        self.page.update()

    def _refresh_lamp_choices(self) -> None:
        states = self.service.runtime.lamp_states()
        self._states = {str(item["ip"]): item for item in states}
        options = []
        for ip in sorted(self._states):
            state = self._states[ip]
            label = state.get("name") or "Yeelight"
            options.append(ft.dropdown.Option(key=ip, text=f"{ip} · {label}"))
        self._lamp_dropdown.options = options
        if self._selected_ip not in self._states:
            self._selected_ip = sorted(self._states)[0] if self._states else None
        self._lamp_dropdown.value = self._selected_ip
        self._load_lamp_controls()
        self.page.update()

    def _load_lamp_controls(self) -> None:
        state = self._states.get(self._selected_ip or "")
        has_lamp = state is not None
        self._brightness_slider.disabled = not has_lamp
        self._temperature_slider.disabled = not has_lamp
        self._color_field.disabled = not has_lamp
        self._remove_lamp_button.disabled = not has_lamp
        if not state:
            self._lamp_info.value = (
                "Лампы не найдены. Нажмите «Найти лампы» или добавьте IP вручную."
            )
            self._lamp_power.value = "—"
            return
        power = state.get("power")
        self._lamp_power.value = {
            "on": "включена",
            "off": "выключена",
        }.get(str(power), "неизвестно")
        brightness = state.get("brightness")
        if isinstance(brightness, int):
            self._brightness_slider.value = brightness
        temperature = state.get("color_temperature")
        if isinstance(temperature, int):
            self._temperature_slider.value = temperature
        rgb = _format_rgb(state.get("rgb"))
        if rgb:
            self._color_field.value = rgb
        online = state.get("online")
        last_error = state.get("last_error")
        parts = [
            f"IP: {state.get('ip')}",
            f"Имя: {state.get('name') or '—'}",
            f"Модель: {state.get('model') or '—'}",
            f"В сети: {'да' if online else 'нет' if online is False else 'неизвестно'}",
            f"Мощность: {power or '—'}",
            f"Яркость: {brightness if brightness is not None else '—'}",
            f"Температура: {temperature if temperature is not None else '—'} K",
            f"Цвет: {rgb or '—'}",
        ]
        if last_error:
            parts.append(f"Последняя ошибка: {last_error}")
        self._lamp_info.value = "\n".join(parts)

    def _refresh_selected_lamp(self) -> None:
        if not self._selected_ip:
            self._snack("Сначала выберите лампу.")
            return
        ip = self._selected_ip
        self.page.run_thread(self._status_worker, ip)

    def _status_worker(self, ip: str) -> None:
        result = self.service.runtime.run_action("status", ip)
        if not result.ok:
            self._snack(result.message, error=True)
        self._refresh_lamp_choices()

    def _run_action(self, action: str, params: dict[str, Any]) -> None:
        ip = self._selected_ip
        if not ip:
            self._snack("Сначала выберите лампу.")
            return
        self.page.run_thread(self._action_worker, action, ip, params)

    def _action_worker(self, action: str, ip: str, params: dict[str, Any]) -> None:
        result = self.service.runtime.run_action(action, ip, params)
        if result.ok:
            self._snack(result.message)
        else:
            self._snack(result.message, error=True)
        self._refresh_lamp_choices()

    def _apply_color(self) -> None:
        rgb = _parse_hex(self._color_field.value or "")
        if rgb is None:
            self._snack("Цвет должен быть в формате #RRGGBB.", error=True)
            return
        self._run_action("color", {"rgb": rgb})

    def _discover(self) -> None:
        self.page.run_thread(self._discover_worker)

    def _discover_worker(self) -> None:
        result = self.service.runtime.discover()
        if result.ok:
            bulbs = (result.data or {}).get("bulbs") or []
            self._snack(f"Найдено ламп: {len(bulbs)}")
        else:
            self._snack(result.message, error=True)
        self._refresh_lamp_choices()

    def _show_add_lamp_dialog(self) -> None:
        field = ft.TextField(label="IP-адрес лампы", hint_text="192.168.1.42")
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Добавить лампу"),
            content=field,
            actions=[
                ft.TextButton(
                    content=ft.Text("Отмена"),
                    on_click=lambda _e: self.page.pop_dialog(),
                ),
                ft.FilledButton(
                    content=ft.Text("Добавить"),
                    on_click=lambda _e: self._add_lamp(field.value or ""),
                ),
            ],
        )
        self.page.show_dialog(dialog)

    def _add_lamp(self, ip: str) -> None:
        self.page.pop_dialog()
        ip = ip.strip()
        if not ip:
            self._snack("Введите IP-адрес.", error=True)
            return
        self.page.run_thread(self._add_lamp_worker, ip)

    def _add_lamp_worker(self, ip: str) -> None:
        result = self.service.runtime.add_lamp(ip)
        if result.ok:
            self._selected_ip = ip
            self._snack(result.message)
        else:
            self._snack(result.message, error=True)
        self._refresh_lamp_choices()

    def _confirm_remove_lamp(self, _event: Any = None) -> None:
        ip = self._selected_ip
        if not ip:
            return

        def remove(_event: Any = None) -> None:
            self.page.pop_dialog()
            self.page.run_thread(self._remove_lamp_worker, ip)

        self.page.show_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text("Удалить лампу?"),
                content=ft.Text(f"Лампа {ip} будет удалена из списка менеджера."),
                actions=[
                    ft.TextButton(
                        content=ft.Text("Отмена"),
                        on_click=lambda _e: self.page.pop_dialog(),
                    ),
                    ft.FilledButton(
                        content=ft.Text("Удалить"),
                        on_click=remove,
                    ),
                ],
            )
        )

    def _remove_lamp_worker(self, ip: str) -> None:
        result = self.service.runtime.remove_lamp(ip)
        if result.ok:
            self._selected_ip = None
            self._snack(result.message)
        else:
            self._snack(result.message, error=True)
        self._refresh_lamp_choices()

    # ------------------------------------------------------------------
    # Pairing dialogs
    # ------------------------------------------------------------------

    def _show_pair_dialog(self) -> None:
        code = ft.TextField(label="Код привязки", hint_text="ABCDE12345")
        name = ft.TextField(label="Имя менеджера", value=self.service.settings.manager_name)
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Привязать к серверу"),
            content=ft.Column(
                controls=[
                    ft.Text(
                        "Создайте код в веб-интерфейсе сервера на странице "
                        "«Менеджеры» и введите его здесь.",
                        size=12,
                        color=ft.Colors.ON_SURFACE_VARIANT,
                    ),
                    code,
                    name,
                ],
                spacing=10,
                width=360,
            ),
            actions=[
                ft.TextButton(
                    content=ft.Text("Отмена"),
                    on_click=lambda _e: self.page.pop_dialog(),
                ),
                ft.FilledButton(
                    content=ft.Text("Привязать"),
                    on_click=lambda _e: self._pair(code.value or "", name.value or ""),
                ),
            ],
        )
        self.page.show_dialog(dialog)

    def _pair(self, code: str, name: str) -> None:
        self.page.pop_dialog()
        self.page.run_thread(self._pair_worker, code, name)

    def _pair_worker(self, code: str, name: str) -> None:
        try:
            outcome = self.service.pair(code, name=name or None)
        except PairingError as exc:
            self._snack(str(exc), error=True)
        except Exception as exc:  # pragma: no cover - defensive
            self._snack(f"Не удалось привязаться: {exc}", error=True)
        else:
            self._snack(f"Готово: {outcome.manager_name}")
        self._refresh_status_labels()
        self.page.update()

    def _reconnect(self) -> None:
        self.service.reconnect()
        self._snack("Переподключение запущено.")
        self._refresh_status_labels()
        self.page.update()

    def _confirm_unpair(self, _event: Any = None) -> None:
        def unpair(_event: Any = None) -> None:
            self.page.pop_dialog()
            self.page.run_thread(self._unpair_worker)

        self.page.show_dialog(
            ft.AlertDialog(
                modal=True,
                title=ft.Text("Отвязать менеджер?"),
                content=ft.Text("Сохранённый токен будет удалён. Для работы потребуется новый код."),
                actions=[
                    ft.TextButton(
                        content=ft.Text("Отмена"),
                        on_click=lambda _e: self.page.pop_dialog(),
                    ),
                    ft.FilledButton(
                        content=ft.Text("Отвязать"),
                        on_click=unpair,
                    ),
                ],
            )
        )

    def _unpair_worker(self) -> None:
        self.service.unpair()
        self._snack("Менеджер отвязан.")
        self._refresh_status_labels()
        self.page.update()

    # ------------------------------------------------------------------
    # Provisioning tab
    # ------------------------------------------------------------------

    def _build_provisioning(self) -> list[ft.Control]:
        return [
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Text("Настройка Wi-Fi", size=18, weight=ft.FontWeight.BOLD),
                        ft.Text(
                            "Лампа должна быть доступна по локальному miIO-протоколу. "
                            "Пароль используется только для одного зашифрованного запроса "
                            "и не сохраняется. Поддерживается модель yeelink.light.color1.",
                            size=12,
                            color=ft.Colors.ON_SURFACE_VARIANT,
                        ),
                        ft.Row(
                            controls=[self._wifi_ip, self._wifi_ssid, self._wifi_password],
                            wrap=True,
                            spacing=12,
                        ),
                        self._wifi_lan_switch,
                        self._wifi_confirm,
                        self._wifi_button,
                        self._wifi_result,
                    ],
                    spacing=10,
                ),
                padding=20,
                border_radius=12,
                bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            ),
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Text(
                            "Включение LAN Control", size=18, weight=ft.FontWeight.BOLD
                        ),
                        ft.Text(
                            "Запрос выполняется локально и меняет настройки лампы. "
                            "Успешный ответ устройства не подтверждает, что TCP 55443 "
                            "уже доступен — проверьте лампу после перезагрузки.",
                            size=12,
                            color=ft.Colors.ON_SURFACE_VARIANT,
                        ),
                        ft.Row(
                            controls=[self._lan_ip],
                            wrap=True,
                            spacing=12,
                        ),
                        self._lan_confirm,
                        self._lan_button,
                        self._lan_result,
                    ],
                    spacing=10,
                ),
                padding=20,
                border_radius=12,
                bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            ),
        ]

    def _refresh_provisioning_buttons(self, _event: Any = None) -> None:
        self._wifi_button.disabled = not bool(self._wifi_confirm.value)
        self._lan_button.disabled = not bool(self._lan_confirm.value)
        self.page.update()

    def _start_wifi_setup(self, _event: Any = None) -> None:
        if not self._wifi_confirm.value:
            self._snack("Подтвердите настройку Wi-Fi.", error=True)
            return
        ip = (self._wifi_ip.value or "").strip()
        ssid = self._wifi_ssid.value or ""
        password = self._wifi_password.value or ""
        if not ip or not ssid or not password:
            self._snack("Заполните IP, SSID и пароль.", error=True)
            return
        enable_lan = bool(self._wifi_lan_switch.value)
        self._wifi_result.value = "Выполняется…"
        self._wifi_result.color = None
        self.page.update()
        self.page.run_thread(
            self._wifi_worker, ip, ssid, password, enable_lan
        )

    def _wifi_worker(self, ip: str, ssid: str, password: str, enable_lan: bool) -> None:
        try:
            result = self.service.runtime.provision_wifi(
                ip,
                ssid,
                password,
                enable_lan_control=enable_lan,
                confirm=True,
            )
        except (YeelightLogicError, OSError) as exc:
            self._wifi_result.value = f"Ошибка: {exc}"
            self._wifi_result.color = ft.Colors.RED_400
            self._snack(f"Wi-Fi: {exc}", error=True)
        else:
            self._wifi_result.value = (
                f"Wi-Fi: {result.wifi_message}\n"
                f"LAN Control: {result.lan_control_message}"
            )
            self._wifi_result.color = None
            self._snack("Запрос Wi-Fi выполнен; проверьте лампу.")
        finally:
            self._wifi_password.value = ""
            self.page.update()

    def _start_lan_control(self, _event: Any = None) -> None:
        if not self._lan_confirm.value:
            self._snack("Подтвердите включение LAN Control.", error=True)
            return
        ip = (self._lan_ip.value or "").strip()
        if not ip:
            self._snack("Введите IP-адрес.", error=True)
            return
        self._lan_result.value = "Выполняется…"
        self._lan_result.color = None
        self.page.update()
        self.page.run_thread(self._lan_worker, ip)

    def _lan_worker(self, ip: str) -> None:
        try:
            result = self.service.runtime.provision_lan_control(ip, confirm=True)
        except (YeelightLogicError, OSError) as exc:
            self._lan_result.value = f"Ошибка: {exc}"
            self._lan_result.color = ft.Colors.RED_400
            self._snack(f"LAN Control: {exc}", error=True)
        else:
            self._lan_result.value = result.lan_control_message
            self._lan_result.color = None
            self._snack("Запрос LAN Control выполнен.")
        finally:
            self.page.update()

    # ------------------------------------------------------------------
    # Help tab
    # ------------------------------------------------------------------

    def _build_help(self) -> list[ft.Control]:
        paths = self.service.snapshot().get("paths", {})
        return [
            ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Text("Как это работает", size=18, weight=ft.FontWeight.BOLD),
                        ft.Text(
                            "Менеджер подключается к серверу по исходящему WebSocket. "
                            "Сервер отправляет только типизированные действия; "
                            "команды выполняются здесь, в локальной сети.",
                        ),
                        ft.Text("Безопасность", size=18, weight=ft.FontWeight.BOLD),
                        ft.Text(
                            "Токен менеджера хранится локально: DPAPI на Windows или файл "
                            "0600 на других системах. Пароль Wi-Fi не сохраняется и не "
                            "пишется в журналы. Настройка Wi-Fi и LAN Control доступна "
                            "только с этого компьютера и требует явного подтверждения."
                        ),
                        ft.Text("Файлы", size=18, weight=ft.FontWeight.BOLD),
                        ft.Text(
                            "\n".join(f"{key}: {value}" for key, value in paths.items()),
                            selectable=True,
                            size=12,
                        ),
                        ft.Text(
                            f"Версия менеджера: {__version__}",
                            size=12,
                            color=ft.Colors.ON_SURFACE_VARIANT,
                        ),
                    ],
                    spacing=10,
                ),
                padding=20,
                border_radius=12,
                bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
            )
        ]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _refresh_all(self) -> None:
        self._refresh_status_labels()
        self.page.run_thread(self._refresh_lamps_worker)

    def _refresh_lamps_worker(self) -> None:
        try:
            self.service.runtime.refresh_states()
        except Exception:  # pragma: no cover - defensive
            logger.exception("Manual lamp refresh failed")
        self._refresh_lamp_choices()
        self._refresh_status_labels()
        self.page.update()

    async def _ticker(self) -> None:
        while True:
            await asyncio.sleep(2.0)
            try:
                self._refresh_status_labels()
                self.page.update()
            except Exception:  # pragma: no cover - UI closed while polling
                logger.debug("Status ticker stopped", exc_info=True)
                return

    def _snack(self, message: str, *, error: bool = False) -> None:
        snack = ft.SnackBar(
            content=ft.Text(message),
            bgcolor=ft.Colors.RED_400 if error else None,
        )
        try:
            self.page.show_dialog(snack)
        except Exception:  # pragma: no cover - UI closing
            logger.debug("Could not show snackbar", exc_info=True)


def _main(page: ft.Page, service: ManagerService) -> None:
    ManagerView(page, service).build()


def run_ui(service: ManagerService) -> None:
    """Run the Flet desktop application (blocks until the window closes)."""

    ft.run(
        functools.partial(_main, service=service),
        name="Yeelight Manager",
        view=ft.AppView.FLET_APP,
        assets_dir=None,
    )


__all__ = ["ManagerView", "run_ui"]
