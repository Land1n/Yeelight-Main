import {
  $,
  api,
  commandStatus,
  commandSummary,
  empty,
  escapeHtml,
  fillManagerSelect,
  formatTime,
  loadManagers,
  log,
  runCommand,
  selectedManager,
  startPage,
} from "./app.js";

const LAMP_ACTIONS = new Set(["status", "power", "brightness", "color", "color_temperature", "add", "remove"]);

const state = {
  managers: [],
  busy: false,
};

function currentManager() {
  return selectedManager(state.managers, $("#manager-select"));
}

function updateActionFields() {
  const action = $("#action-select").value;
  $("#ip-field").hidden = !LAMP_ACTIONS.has(action);
  $("#params-power").hidden = action !== "power";
  const showValue = action === "brightness" || action === "color_temperature";
  $("#params-value").hidden = !showValue;
  $("#params-rgb").hidden = action !== "color";
  if (action === "brightness") {
    $("#param-value").min = "1";
    $("#param-value").max = "100";
    $("#param-value").value = "60";
    $("#value-hint").textContent = "Яркость от 1 до 100.";
  } else if (action === "color_temperature") {
    $("#param-value").min = "1700";
    $("#param-value").max = "6500";
    $("#param-value").step = "100";
    $("#param-value").value = "4000";
    $("#value-hint").textContent = "Цветовая температура от 1700 до 6500 K.";
  } else {
    $("#param-value").step = "1";
  }
}

function updateManagerState() {
  const manager = currentManager();
  const pill = $("#manager-state");
  if (!manager) {
    pill.className = "pill pill-muted";
    pill.textContent = "не выбран";
    return;
  }
  pill.className = `pill ${manager.online ? "pill-muted" : "pill-warn"}`;
  pill.textContent = manager.online ? "онлайн" : "офлайн";
}

function collectParams(action) {
  if (action === "power") return { state: $("#param-state").value };
  if (action === "brightness" || action === "color_temperature") {
    return { value: Number($("#param-value").value) };
  }
  if (action === "color") return { hex: $("#param-hex").value };
  if (action === "add" || action === "remove") return { ip: $("#param-ip").value.trim() };
  return {};
}

async function execute(action, ip, params, label) {
  const manager = currentManager();
  if (!manager) {
    log("Сначала выберите менеджер.", "error");
    return null;
  }
  if (state.busy) return null;
  state.busy = true;
  $("#send-command").disabled = true;
  log(`> ${label}`, "command");
  try {
    const data = await runCommand(manager.id, action, ip || null, params);
    const command = data.command;
    log(`Статус: ${command.status}`);
    if (command.result) log(JSON.stringify(command.result, null, 2));
    if (command.error) log(`${command.error_code || "error"}: ${command.error}`, "error");
    await refreshHistory();
    return command;
  } catch (error) {
    log(`Ошибка: ${error.message}`, "error");
    if (error.command) {
      log(`Статус команды: ${error.command.status}`, "error");
      log(JSON.stringify(error.command, null, 2));
    }
    return null;
  } finally {
    state.busy = false;
    $("#send-command").disabled = false;
  }
}

async function submitCommand(event) {
  event.preventDefault();
  const action = $("#action-select").value;
  const ip = LAMP_ACTIONS.has(action) ? $("#param-ip").value.trim() : null;
  if (LAMP_ACTIONS.has(action) && !ip) {
    log("Введите IP лампы.", "error");
    return;
  }
  const params = collectParams(action);
  const summary = `${action}${ip ? ` ${ip}` : ""}${params.state ? ` ${params.state}` : ""}${params.value !== undefined ? ` ${params.value}` : ""}`;
  await execute(action, ip, params, summary);
}

