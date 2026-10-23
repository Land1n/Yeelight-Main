# yeelight-logic

Независимая библиотека для управления лампами Yeelight по LAN-протоколу. Пакет
не зависит от FastAPI, Flet и серверных концепций, поэтому его можно использовать
в скриптах, менеджере и тестах без запуска инфраструктуры.

## Установка

```powershell
.\.venv\Scripts\python.exe -m pip install -e packages\yeelight-logic
```

Зависимости: `yeelight` для SSDP/LAN-адаптера и `cryptography` для miIO.

## Быстрый пример

```python
from yeelight_logic import Bulb

with Bulb("192.168.1.45") as bulb:
    bulb.turn_on()
    bulb.set_brightness(60)
    bulb.set_rgb(51, 170, 255)
    bulb.set_color_temperature(4000)
    print(bulb.get_status())
    bulb.turn_off()
```

`Bulb` проверяет IP, яркость (1–100), RGB (0–255) и температуру (1700–6500 K).
Исключения имеют стабильные коды: `command_error`, `device_error`,
`connection_error`, `storage_error`, `discovery_error`,
`provisioning_error`, `unsupported_model`.

## Контроллер и несколько ламп

```python
from yeelight_logic import YeelightController

controller = YeelightController(
    ["192.168.1.45", "192.168.1.46"],
    storage_path="data/bulbs.json",
)
try:
    print(controller.known_bulbs())
    print(controller.discover())
finally:
    controller.close()
```

Контроллер создаёт один переиспользуемый адаптер на IP, сериализует доступ к
сокету и выдерживает интервал между командами одной лампы (прошивка ограничивает
примерно 60 команд в минуту). Список ламп сохраняется атомарно.

## Типизированные действия

`execute_action` — общий dispatcher для менеджера и совместимого фасада. Он
принимает только закрытый набор действий:

`power`, `brightness`, `color`, `color_temperature`, `status`, `discover`,
`add`, `remove`, `list`.

```python
from yeelight_logic import execute_action, validate_action_params

params = validate_action_params("color", {"hex": "#33AAFF"})
result = execute_action(controller, "color", address="192.168.1.45", params=params)
print(result.ok, result.message, result.data)
```

Провижининг (Wi-Fi/LAN Control) намеренно отсутствует в `REMOTE_ACTIONS`: эти
операции должны запускаться только локально с подтверждением.

## Команды

Классы команд находятся в `yeelight_logic.commands`:

- `TurnOnCommand`, `TurnOffCommand`, `ToggleCommand`, `GetStatusCommand`;
- `SetBrightnessCommand`, `SetColorCommand`, `SetColorTemperatureCommand`;
- `AddBulbCommand`, `RemoveBulbCommand`, `ListBulbsCommand`,
  `DiscoverBulbsCommand`;
- `ConnectWifiCommand`, `EnableLanControlCommand` (требуют `confirmed=True`).

Все команды возвращают `CommandResult(ok, message, data, error_code)`.

## Discovery

```python
from yeelight_logic import discover_bulbs

for item in discover_bulbs(timeout=2.0):
    print(item)
```

Discovery использует SSDP `239.255.255.250:1982`. В контроллере найденные IP
автоматически добавляются в список известных ламп.

## Wi-Fi и LAN Control

```python
from yeelight_logic import connect_to_wifi, enable_lan_control

result = connect_to_wifi(
    "192.168.13.1",
    "HomeWiFi",
    "secret-password",
    enable_lan_control=True,
)
print(result.wifi_status, result.lan_control_status)

lan = enable_lan_control("192.168.1.45")
print(lan.lan_control_status, lan.lan_control_message)
```

Особенности:

- поддерживается только модель `yeelink.light.color1`;
- принимаются только private IPv4-адреса;
- пароль Wi-Fi не сохраняется и не логируется;
- `responded_unverified`/`sent_unconfirmed` не означают успешное подключение;
- Wi-Fi и LAN Control отчитываются раздельно: ошибка LAN Control не отменяет
  отправку настроек Wi-Fi.

## Публичный API

Основные экспорты:

```python
from yeelight_logic import (
    Bulb, YeelightController, CommandResult, ProvisioningResult,
    execute_action, validate_action_params, REMOTE_ACTIONS,
    discover_bulbs, connect_to_wifi, enable_lan_control,
)
```

## Проверки

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Тесты библиотеки используют fake-адаптеры и не требуют ламп. Аппаратная
проверка включается через `YEELIGHT_TEST_LAMP_IP`, см. `tests/README.md`.
