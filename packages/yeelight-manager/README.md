# yeelight-manager

Локальный агент Yeelight. Работает рядом с лампами, выполняет типизированные
команды сервера и предоставляет Flet-интерфейс и loopback HTTP API для настройки
Wi-Fi и LAN Control.

## Установка и запуск

```powershell
.\.venv\Scripts\python.exe -m pip install -e packages\yeelight-logic
.\.venv\Scripts\python.exe -m pip install -e packages\yeelight-manager
.\.venv\Scripts\python.exe -m yeelight_manager
```

Или из корня репозитория:

```powershell
start-manager.bat
start-manager.bat --no-ui
start-manager.bat --pair <КОД>
start-manager.bat --status
```

Пакет зависит от `yeelight-logic`, `websockets`, `httpx`, FastAPI, uvicorn и
Flet. Менеджер не требует входящих сетевых портов: он сам подключается к серверу
по WebSocket.

## Спаривание

1. В веб-интерфейсе сервера откройте «Менеджеры» и создайте одноразовый код.
2. Выполните `start-manager.bat --pair <КОД>` или введите код в окне менеджера.
3. Сервер вернёт токен `ylm_...`; менеджер сохранит его в защищённом виде.
4. При следующем запуске агент подключится к `/api/v1/managers/ws` с заголовком
   `Authorization: Bearer ...`.

Код действует 10 минут и используется один раз. При удалении менеджера на
сервере сокет закрывается с кодом `4003`; при неверном токене — с `4401`.
Менеджер показывает эти состояния и не пытается бесконечно подключаться с
недействительным токеном.

## Состояние и токен

Домашний каталог:

- Windows: `%LOCALAPPDATA%\YeelightManager`;
- Linux: `$XDG_DATA_HOME/YeelightManager` или `~/.local/share/YeelightManager`;
- macOS: `~/Library/Application Support/YeelightManager`.

Файлы:

- `state.json` — состояние без токена;
- `bulbs.json` — известные IP-адреса;
- `token.bin` — токен: DPAPI на Windows, файл `0600` на Unix.

Переопределить каталог можно через `YEELIGHT_MANAGER_HOME`.

## Локальный API

API слушает только loopback (по умолчанию `127.0.0.1:8765`). Клиенты не из
loopback и запросы с не-loopback `Origin` отклоняются. Изменяющие запросы
требуют заголовок:

```http
X-Yeelight-Manager: 1
```

Провижининг дополнительно требует `"confirm": true`.

| Метод | Путь | Тело/назначение |
| --- | --- | --- |
| GET | `/api/health` | Проверка процесса. |
| GET | `/api/status` | Снимок состояния. |
| GET | `/api/lamps` | Кэш ламп. |
| POST | `/api/lamps/discover` | Поиск ламп. |
| POST | `/api/lamps` | `{"ip": "192.168.1.45"}` |
| DELETE | `/api/lamps/{ip}` | Удалить лампу. |
| POST | `/api/lamps/{ip}/command` | `{"action": "power", "params": {"state": "on"}}` |
| POST | `/api/provisioning/wifi` | `{"ip", "ssid", "password", "enable_lan_control", "confirm": true}` |
| POST | `/api/provisioning/lan-control` | `{"ip", "confirm": true}` |
| POST | `/api/pair` | `{"code": "..."}` |
| POST | `/api/unpair` | Удалить токен. |
| POST | `/api/reconnect` | Разбудить агент. |

Пример:

```powershell
curl -X POST http://127.0.0.1:8765/api/lamps/192.168.1.45/command `
  -H "X-Yeelight-Manager: 1" -H "Content-Type: application/json" `
  -d '{"action":"brightness","params":{"value":60}}'
```

Пароль Wi-Fi не сохраняется, не возвращается в ответе и не пишется в логи.
Успешный ответ miIO означает только доставку запроса.

## Конфигурация

| Переменная | По умолчанию |
| --- | --- |
| `YEELIGHT_SERVER_URL` | `http://127.0.0.1:8000` |
| `YEELIGHT_MANAGER_NAME` | имя компьютера |
| `YEELIGHT_MANAGER_HOME` | системный каталог |
| `YEELIGHT_MANAGER_LOCAL_API` | `true` |
| `YEELIGHT_MANAGER_LOCAL_HOST` | `127.0.0.1` |
| `YEELIGHT_MANAGER_LOCAL_PORT` | `8765` |
| `YEELIGHT_MANAGER_UI` | `true` |
| `YEELIGHT_MANAGER_POLL_SECONDS` | `30` |
| `YEELIGHT_MANAGER_DISCOVERY_TIMEOUT_SECONDS` | `2` |
| `YEELIGHT_MANAGER_COMMAND_TIMEOUT_SECONDS` | `30` |
| `YEELIGHT_MANAGER_VERIFY_TLS` | `true` |
| `YEELIGHT_MANAGER_LOG_LEVEL` | `INFO` |

## Безопасность

- Токен менеджера не хранится в открытом виде на Windows и не логируется.
- Локальный API не предназначен для доступа из сети; не меняйте
  `YEELIGHT_MANAGER_LOCAL_HOST` на `0.0.0.0` (такое значение отклоняется).
- Wi-Fi и LAN Control выполняются только после явного подтверждения.
- Менеджер не принимает произвольные командные строки от сервера: только
  типизированные действия из `yeelight-logic`.

## Проверки

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Обычные тесты используют fake-лампы и fake-сервер. Аппаратные и e2e-проверки
включаются переменными окружения, см. `tests/README.md`.
