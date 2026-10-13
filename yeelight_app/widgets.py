from __future__ import annotations

from collections.abc import Awaitable, Callable

import flet as ft


CommandHandlerFactory = Callable[
    [str],
    Callable[[ft.ControlEvent], Awaitable[None]],
]


def empty_bulbs_card() -> ft.Container:
    return ft.Container(
        content=ft.Column(
            [
                ft.Icon(ft.Icons.LIGHTBULB_OUTLINE, size=30, color="#91a0b3"),
                ft.Text(
                    "Пока нет ламп",
                    size=15,
                    weight=ft.FontWeight.BOLD,
                    text_align=ft.TextAlign.CENTER,
                ),
                ft.Text(
                    "Найдите лампы в сети или добавьте адрес командой add <IP>.",
                    size=12,
                    color="#91a0b3",
                    text_align=ft.TextAlign.CENTER,
                ),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=7,
        ),
        padding=18,
        bgcolor="#101722",
        border_radius=14,
    )


def bulb_card(
    address: str,
    command_handler: CommandHandlerFactory,
    online: bool | None = None,
) -> ft.Container:
    availability = {
        True: ("#b6e36b", "Есть ответ"),
        False: ("#ff6b6b", "Нет ответа"),
        None: ("#748197", "Проверяем связь…"),
    }
    status_color, status_text = availability[online]
    status_dot = ft.Container(
        width=8,
        height=8,
        bgcolor=status_color,
        border_radius=4,
    )
    status_label = ft.Text(status_text, size=11, color="#91a0b3")
    palette = (
        ("Красный", 255, 0, 0),
        ("Оранжевый", 255, 128, 0),
        ("Жёлтый", 255, 255, 0),
        ("Зелёный", 0, 200, 0),
        ("Голубой", 0, 200, 255),
        ("Синий", 0, 0, 255),
        ("Фиолетовый", 160, 32, 240),
        ("Розовый", 255, 64, 160),
        ("Белый", 255, 255, 255),
        ("Тёплый белый", 255, 180, 100),
    )
    menu_actions = [
        ("Включить", f"on {address}"),
        ("Выключить", f"off {address}"),
        ("Переключить", f"toggle {address}"),
        ("Статус", f"status {address}"),
        ("Удалить из списка", f"remove {address}"),
        *(
            (f"Яркость {value}%", f"brightness {address} {value}")
            for value in (10, 25, 50, 75, 100)
        ),
        *(
            (label, f"color {address} {red} {green} {blue}")
            for label, red, green, blue in palette
        ),
        *(
            (f"Температура {value} K", f"temp {address} {value}")
            for value in (2700, 4000, 5500, 6500)
        ),
    ]
    return ft.Container(
        content=ft.ResponsiveRow(
            [
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Container(
                                content=ft.Icon(
                                    ft.Icons.LIGHTBULB,
                                    color="#b6e36b",
                                    size=22,
                                ),
                                padding=10,
                                bgcolor="#263421",
                                border_radius=12,
                            ),
                            ft.Column(
                                [
                                    ft.Text(
                                        address,
                                        size=14,
                                        weight=ft.FontWeight.BOLD,
                                    ),
                                    ft.Row(
                                        [
                                            status_dot,
                                            status_label,
                                        ],
                                        spacing=6,
                                    ),
                                ],
                                spacing=3,
                                tight=True,
                            ),
                        ],
                        spacing=12,
                    ),
                    col={"xs": 12, "sm": 5, "md": 6},
                ),
                ft.Container(
                    content=ft.Row(
                        [
                            ft.PopupMenuButton(
                                content=ft.Text("Управление"),
                                items=[
                                    ft.PopupMenuItem(
                                        content=ft.Text(label),
                                        on_click=command_handler(command),
                                    )
                                    for label, command in menu_actions
                                ],
                            ),
                        ],
                        wrap=True,
                        spacing=7,
                    ),
                    col={"xs": 12, "sm": 7, "md": 6},
                ),
            ],
            run_spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=14,
        bgcolor="#101722",
        border=ft.Border.all(1, "#253244"),
        border_radius=14,
        data={
            "ip": address,
            "status_dot": status_dot,
            "status_label": status_label,
        },
    )
