const REQUEST_TIMEOUT_MS = 40_000;
const MAX_LOG_ENTRIES = 150;

let csrfToken = "";

export function $(selector, root = document) {
  return root.querySelector(selector);
}

export function $$(selector, root = document) {
  return Array.from(root.querySelectorAll(selector));
}

export function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[character]);
}

export function formatError(detail) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((item) => {
      if (typeof item === "string") return item;
      const location = Array.isArray(item.loc) ? `${item.loc.join(".")}: ` : "";
      return `${location}${item.msg || JSON.stringify(item)}`;
    }).join("; ");
  }
  if (detail && typeof detail === "object") {
    return detail.message || JSON.stringify(detail);
  }
  return "";
}

export function formatTime(timestamp) {
  if (!timestamp) return "—";
  const date = new Date(Number(timestamp) * 1000);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function setConnection(ok, message) {
  const dot = $("#status-dot");
  const text = $("#status-text");
  if (dot) dot.className = `dot ${ok ? "ok" : "error"}`;
  if (text) text.textContent = message;
}

export function log(text, kind = "") {
  const output = $("#output");
  if (!output) return;
  const line = document.createElement("div");
  line.className = `entry ${kind}`;
  line.textContent = text;
  output.append(line);
  while (output.children.length > MAX_LOG_ENTRIES) output.firstElementChild.remove();
  output.scrollTop = output.scrollHeight;
}

export function logJson(value) {
  log(JSON.stringify(value, null, 2));
}

export function empty(message) {
  const block = document.createElement("div");
  block.className = "empty";
  block.textContent = message;
  return block;
}

async function parseBody(response) {
  const text = await response.text();
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch {
    return { detail: `Некорректный ответ сервера (HTTP ${response.status})` };
  }
}

export async function api(path, options = {}) {
  const { redirectOn401 = true, timeout = REQUEST_TIMEOUT_MS, ...fetchOptions } = options;
  const method = (fetchOptions.method || "GET").toUpperCase();
  const headers = new Headers(fetchOptions.headers || {});
  if (fetchOptions.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (!["GET", "HEAD"].includes(method) && csrfToken) {
    headers.set("X-CSRF-Token", csrfToken);
  }

  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeout);
  let response;
  try {
    response = await fetch(path, {
      ...fetchOptions,
      method,
      headers,
      credentials: "same-origin",
      signal: controller.signal,
    });
  } catch (error) {
    window.clearTimeout(timer);
    if (error.name === "AbortError") {
      throw new Error("Превышено время ожидания ответа сервера.");
    }
    throw new Error(`Не удалось связаться с сервером: ${error.message}`);
  }

  let body;
  try {
    body = await parseBody(response);
  } finally {
    window.clearTimeout(timer);
  }

  if (response.status === 401 && redirectOn401) {
    const next = encodeURIComponent(window.location.pathname + window.location.search);
    window.location.assign(`/login?next=${next}`);
    throw new Error("Сессия истекла. Войдите снова.");
  }
  if (!response.ok) {
    const error = new Error(formatError(body.detail) || `Ошибка HTTP ${response.status}`);
    error.status = response.status;
    error.payload = body.detail;
    throw error;
  }
  return body;
}

export async function loadManagers() {
  const data = await api("/api/v1/managers");
  return data.managers || [];
}

export function managerLabel(manager) {
  return `${manager.name}${manager.online ? "" : " · офлайн"}`;
}

export function fillManagerSelect(select, managers, { allowEmpty = true } = {}) {
  if (!select) return;
  const previous = select.value;
  select.replaceChildren();
  if (allowEmpty) {
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = managers.length ? "Выберите менеджер" : "Нет менеджеров";
    select.append(placeholder);
  }
  for (const manager of managers) {
    const option = document.createElement("option");
    option.value = manager.id;
    option.textContent = managerLabel(manager);
    select.append(option);
  }
  if (managers.some((manager) => manager.id === previous)) {
    select.value = previous;
  } else if (!allowEmpty && managers.length) {
    select.value = managers[0].id;
  }
}

export function selectedManager(managers, select) {
  if (!select || !select.value) return null;
  return managers.find((manager) => manager.id === select.value) || null;
}

export async function loadManagerLamps(managerId) {
  if (!managerId) return [];
  const data = await api(`/api/v1/managers/${encodeURIComponent(managerId)}/lamps`);
  return data.lamps || [];
}

export async function loadAllLamps() {
  const data = await api("/api/v1/lamps");
  return data.lamps || [];
}

export async function runCommand(managerId, action, ip, params = {}, options = {}) {
  const body = {
    manager_id: managerId,
    action,
    params,
    wait: options.wait !== false,
  };
  if (ip) body.ip = ip;
  if (options.timeoutSeconds) body.timeout_seconds = options.timeoutSeconds;
  try {
    return await api("/api/v1/commands", {
      method: "POST",
      body: JSON.stringify(body),
      timeout: options.requestTimeout,
    });
  } catch (error) {
    if (error.payload && error.payload.command) {
      error.command = error.payload.command;
    }
    throw error;
  }
}

export function commandSummary(command) {
  if (!command) return "—";
  const parts = [command.action];
  if (command.ip) parts.push(command.ip);
  const params = command.params || {};
  if (params.state) parts.push(params.state);
  if (params.value !== undefined) parts.push(String(params.value));
  if (Array.isArray(params.rgb)) parts.push(params.rgb.join(","));
  return parts.join(" ");
}

export function commandStatus(command) {
  return command?.status || "unknown";
}

export async function startPage({ ready, tick, intervalMs = 5000 } = {}) {
  const logout = $("#logout");
  if (logout) {
    logout.addEventListener("click", async () => {
      logout.disabled = true;
      try {
        await api("/api/v1/auth/logout", { method: "POST", redirectOn401: false });
      } catch {
        // The cookie may already be gone; the redirect below is what matters.
      }
      window.location.assign("/login");
    });
  }

  try {
    const me = await api("/api/v1/auth/me", { redirectOn401: false });
    csrfToken = me.csrf_token;
    setConnection(true, `Сервер доступен · ${me.username}`);
  } catch (error) {
    if (error.status === 401) {
      const next = encodeURIComponent(window.location.pathname);
      window.location.assign(`/login?next=${next}`);
      return;
    }
    setConnection(false, "Нет подключения");
    log(error.message, "error");
  }

  if (ready) {
    try {
      await ready();
    } catch (error) {
      setConnection(error.status !== undefined, error.status !== undefined ? "Ошибка запроса" : "Нет подключения");
      log(error.message, "error");
    }
  }

  if (tick) {
    window.setInterval(async () => {
      try {
        await tick();
        setConnection(true, "Сервер доступен");
      } catch (error) {
        setConnection(error.status !== undefined, error.status !== undefined ? "Ошибка запроса" : "Нет подключения");
      }
    }, intervalMs);
  }
}

export function bindSubmit(form, handler) {
  if (!form) return;
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      await handler(event);
    } catch (error) {
      log(error.message, "error");
    }
  });
}
