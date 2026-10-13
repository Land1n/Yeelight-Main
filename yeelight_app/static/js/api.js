const REQUEST_TIMEOUT_MS = 35_000;

export function createApi(serverInput, tokenInput) {
  function apiUrl(path) {
    const base = serverInput.value.trim().replace(/\/+$/, "");
    let parsed;
    try {
      parsed = new URL(base);
    } catch {
      parsed = null;
    }
    if (
      !parsed ||
      !["http:", "https:"].includes(parsed.protocol) ||
      parsed.username ||
      parsed.password ||
      parsed.pathname !== "/" ||
      parsed.search ||
      parsed.hash
    ) {
      throw new Error("Укажите корректный адрес сервера (http:// или https://)");
    }
    return `${parsed.origin}${path}`;
  }

  async function request(path, options = {}) {
    const url = apiUrl(path);
    const headers = new Headers(options.headers || {});
    if (tokenInput.value) headers.set("X-API-Token", tokenInput.value);
    if (options.body) headers.set("Content-Type", "application/json");

    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
    let response;
    try {
      response = await fetch(url, {
        ...options,
        headers,
        signal: controller.signal,
      });
    } catch (error) {
      window.clearTimeout(timeout);
      if (error.name === "AbortError") {
        throw new Error("Превышено время ожидания ответа сервера.");
      }
      throw new Error(`Не удалось связаться с сервером: ${error.message}`);
    }

    let body;
    try {
      body = await response.json();
    } catch {
      if (controller.signal.aborted) {
        throw new Error("Превышено время ожидания ответа сервера.");
      }
      if (response.ok) {
        throw new Error(`Сервер вернул некорректный ответ (HTTP ${response.status})`);
      }
      body = {};
    } finally {
      window.clearTimeout(timeout);
    }
    if (!body || typeof body !== "object" || Array.isArray(body)) {
      if (response.ok) {
        throw new Error(`Сервер вернул некорректный ответ (HTTP ${response.status})`);
      }
      body = {};
    }
    if (!response.ok) {
      const error = new Error(formatError(body.detail) || `Ошибка HTTP ${response.status}`);
      error.httpStatus = response.status;
      throw error;
    }
    return body;
  }

  return request;
}

function formatError(detail) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map((item) => {
      if (typeof item === "string") return item;
      const location = Array.isArray(item.loc) ? `${item.loc.join(".")}: ` : "";
      return `${location}${item.msg || JSON.stringify(item)}`;
    }).join("; ");
  }
  if (detail && typeof detail === "object") return detail.message || JSON.stringify(detail);
  return "";
}
