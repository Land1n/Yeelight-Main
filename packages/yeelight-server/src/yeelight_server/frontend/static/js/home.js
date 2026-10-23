import {
  $,
  api,
  commandStatus,
  commandSummary,
  escapeHtml,
  formatTime,
  log,
  startPage,
} from "./app.js";

async function refresh() {
  const [managersData, lampsData, modesData, commandsData] = await Promise.all([
    api("/api/v1/managers"),
    api("/api/v1/lamps"),
    api("/api/v1/modes"),
    api("/api/v1/commands?limit=10"),
  ]);
  const managers = managersData.managers || [];
  const lamps = lampsData.lamps || [];
  const modes = modesData.modes || [];
  const commands = commandsData.commands || [];

  const online = managers.filter(( manager ) => manager.online).length;
  $("#summary-managers").textContent = `${online} / ${managers.length}`;
  $("#summary-lamps").textContent = String(lamps.length);
  $("#summary-modes").textContent = String(modes.length);
  $("#summary-running").textContent = String(modes.filter((mode) => mode.running).length);

  const managerList = $("#manager-list");
  managerList.replaceChildren();
  if (!managers.length) {
    const block = document.createElement("div");
    block.className = "empty";
    block.innerHTML = 'Менеджеров пока нет. <a href="/setup">Создайте код подключения</a>.';
    managerList.append(block);
  } else {
    for (const manager of managers) {
      const lampCount = lamps.filter((lamp) => lamp.manager_id === manager.id).length;
      const card = document.createElement("div");
      card.className = "manager-card";
      card.innerHTML = `
        <div class="manager-info">
          <div class="manager-name">${escapeHtml(manager.name)}</div>
          <div class="manager-meta">${lampCount} ламп · последняя связь: ${escapeHtml(formatTime(manager.last_seen_at))} · ${escapeHtml(manager.version || "версия неизвестна")}</div>
        </div>
        <div class="manager-actions">
          <span class="status-badge ${manager.online ? "ok" : "bad"}">${manager.online ? "онлайн" : "офлайн"}</span>
          <a class="btn btn-ghost btn-small" href="/bulbs">К лампам</a>
        </div>`;
      managerList.append(card);
    }
  }

  const tbody = $("#recent-commands");
  tbody.replaceChildren();
  if (!commands.length) {
    const row = document.createElement("tr");
    row.innerHTML = '<td colspan="5" class="empty">Команд пока нет.</td>';
    tbody.append(row);
  } else {
    for (const command of commands) {
      const manager = managers.find((item) => item.id === command.manager_id);
      const row = document.createElement("tr");
      row.innerHTML = `
        <td>${escapeHtml(formatTime(command.created_at))}</td>
        <td>${escapeHtml(manager?.name || command.manager_id)}</td>
        <td><code>${escapeHtml(commandSummary(command))}</code></td>
        <td>${escapeHtml(command.ip || "—")}</td>
        <td><span class="status-badge ${commandStatus(command) === "completed" ? "ok" : commandStatus(command) === "failed" || commandStatus(command) === "timed_out" || commandStatus(command) === "manager_unavailable" ? "bad" : "warn"}">${escapeHtml(commandStatus(command))}</span></td>`;
      tbody.append(row);
    }
  }
}

async function main() {
  $("#refresh").addEventListener("click", async () => {
    try {
      await refresh();
      log("Сводка обновлена.");
    } catch (error) {
      log(error.message, "error");
    }
  });
  await startPage({
    ready: refresh,
    tick: refresh,
    intervalMs: 5000,
  });
}

main();
