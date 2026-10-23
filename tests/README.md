# Проверки

Обычные тесты не требуют ламп, сети и запущенного сервера. Они используют
поддельные лампы, менеджер и сервер, а базу данных SQLite располагают во
временных каталогах.

## Запуск

Из корня репозитория (после установки трёх пакетов в editable-режиме):

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Запуск одного набора:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_logic_actions tests.test_server_auth -v
```

## Наборы тестов

| Файл | Что проверяется |
| --- | --- |
| `tests/test_logic_actions.py` | Типизированные действия, валидация параметров, fake-лампы, поворот при ошибке сокета. |
| `tests/test_logic_controller.py` | Контроллер, список ламп, discovery, текстовые команды, хранение, atomic JSON. |
| `tests/test_manager_settings.py` | Настройки менеджера, URL сервера, WebSocket-адрес. |
| `tests/test_manager_secrets.py` | Токен менеджера: DPAPI (Windows) / файл 0600 (Unix), битые форматы. |
| `tests/test_manager_runtime.py` | Кэш состояний ламп, действия, мониторинг, локальная провижининг. |
| `tests/test_manager_local_api.py` | Loopback API менеджера: лампы, команды, Wi-Fi/LAN Control, пароль, спаривание. |
| `tests/test_manager_agent.py` | WebSocket-агент: обработка команд и кэш результатов. |
| `tests/test_manager_service.py` | Жизненный цикл менеджера, токен, снимок состояния. |
| `tests/test_server_auth.py` | Вход, сессия, CSRF, cookie, блокировка неверного пароля. |
| `tests/test_server_pairing.py` | Одноразовые коды, спаривание менеджера, конфликты имён. |
| `tests/test_server_commands.py` | Типизированные команды, состояния, офлайн-менеджер, валидация. |
| `tests/test_server_modes.py` | Режимы CRUD, запуск/остановка, импорт старых режимов. |
| `tests/test_server_storage.py` | База SQLite: пользователи, сессии, менеджеры, лампы, команды, аудит. |
| `tests/test_server_diagnostics.py` | Настройки, диагностика, аудит через API. |
| `tests/test_server_ws.py` | WebSocket менеджера: hello, лампы, результаты команд. |

## Аппаратные и сквозные проверки (опционально)

Включаются только переменными окружения. По умолчанию пропускаются.

- `YEELIGHT_TEST_LAMP_IP=<IP>` — проверка против реальной лампы: статус,
  яркость, переключение питания. Лампа должна быть в сети и доступна по TCP 55443.
- `YEELIGHT_TEST_E2E=1` — сквозная проверка: запускается настоящий сервер,
  создаётся администратор, код спаривания и менеджер, проверяется API.

Пример:

```powershell
$env:YEELIGHT_TEST_LAMP_IP="192.168.1.45"
.\.venv\Scripts\python.exe -m unittest tests.test_e2e -v
```

Для e2e нужен `.venv` с установленными пакетами и `.env` не обязателен —
пароль администратора передаётся через переменную окружения.
