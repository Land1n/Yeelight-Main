import {
  $,
  api,
  empty,
  escapeHtml,
  formatTime,
  log,
  startPage,
} from "./app.js";

async function loadManagers() {
  const data = await api("/api/v1/managers");
  const managers = data.managers || [];
  const list = $("#manager-list");
  list.replaceChildren();
  if (!managers.length) {
    list.append(empty("Подключённых менеджеров нет. Создайте код выше."));
    return;
  }
  for (const manager of managers) {
    const card = document.createElement("div");
    card.className = "manager-card";
    card.innerHTML = `
      <div class="manager-info">
        <div class="manager-name">${escapeHtml(manager.name)}</div>
        <div class="manager-meta">ID: ${escapeHtml(manager.id)} · версия: ${escapeHtml(manager.version || "неизвестна")} · создан: ${escapeHtml(formatTime(manager.created_at))} · последняя связь: ${escapeHtml(formatTime(manager.last_seen_at))}</div>
      </div>
      <div class="manager-actions">
        <span class="status-badge ${manager.online ? "ok" : "bad"}">${manager.online ? "онлайн" : "офлайн"}</span>
        <button type="button" class="danger" data-delete="${escapeHtml(manager.id)}">Удалить</button>
      </div>`;
    list.append(card);
  }
}

async function loadDiagnostics() {
  const data = await api("/api/v1/diagnostics");
  $("#diagnostics").textContent = JSON.stringify({
    status: data.status,
    version: data.version,
    uptime_seconds: data.uptime_seconds,
    managers: data.managers,
    lamps: data.lamps,
    modes: data.modes,
    commands: data.commands,
    settings: data.settings,
  }, null, 2);
  const events = data.recent_audit || [];
  const tbody = $("#audit-list");
  tbody.replaceChildren();
  if (!events.length) {
    const row = document.createElement("tr");
    row.innerHTML = '<td colspan="4" class="empty">Событий нет.</td>';
    tbody.append(row);
    return;
  }
  for (const event of events) {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${escapeHtml(formatTime(event.created_at))}</td>
      <td>${escapeHtml(event.actor_type)}${event.actor_id ? ` · ${escapeHtml(event.actor_id)}` : ""}</td>
      <td>${escapeHtml(event.action)}</td>
      <td>${escapeHtml(event.outcome)}</td>`;
    tbody.append(row);
  }
}

async function createPairingCode(event) {
  event.preventDefault();
  const name = $("#pair-name").value.trim();
  try {
    const data = await api("/api/v1/managers/pairing-codes", {
      method: "POST",
      body: JSON.stringify({ name: name || null }),
    });
    $("#pair-result").hidden = false;
    $("#pair-code").textContent = data.code;
    const minutes = Math.max(1, Math.round(data.ttl_seconds / 60));
    $("#pair-expires").textContent = `действует ${minutes} мин. до ${formatTime(data.expires_at)}`;
    const managerName = name || "Дом";
    const server = window.location.origin;
    $("#pair-command").textContent = [
      `.\\start-manager.bat --pair ${data.code} --server ${server} --name "${managerName}"`,
      `# или: yeelight-manager --pair ${data.code} --server ${server} --name "${managerName}"`,
    ].join("\n");
    log("Одноразовый код создан. Он показан только сейчас.");
  } catch (error) {
    log(`Не удалось создать код: ${error.message}`, "error");
  }
}

async function main() {
  $("#pair-form").addEventListener("submit", createPairingCode);
  $("#refresh-managers").addEventListener("click", () => {
    loadManagers().catch((error) => log(error.message, "error"));
  });
  $("#refresh-diagnostics").addEventListener("click", () => {
    loadDiagnostics().catch((error) => log(error.message, "error"));
  });
  $("#manager-list").addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-delete]");
    if (!button) return;
    const managerId = button.dataset.delete;
    if (!window.confirm("Удалить менеджер, его лампы и историю команд?")) return;
    try {
      await api(`/api/v1/managers/${encodeURIComponent(managerId)}`, { method: "DELETE" });
      log("Менеджер удалён.");
      await loadManagers();
      await loadDiagnostics();
    } catch (error) {
      log(error.message, "error");
    }
  });

  await startPage({
    ready: async () => {
      await loadManagers();
      await loadDiagnostics();
    },
    tick: async () => {
      await loadManagers();
      await loadDiagnostics();
    },
    intervalMs: 10000,
  });
}

main();
