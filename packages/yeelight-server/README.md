# yeelight-server

Веб-сервер и ретранслятор команд. Принимает запросы от браузера, хранит
пользователей, менеджеры, лампы, команды и режимы в SQLite, а выполнение команд
передаёт подключённому менеджеру по исходящему WebSocket. Сервер не открывает
соединений с лампами и не содержит маршрутов настройки Wi-Fi.

## Установка и запуск

```powershell
.\.venv\Scripts\python.exe -m pip install -e packages\yeelight-logic
.\.venv\Scripts\python.exe -m pip install -e packages\yeelight-server
.\.venv\Scripts\python.exe -m yeelight_server
```

Или из корня репозитория:

```powershell
start-server.bat
```

По умолчанию сервер слушает `http://127.0.0.1:8000`. Перед первым запуском
задайте `YEELIGHT_SERVER_ADMIN_PASSWORD` (не менее 8 символов). После создания
первого пользователя значение из `.env` не используется: хранится scrypt-хеш.

```powershell
.\.venv\Scripts\python.exe -m yeelight_server --host 127.0.0.1 --port 8000
.\.venv\Scripts\python.exe -m yeelight_server --set-password
```

## Аутентификация

- Человек входит через `POST /api/v1/auth/login`; сервер устанавливает
  непрозрачную `HttpOnly` cookie `yl_session` с `SameSite=Lax`.
- Все изменяющие запросы требуют заголовок `X-CSRF-Token` со значением из
  ответа входа или `GET /api/v1/auth/me`.
- Пароли хешируются scrypt. Сессии хранятся в SQLite и удаляются по истечении
  TTL.
- Менеджеры аутентифицируются отдельно: одноразовый код обменивается на токен
  `ylm_...`; на сервере хранится только SHA-256 хеш токена.
- Коды спаривания живут 10 минут и используются один раз.

## Спаривание менеджера

1. `POST /api/v1/managers/pairing-codes` создаёт код.
2. Менеджер вызывает `POST /api/v1/managers/pair` с кодом, именем и версией.
3. Сервер возвращает токен, `ws_path` и интервал heartbeat.
4. Менеджер подключается к `/api/v1/managers/ws` с
   `Authorization: Bearer <токен>`.
5. После подключения сервер отправляет `hello`, менеджер — `hello` со списком
   ламп. Далее идут `heartbeat`, `lamps` и `command_result`.

Сервер не инициирует входящие соединения к менеджеру. Если менеджер отключился,
незавершённые команды получают статус `manager_unavailable`; сервер не выдаёт их
за выполненные.

## Команды

`POST /api/v1/commands` принимает только типизированные действия:

`power`, `brightness`, `color`, `color_temperature`, `status`, `discover`,
`add`, `remove`, `list`.

Параметры проверяются общей библиотекой `yeelight-logic`. Произвольные строки,
shell-подобные команды и провижининг отклоняются. Для действий с лампой IP
должен быть известен менеджеру. Ответ содержит команду и её состояние:
`pending`, `delivered`, `completed`, `failed`, `timed_out`,
`manager_unavailable` или `cancelled`.

При `wait: true` сервер ждёт результат не дольше
`YEELIGHT_SERVER_MAX_COMMAND_WAIT_SECONDS`. При `wait: false` возвращается `202`
и команду можно опросить через `GET /api/v1/commands/{id}`.

Идемпотентность: заголовок `Idempotency-Key` (или поле `idempotency_key`)
возвращает существующую команду вместо повторной доставки.

## Режимы

`/api/v1/modes` поддерживает CRUD, запуск и остановку. Режим состоит из шагов
`on`, `off`, `toggle`, `status`, `brightness`, `color`, `temp` и задержки.
Сервер выполняет цикл, передавая каждый шаг менеджеру; после 10 ошибок подряд
режим останавливается и сохраняет `last_error`.

Старый `data/modes.json` импортируется один раз, если в базе ещё нет режимов.
Факт импорта фиксируется в таблице `metadata`.

## Маршруты

Страницы: `/`, `/bulbs`, `/modes`, `/console`, `/setup`, `/help`, `/login`.

Публичные:

- `GET /api/health`
- `POST /api/v1/auth/login`
- `POST /api/v1/managers/pair`

Защищённые (cookie + CSRF для изменений):

- `GET /api/v1/auth/me`, `POST /api/v1/auth/logout`
- `POST /api/v1/managers/pairing-codes`, `GET /api/v1/managers`,
  `DELETE /api/v1/managers/{id}`, `GET /api/v1/managers/{id}/lamps`
- `GET /api/v1/lamps`
- `POST/GET /api/v1/commands`, `GET /api/v1/commands/{id}`
- `GET/POST/DELETE /api/v1/modes`, `POST /api/v1/modes/{id}/start|stop`
- `GET /api/v1/diagnostics`, `GET /api/v1/audit`, `GET /api/v1/settings`

WebSocket менеджера: `/api/v1/managers/ws`.

## Настройки

| Переменная | По умолчанию |
| --- | --- |
| `YEELIGHT_SERVER_HOST` | `127.0.0.1` |
| `YEELIGHT_SERVER_PORT` | `8000` |
| `YEELIGHT_SERVER_DB` | `data/server.db` |
| `YEELIGHT_SERVER_ADMIN_USER` | `admin` |
| `YEELIGHT_SERVER_ADMIN_PASSWORD` | пусто |
| `YEELIGHT_SERVER_SESSION_TTL_SECONDS` | `43200` |
| `YEELIGHT_SERVER_SECURE_COOKIES` | `false` |
| `YEELIGHT_SERVER_TLS_CERT` / `YEELIGHT_SERVER_TLS_KEY` | пусто |
| `YEELIGHT_SERVER_COMMAND_TIMEOUT_SECONDS` | `15` |
| `YEELIGHT_SERVER_MAX_COMMAND_WAIT_SECONDS` | `30` |
| `YEELIGHT_SERVER_HEARTBEAT_SECONDS` | `20` |
| `YEELIGHT_SERVER_MANAGER_GRACE_SECONDS` | `45` |
| `YEELIGHT_SERVER_LEGACY_MODES_FILE` | `data/modes.json` |

Относительные пути считаются от текущего каталога. Запускайте сервер из корня
репозитория либо задавайте абсолютные пути.

## Безопасность

- Ограничение тела запроса 256 КиБ, security headers, `no-store`.
- Rate limit входа, спаривания и команд.
- Forwarded-заголовки не используются для определения IP клиента: сервер не
  доверяет reverse proxy по умолчанию.
- Wi-Fi-пароль не принимается сервером и не хранится.
- Аудит содержит действия, результат, IP и идентификаторы, но не секреты.
- Для доступа из LAN используйте HTTPS (TLS или reverse proxy) и
  `YEELIGHT_SERVER_SECURE_COOKIES=true`. Не публикуйте сервер в интернет.

## Проверки

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Тесты сервера работают с временной SQLite и fake-менеджером. Аппаратные и e2e
проверки включаются переменными окружения, см. `tests/README.md`.
