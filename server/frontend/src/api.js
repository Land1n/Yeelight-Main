import { useEffect, useState } from "react";

async function request(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return response.json();
}

export function getState() {
  return request("/api/state");
}

// Отправляет действие и ждёт результата агента (done/error).
export async function send(action) {
  const created = await request("/api/actions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(action),
  });
  for (;;) {
    const item = await request(`/api/actions/${created.id}`);
    if (item.status === "done") {
      return item.result;
    }
    if (item.status === "error") {
      throw new Error(item.result?.error || "Ошибка выполнения");
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
}

export function useManagerState() {
  const [state, setState] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let active = true;
    const tick = () =>
      getState()
        .then((data) => active && (setState(data), setError(null)))
        .catch((err) => active && setError(err.message));
    tick();
    const timer = setInterval(tick, 1500);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, []);

  return { state, error };
}