function parseQuick(text) {
  const parts = text.trim().split(/\s+/);
  if (!parts.length) throw new Error("Введите команду.");
  const [operation, ...args] = parts;
  const ip = (value) => {
    if (!/^(?:\d{1,3}\.){3}\d{1,3}$/.test(value || "")) {
      throw new Error("Укажите корректный IPv4-адрес.");
    }
    return value;
  };
  if (operation === "discover" || operation === "list") {
    if (args.length) throw new Error(`Команда ${operation} не принимает аргументы.`);
    return { action: operation, ip: null, params: {} };
  }
  if (operation === "add" || operation === "remove") {
    if (args.length !== 1) throw new Error(`Использование: ${operation} <IP>`);
    return { action: operation, ip: ip(args[0]), params: { ip: ip(args[0]) } };
  }
  if (["on", "off", "toggle", "status"].includes(operation)) {
    if (args.length !== 1) throw new Error(`Использование: ${operation} <IP>`);
    if (operation === "status") return { action: "status", ip: ip(args[0]), params: {} };
    return { action: "power", ip: ip(args[0]), params: { state: operation } };
  }
  if (operation === "brightness") {
    if (args.length !== 2) throw new Error("Использование: brightness <IP> <1-100>");
    return { action: "brightness", ip: ip(args[0]), params: { value: Number(args[1]) } };
  }
  if (operation === "temp") {
    if (args.length !== 2) throw new Error("Использование: temp <IP> <1700-6500>");
    return { action: "color_temperature", ip: ip(args[0]), params: { value: Number(args[1]) } };
  }
  if (operation === "color") {
    if (args.length === 2 && /^#?[0-9a-fA-F]{6}$/.test(args[1])) {
      return { action: "color", ip: ip(args[0]), params: { hex: args[1] } };
    }
    if (args.length === 4) {
      return {
        action: "color",
        ip: ip(args[0]),
        params: { rgb: [Number(args[1]), Number(args[2]), Number(args[3])] },
      };
    }
    throw new Error("Использование: color <IP> <#RRGGBB> или color <IP> <R> <G> <B>");
  }
  throw new Error(`Неизвестная команда: ${operation}`);
}

async function runQuick() {
  try {
    const parsed = parseQuick($("#quick-command").value);
    await execute(parsed.action, parsed.ip, parsed.params, $("#quick-command").value.trim());
  } catch (error) {
    log(error.message, "error");
  }
}

async function refreshHistory() {
  const data = await api("/api/v1/commands?limit=50");
  const commands = data.commands || [];
  const tbody = $("#command-history");
  tbody.replaceChildren();
  if (!commands.length) {
    const row = document.createElement("tr");
    row.innerHTML = '<td colspan="5" class="empty">История пуста.</td>';
    tbody.append(row);
    return;
  }
  for (const command of commands) {
    const result = command.error || (command.result ? JSON.stringify(command.result) : "");
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${escapeHtml(formatTime(command.created_at))}</td>
      <td><code>${escapeHtml(commandSummary(command))}</code></td>
      <td>${escapeHtml(command.ip || "—")}</td>
      <td><span class="status-badge ${commandStatus(command) === "completed" ? "ok" : ["failed", "timed_out", "manager_unavailable"].includes(commandStatus(command)) ? "bad" : "warn"}">${escapeHtml(commandStatus(command))}</span></td>
      <td>${escapeHtml(result)}</td>`;
    tbody.append(row);
  }
}

async function refreshManagers() {
  state.managers = await loadManagers();
  fillManagerSelect($("#manager-select"), state.managers);
  const select = $("#manager-select");
  if (!state.managers.some((manager) => manager.id === select.value)) {
    const firstOnline = state.managers.find((manager) => manager.online) || state.managers[0];
    if (firstOnline) select.value = firstOnline.id;
  }
  updateManagerState();
}

async function main() {
  updateActionFields();
  $("#action-select").addEventListener("change", updateActionFields);
  $("#manager-select").addEventListener("change", updateManagerState);
  $("#command-form").addEventListener("submit", submitCommand);
  $("#quick-run").addEventListener("click", runQuick);
  $("#quick-command").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      runQuick();
    }
  });
  $("#refresh-history").addEventListener("click", () => refreshHistory().catch((error) => log(error.message, "error")));

  await startPage({
    ready: async () => {
      await refreshManagers();
      await refreshHistory();
    },
    tick: async () => {
      if (state.busy) return;
      await refreshManagers();
      await refreshHistory();
    },
    intervalMs: 10000,
  });
}

main();
