import { createApi } from "./api.js";

const TOKEN_KEY = "yeelight-api-token";
const SERVER_KEY = "yeelight-server-url";
const POLL_INTERVAL_MS = 5000;
const MAX_LOG_ENTRIES = 100;

export function $(selector, root = document) {
  return root.querySelector(selector);
}

export function empty(message) {
  const block = document.createElement("div");
  block.className = "empty";
  block.textContent = message;
  return block;
}

export function startPage({ panel = "#token-panel", create, ready, tick, unauthorized }) {
  const tokenPanel = panel ? $(panel) : null;
  const tokenInput = $("#api-token");
  const serverInput = $("#server-url");
  const statusDot = $("#status-dot");
  const statusText = $("#status-text");
  const reconnectButton = $("#reconnect");
  const output = $("#output");
  let storageWarned = false;
  let authorized = false;
  let busy = false;

  function warnStorage() {
    if (storageWarned) return;
    storageWarned = true;
    log(
      "Браузер не разрешил сохранить токен для этой вкладки; введите его снова после перезагрузки.",
      "error",
    );
  }

  function recall(key) {
    try {
      return sessionStorage.getItem(key) || "";
    } catch {
      warnStorage();
      return "";
    }
  }

  function remember(key, value) {
    try {
      sessionStorage.setItem(key, value);
    } catch {
      warnStorage();
    }
  }

  function log(text, kind = "") {
    if (!output) return;
    const line = document.createElement("div");
    line.className = `entry ${kind}`;
    line.textContent = text;
    output.append(line);
    while (output.children.length > MAX_LOG_ENTRIES) output.firstElementChild.remove();
    output.scrollTop = output.scrollHeight;
  }

  function setConnection(ok, message) {
    if (statusDot) statusDot.className = `dot ${ok ? "ok" : "error"}`;
    if (statusText) statusText.textContent = message;
  }

  function showPanel(show) {
    if (tokenPanel) tokenPanel.hidden = !show;
  }

  if (serverInput) serverInput.value = recall(SERVER_KEY) || window.location.origin;
  if (tokenInput) tokenInput.value = recall(TOKEN_KEY);
  if (serverInput) {
    serverInput.addEventListener("input", () => remember(SERVER_KEY, serverInput.value));
  }
  if (tokenInput) {
    tokenInput.addEventListener("input", () => remember(TOKEN_KEY, tokenInput.value));
  }

  const apiRequest = createApi(
    serverInput || { value: window.location.origin },
    tokenInput || { value: "" },
  );

  const context = {
    $,
    request: apiRequest,
    log,
    setConnection,
    get authorized() {
      return authorized;
    },
    get busy() {
      return busy;
    },
    setBusy(value) {
      busy = Boolean(value);
    },
  };

  async function connect() {
    if (!tokenInput) return;
    if (reconnectButton) {
      reconnectButton.disabled = true;
      reconnectButton.textContent = "Подключение…";
    }
    setConnection(false, "Подключаемся к серверу…");
    try {
      if (!tokenInput.value.trim()) {
        authorized = false;
        setConnection(true, "Нужен API-токен");
        showPanel(true);
        if (unauthorized) await unauthorized(context, "Введите YEELIGHT_API_TOKEN из файла .env.");
        return;
      }
      await apiRequest("/api/health");
      authorized = true;
      setConnection(true, "Сервер подключён");
      showPanel(false);
      if (ready) await ready(context);
    } catch (error) {
      authorized = false;
      const invalidToken = error.httpStatus === 401;
      setConnection(!invalidToken, invalidToken ? "Неверный API-токен" : "Нет подключения");
      showPanel(true);
      log(error.message, "error");
      if (unauthorized) {
        await unauthorized(
          context,
          invalidToken
            ? "Неверный API-токен: проверьте YEELIGHT_API_TOKEN в .env."
            : error.message,
        );
      }
    } finally {
      if (reconnectButton) {
        reconnectButton.disabled = false;
        reconnectButton.textContent = "Переподключиться к серверу";
      }
    }
  }

  if (reconnectButton) {
    reconnectButton.addEventListener("click", connect);
    tokenInput.addEventListener("keydown", (event) => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      tokenInput.blur();
      connect();
    });
    tokenInput.addEventListener("change", connect);
  }

  create?.(context);
  connect();

  if (tick) {
    window.setInterval(() => {
      if (busy || !authorized) return;
      Promise.resolve(tick(context)).catch((error) => log(`Автообновление: ${error.message}`, "error"));
    }, POLL_INTERVAL_MS);
  }

  return context;
}

export async function runCommand(context, text) {
  const command = text.trim();
  if (!command || context.busy) return null;
  context.setBusy(true);
  context.log(`> ${command}`, "command");
  try {
    const data = await context.request("/api/commands", {
      method: "POST",
      body: JSON.stringify({ command }),
    });
    context.log(JSON.stringify(data.result, null, 2));
    context.setConnection(true, "Сервер подключён");
    return data;
  } catch (error) {
    context.log(`Ошибка: ${error.message}`, "error");
    context.setConnection(
      error.httpStatus !== undefined,
      error.httpStatus !== undefined ? "Сервер доступен • ошибка запроса" : "Нет подключения",
    );
    return null;
  } finally {
    context.setBusy(false);
  }
}
