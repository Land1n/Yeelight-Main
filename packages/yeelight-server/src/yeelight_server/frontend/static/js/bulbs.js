import {
  $,
  api,
  empty,
  escapeHtml,
  fillManagerSelect,
  formatTime,
  loadManagerLamps,
  loadManagers,
  log,
  managerLabel,
  runCommand,
  selectedManager,
  startPage,
} from "./app.js";

const state = {
  managers: [],
  managerId: "",
  lamps: [],
  busy: false,
};

function currentManager() {
  return selectedManager(state.managers, $("#manager-select"));
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

async function refreshManagers() {
  state.managers = await loadManagers();
  fillManagerSelect($("#manager-select"), state.managers);
  const select = $("#manager-select");
  if (!state.managerId || !state.managers.some((item) => item.id === state.managerId)) {
    const firstOnline = state.managers.find((item) => item.online) || state.managers[0];
    state.managerId = firstOnline?.id || "";
  }
  if (state.managerId) select.value = state.managerId;
  updateManagerState();
}

async function refreshLamps() {
  if (!state.managerId) {
    state.lamps = [];
    renderLamps();
    return;
  }
  state.lamps = await loadManagerLamps(state.managerId);
  renderLamps();
}

function lampStateText(lamp) {
  const parts = [];
  if (lamp.power) parts.push(`питание: ${lamp.power}`);
  if (lamp.brightness !== null && lamp.brightness !== undefined) parts.push(`яркость: ${lamp.brightness}`);
  if (lamp.color_temperature) parts.push(`${lamp.color_temperature} K`);
  if (Array.isArray(lamp.rgb)) parts.push(`RGB ${lamp.rgb.join(", ")}`);
  if (lamp.model) parts.push(lamp.model);
  return parts.join(" · ") || "состояние ещё не прочитано";
}

function renderLamps() {
  const list = $("#bulbs");
  const count = $("#bulbs-count");
  count.textContent = `${state.lamps.length}`;
  list.replaceChildren();
  if (!state.managers.length) {
    list.append(empty("Сначала подключите менеджер на странице «Менеджеры»."));
    return;
  }
  if (!state.managerId) {
    list.append(empty("Выберите менеджер."));
    return;
  }
  if (!state.lamps.length) {
    list.append(empty("Ламп нет. Нажмите «Найти лампы» или добавьте IP вручную."));
    return;
  }
  for (const lamp of state.lamps) {
    const card = document.createElement("article");
    card.className = "bulb";
    card.dataset.ip = lamp.ip;
    const onlineClass = lamp.online === false ? "offline" : lamp.online ? "online" : "";
    const brightness = Number.isFinite(Number(lamp.brightness)) ? Number(lamp.brightness) : 50;
    const temperature = Number.isFinite(Number(lamp.color_temperature)) ? Number(lamp.color_temperature) : 4000;
    card.innerHTML = `
      <div class="bulb-info">
        <div class="bulb-ip">${escapeHtml(lamp.name || lamp.ip)} <span class="bulb-state"><span class="bulb-dot ${onlineClass}"></span>${lamp.online === false ? "офлайн" : lamp.online ? "онлайн" : "неизвестно"}</span></div>
        <div class="bulb-current">${escapeHtml(lamp.ip)} · ${escapeHtml(lampStateText(lamp))}</div>
        <div class="lamp-controls">
          <div class="lamp-control-row">
            <label>Яркость</label>
            <input type="range" min="1" max="100" value="${brightness}" data-command="brightness">
            <output>${brightness}%</output>
          </div>
          <div class="lamp-control-row">
            <label>Температура</label>
            <input type="range" min="1700" max="6500" step="100" value="${temperature}" data-command="temp">
            <output>${temperature} K</output>
          </div>
          <div class="lamp-control-row">
            <label>Цвет</label>
            <input type="color" value="${Array.isArray(lamp.rgb) ? `#${lamp.rgb.map((value) => Number(value).toString(16).padStart(2, "0")).join("")}` : "#ffffff"}" data-command="color">
            <button type="button" data-action="status">Статус</button>
            <button type="button" class="danger" data-action="remove">Удалить</button>
          </div>
        </div>
      </div>
      <div class="lamp-actions">
        <button type="button" data-action="power" data-state="on">Включить</button>
        <button type="button" data-action="power" data-state="off">Выключить</button>
        <button type="button" data-action="power" data-state="toggle">Переключить</button>
      </div>`;
    list.append(card);
  }
}

async function send(action, ip, params = {}, label = action, options = {}) {
  if (state.busy) return null;
  const manager = currentManager();
  if (!manager) {
    log("Сначала выберите менеджер.", "error");
    return null;
  }
  state.busy = true;
  log(`> ${label}`, "command");
  try {
    const data = await runCommand(manager.id, action, ip, params, options);
    const command = data.command;
    log(`Статус: ${command.status}`);
    if (command.result) log(JSON.stringify(command.result, null, 2));
    if (command.error) log(`Ошибка: ${command.error}`, "error");
    if (command.status === "completed") {
      await refreshLamps();
    }
    return command;
  } catch (error) {
    log(`Ошибка: ${error.message}`, "error");
    if (error.command) log(`Статус команды: ${error.command.status}`, "error");
    return null;
  } finally {
    state.busy = false;
  }
}

async function discover() {
  await send("discover", null, {}, "discover");
  await refreshLamps();
}

async function addLamp(event) {
  event.preventDefault();
  const input = $("#add-lamp-ip");
  const ip = input.value.trim();
  if (!ip) return;
  const command = await send("add", ip, { ip }, `add ${ip}`);
  if (command?.status === "completed") {
    input.value = "";
    await new Promise((resolve) => window.setTimeout(resolve, 300));
    await refreshLamps();
  }
}

function bindLampControls() {
  const list = $("#bulbs");
  list.addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button) return;
    const card = button.closest(".bulb");
    const ip = card?.dataset.ip;
    if (!ip) return;
    const action = button.dataset.action;
    if (action === "power") {
      await send("power", ip, { state: button.dataset.state }, `power ${button.dataset.state} ${ip}`);
    } else if (action === "status") {
      await send("status", ip, {}, `status ${ip}`);
    } else if (action === "remove") {
      if (!window.confirm(`Удалить лампу ${ip} из списка менеджера?`)) return;
      await send("remove", ip, { ip }, `remove ${ip}`);
      await refreshLamps();
    }
  });

  list.addEventListener("change", async (event) => {
    const control = event.target;
    const card = control.closest(".bulb");
    const ip = card?.dataset.ip;
    if (!ip || !control.dataset.command) return;
    const output = control.parentElement?.querySelector("output");
    if (control.dataset.command === "brightness") {
      const value = Number(control.value);
      if (output) output.textContent = `${value}%`;
      await send("brightness", ip, { value }, `brightness ${ip} ${value}`);
    } else if (control.dataset.command === "temp") {
      const value = Number(control.value);
      if (output) output.textContent = `${value} K`;
      await send("color_temperature", ip, { value }, `color_temperature ${ip} ${value}`);
    } else if (control.dataset.command === "color") {
      await send("color", ip, { hex: control.value }, `color ${ip} ${control.value}`);
    }
  });
}

async function main() {
  $("#manager-select").addEventListener("change", async (event) => {
    state.managerId = event.target.value;
    updateManagerState();
    try {
      await refreshLamps();
    } catch (error) {
      log(error.message, "error");
    }
  });
  $("#discover").addEventListener("click", async () => {
    try {
      $("#discover").disabled = true;
      await discover();
    } catch (error) {
      log(error.message, "error");
    } finally {
      $("#discover").disabled = false;
    }
  });
  $("#add-lamp-form").addEventListener("submit", addLamp);
  bindLampControls();

  await startPage({
    ready: async () => {
      await refreshManagers();
      await refreshLamps();
    },
    tick: async () => {
      if (state.busy) return;
      const active = document.activeElement;
      if (active && ["INPUT", "SELECT", "TEXTAREA"].includes(active.tagName)) return;
      if (active && active.closest?.("#bulbs")) return;
      await refreshManagers();
      await refreshLamps();
    },
    intervalMs: 8000,
  });
}

main();
