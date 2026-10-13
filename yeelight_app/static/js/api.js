export function createApi(serverInput, tokenInput) {
  function apiUrl(path) {
    const base = serverInput.value.trim().replace(/\/+$/, "");
    if (!/^https?:\/\/[^/]+$/i.test(base)) {
      throw new Error("Укажите корректный адрес сервера (http:// или https://)");
    }
    return `${base}${path}`;
  }

  async function request(path, options = {}) {
    const headers = new Headers(options.headers || {});
    headers.set("X-API-Token", tokenInput.value);
    if (options.body) headers.set("Content-Type", "application/json");

    let response;
    try {
      response = await fetch(apiUrl(path), { ...options, headers });
    } catch (error) {
      throw new Error(`Не удалось связаться с сервером: ${error.message}`);
    }

    const body = await response.json().catch(() => ({}));
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
