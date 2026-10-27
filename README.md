# Yeelight

Управление лампами Yeelight по локальной сети: десктоп-менеджер, сервер с веб-сайтом
и библиотека для работы с лампой.

## Состав

```
lamp/      [submodule] библиотека управления лампой (yeelight, python-miio)
protocol/  [submodule] общие модели обмена manager ↔ server (pydantic)
manager/   [submodule] десктоп-приложение на Flet, опрашивает сервер
server/    [submodule] FastAPI + SQLite: очередь команд, API и сайт (React)
```

- **manager** работает и без сервера (локальное управление). Сам опрашивает сервер
  (`POST /agent/poll`), поэтому проброс портов не нужен.
- **server** хранит очередь команд и последний снимок состояния manager, раздаёт сайт.
- Доступ к серверу защищён ключом `ACCESS_KEY`: manager передаёт его в заголовке
  `X-Access-Key`, сайт без авторизации.
- Настройка Wi-Fi и LAN Control доступна только в manager.

## Клонирование

```powershell
git clone --recurse-submodules https://github.com/Land1n/Yeelight-Main.git
# или, если репозиторий уже клонирован:
git submodule update --init
```

## Окружение

Нужны Python 3.11+ (сервер) и Node.js 20+ (сборка сайта).

```powershell
py -m venv .venv
.\.venv\Scripts\pip install -e lamp -e protocol -e manager -e server pytest
```

Зависимости между сабмодулями ставятся локально, PyPI не используется.

## Тесты

```powershell
.\.venv\Scripts\python -P -m pytest lamp\tests
.\.venv\Scripts\python -P -m pytest manager\tests
.\.venv\Scripts\python -P -m pytest server\tests
```

Флаг `-P` нужен, потому что корневая папка `lamp/` перекрывает установленный пакет.

Тест на реальной лампе пропускается без переменной окружения:

```powershell
$env:YEELIGHT_TEST_IP="192.168.1.45"; .\.venv\Scripts\python -P -m pytest lamp\tests -m hardware
```

## Сайт (фронтенд)

```powershell
npm --prefix server\frontend install
npm --prefix server\frontend run build      # сборка в server\frontend\dist
npm --prefix server\frontend run dev        # режим разработки, /api проксируется на :8000
```

## Сервер

```powershell
Copy-Item server\.env.example server\.env   # затем задать ACCESS_KEY
.\.venv\Scripts\python -P -m server         # http://127.0.0.1:8000
```

Переменные в `server/.env`: `ACCESS_KEY` (обязателен), `HOST` (по умолчанию
`127.0.0.1`), `PORT` (`8000`), `DB_PATH` (`server.db`).

Сайт открывается по адресу `http://127.0.0.1:8000`. Перед этим соберите фронтенд
(см. раздел «Сайт»).

## Manager

```powershell
.\.venv\Scripts\python -P -m manager
```

При первом запуске `modes.json` создаётся из `manager/default_modes.json`.
Настройки подключения к серверу (URL и `access_key`) задаются в `config.json` рядом
с приложением.

Сборка exe:

```powershell
.\.venv\Scripts\flet pack manager\manager\__main__.py --name YeelightManager --add-data "manager\default_modes.json;."
```

## Библиотека lamp

```python
from lamp import Lamp, TurnOnCommand, Command

bulb = Lamp("192.168.1.45")
TurnOnCommand(bulb).execute()
cmd = Command.from_dict({"type": "set_rgb", "ip": "192.168.1.45", "r": 255, "g": 0, "b": 0})
cmd.execute()
cmd.undo()
```

Примеры: `lamp\examples\`. Подробности API: `lamp/README.md`.

## Проверки

Тесты выполнены с фейковой лампой. Проверка на реальной лампе через
`YEELIGHT_TEST_IP` и Wi-Fi/LAN Control на железе не выполнялась.
