# lamp

Библиотека управления лампами Yeelight по локальной сети. Без хранения состояния,
retry и ограничения частоты: это делает manager.

## Установка

```powershell
.\.venv\Scripts\pip install -e lamp
```

## API

| Что | Как |
| --- | --- |
| Поиск ламп | `lamp.network.discover(timeout=2)` |
| Лампа | `Lamp(ip)`: `state()`, `turn_on()`, `turn_off()`, `toggle()`, `set_brightness(1..100)`, `set_rgb(r, g, b)`, `set_hex("#rrggbb")`, `set_hsv(0..359, 0..100)`, `set_color_temp(1700..6500)`, `set_name(str)`, `set_default()` |
| Команды | `TurnOnCommand`, `SetRgbCommand`, ... Метод `execute()`, `undo()`, `to_dict()` |
| Из словаря | `Command.from_dict({"type": "set_rgb", "ip": ..., "r": 255, "g": 0, "b": 0})` |
| Wi-Fi и LAN Control | `lamp.network.connect_to_wifi(ip, ssid, password, enable_lan_control=False)`, `enable_lan_control(ip)` |

Ошибки связи: `LampError`. Неверные значения: `ValueError`.

## Примеры

`examples/01_discover.py` ... `examples/09_lan_control.py`. Запуск:
`.\.venv\Scripts\python lamp\examples\02_turn_on_off.py 192.168.1.45`

## Тесты

```powershell
.\.venv\Scripts\pytest lamp\tests
$env:YEELIGHT_TEST_IP="192.168.1.45"; .\.venv\Scripts\pytest lamp\tests -m hardware
```

Без `YEELIGHT_TEST_IP` тест на железе пропускается.
