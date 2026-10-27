"""Окно manager на Flet: лампы, режимы, настройка, журнал."""

from __future__ import annotations

import time

import flet as ft

from lamp.network import connect_to_wifi, enable_lan_control

from manager.core import Core
from manager.sync import Syncer

COLOR_PRESETS = {"Белый": (255, 255, 255), "Красный": (255, 0, 0), "Зелёный": (0, 255, 0),
                 "Синий": (0, 0, 255), "Фиолетовый": (160, 0, 255)}


def main(page: ft.Page):
    page.title = "Yeelight manager"
    page.window.width = 900
    page.window.height = 680
    page.padding = 12

    core = Core()
    core.start()
    syncer = Syncer(core)
    msg = ft.Text("")

    def notify(text):
        msg.value = text
        page.update()

    def guarded(fn):
        """Запуск операции с сообщением об ошибке вместо падения UI."""
        def run(*_):
            try:
                notify(fn() or "готово")
            except Exception as ex:
                notify(f"ошибка: {ex}")
        return run

    def in_background(fn):
        def run(*_):
            def job():
                try:
                    notify(fn() or "готово")
                except Exception as ex:
                    notify(f"ошибка: {ex}")
            page.run_thread(job)
        return run

    # ---------- Подключение ----------
    server_url = ft.TextField(label="Адрес сервера", value=core.config["server_url"], expand=True)
    access_key = ft.TextField(label="Ключ доступа", value=core.config["access_key"],
                              password=True, can_reveal_password=True, expand=True)
    sync_status = ft.Text("отключено")

    def save_server(*_):
        core.update_config(server_url=server_url.value.strip(), access_key=access_key.value.strip())
        return "настройки сервера сохранены"

    def toggle_sync(*_):
        if syncer.running:
            syncer.stop()
            return "синхронизация остановлена"
        save_server()
        syncer.start()
        return "синхронизация запущена"

    connection_tab = ft.Column([
        ft.Row([server_url]),
        ft.Row([access_key]),
        ft.Row([ft.Button("Сохранить", icon=ft.Icons.SAVE, on_click=guarded(save_server)),
                ft.Button("Запуск / стоп", icon=ft.Icons.SYNC, on_click=guarded(toggle_sync)),
                sync_status]),
    ])

    # ---------- Лампы ----------
    lamps_list = ft.ListView(expand=True, spacing=6)
    add_ip = ft.TextField(label="IP лампы", width=220)

    def refresh_lamps():
        state = core.state()
        lamps_list.controls.clear()
        for lamp in state.lamps:
            status = "онлайн" if lamp.online else "офлайн" if lamp.online is False else "нет данных"
            lamps_list.controls.append(ft.Row([
                ft.Text(f"{lamp.ip} — {status}", expand=True),
                ft.IconButton(ft.Icons.POWER_SETTINGS_NEW, tooltip="Вкл/выкл",
                              on_click=guarded(lambda ip=lamp.ip: core.command(
                                  {"type": "toggle", "ip": ip}))),
                ft.IconButton(ft.Icons.UNDO, tooltip="Отменить",
                              on_click=guarded(lambda ip=lamp.ip: core.undo(ip))),
                ft.IconButton(ft.Icons.DELETE, tooltip="Удалить",
                              on_click=guarded(lambda ip=lamp.ip: core.remove(ip))),
            ]))
        page.update()

    def add_lamp(*_):
        core.add(add_ip.value)
        add_ip.value = ""
        return "лампа добавлена"

    lamps_tab = ft.Column([
        ft.Row([add_ip, ft.Button("Добавить", on_click=guarded(add_lamp)),
                ft.Button("Найти в сети", icon=ft.Icons.SEARCH,
                          on_click=in_background(lambda: f"найдено: {len(core.discover())}"))]),
        lamps_list,
    ], expand=True)

    # ---------- Режимы ----------
    modes_list = ft.ListView(expand=True, spacing=6)
    mode_lamp = ft.Dropdown(label="Лампа", width=220, options=[])

    def refresh_modes():
        state = core.state()
        mode_lamp.options = [ft.DropdownOption(key=lamp.ip, text=lamp.ip) for lamp in state.lamps]
        modes_list.controls.clear()
        for mode in state.modes:
            run_text = f"запущен на {mode['running_ip']}" if mode["running"] else "остановлен"
            error = f" · ошибка: {mode['last_error']}" if mode["last_error"] else ""
            name = mode["name"]
            modes_list.controls.append(ft.Row([
                ft.Text(f"{name} — {run_text}{error}", expand=True),
                ft.IconButton(ft.Icons.PLAY_ARROW, tooltip="Запуск",
                              on_click=guarded(lambda n=name: core.start_mode(n, mode_lamp.value))),
                ft.IconButton(ft.Icons.STOP, tooltip="Стоп",
                              on_click=guarded(lambda n=name: core.stop_mode(n))),
                ft.IconButton(ft.Icons.DELETE, tooltip="Удалить",
                              on_click=guarded(lambda n=name: core.delete_mode(n))),
            ]))
        page.update()

    modes_tab = ft.Column([ft.Row([mode_lamp]), modes_list], expand=True)

    # ---------- Настройка (Wi-Fi и LAN Control) ----------
    wifi_ip = ft.TextField(label="IP лампы", width=220)
    ssid = ft.TextField(label="Wi-Fi SSID", width=260)
    wifi_password = ft.TextField(label="Пароль Wi-Fi", password=True,
                                 can_reveal_password=True, width=260)
    lan_check = ft.Checkbox(label="Включить LAN Control", value=True)
    lan_ip = ft.TextField(label="IP лампы для LAN Control", width=220)
    token = ft.TextField(label="Токен (необязательно)", width=260)

    def wifi_job():
        result = connect_to_wifi(wifi_ip.value.strip(), ssid.value, wifi_password.value,
                                 enable_lan_control=lan_check.value)
        core.log(f"Wi-Fi: {result}")
        return str(result)

    def lan_job():
        result = enable_lan_control(lan_ip.value.strip(), token.value.strip() or None)
        core.log(f"LAN Control: {result}")
        return str(result)

    settings_tab = ft.Column([
        ft.Text("Подключение лампы к Wi-Fi", weight=ft.FontWeight.BOLD),
        ft.Row([wifi_ip, ssid]),
        ft.Row([wifi_password, lan_check]),
        ft.Button("Подключить к Wi-Fi", on_click=in_background(wifi_job)),
        ft.Divider(),
        ft.Text("LAN Control", weight=ft.FontWeight.BOLD),
        ft.Row([lan_ip, token]),
        ft.Button("Включить LAN Control", on_click=in_background(lan_job)),
    ], scroll=ft.ScrollMode.AUTO)

    # ---------- Журнал ----------
    log_view = ft.ListView(expand=True, spacing=2, auto_scroll=True)

    def refresh_log():
        log_view.controls = [ft.Text(line, selectable=True) for line in core.state().log]
        page.update()

    logs_tab = ft.Column([log_view], expand=True)

    tabs = ft.Tabs(
        selected_index=0,
        length=5,
        expand=True,
        content=ft.Column([
            ft.TabBar(tabs=[
                ft.Tab(label="Подключение"),
                ft.Tab(label="Лампы"),
                ft.Tab(label="Режимы"),
                ft.Tab(label="Настройка"),
                ft.Tab(label="Логи"),
            ]),
            ft.TabBarView(expand=True, controls=[
                connection_tab, lamps_tab, modes_tab, settings_tab, logs_tab,
            ]),
        ], expand=True),
        on_change=lambda e: refresh_all(),
    )

    def refresh_all():
        sync_status.value = ("подключено" if syncer.connected else "нет связи") if syncer.running \
            else "отключено"
        refresh_lamps()
        refresh_modes()
        refresh_log()

    page.add(tabs, msg)

    def ticker():
        while True:
            time.sleep(1)
            try:
                refresh_all()
            except Exception:
                return

    page.run_thread(ticker)
    refresh_all()


def run():
    ft.run(main)
