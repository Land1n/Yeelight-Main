import {
  $,
  api,
  empty,
  escapeHtml,
  fillManagerSelect,
  loadManagerLamps,
  loadManagers,
  log,
  runCommand,
  selectedManager,
  startPage,
} from "./app.js";

const ACTIONS = ["on", "off", "toggle", "status", "brightness", "color", "temp"];

const PRESETS = {
  "Фиолетовое переливание": [
    { action: "on", values: [] },
    { action: "color", values: [120, 0, 200] },
    { action: "brightness", values: [60] },
    { action: "color", values: [40, 0, 160] },
    { action: "brightness", values: [100] },
  ],
  "Тёплый закат": [
    { action: "on", values: [] },
    { action: "temp", values: [2700] },
    { action: "brightness", values: [70] },
    { action: "temp", values: [2200] },
    { action: "brightness", values: [30] },
  ],
  "Морская волна": [
    { action: "on", values: [] },
    { action: "color", values: [0, 160, 200] },
    { action: "brightness", values: [80] },
    { action: "color", values: [0, 90, 160] },
    { action: "brightness", values: [40] },
  ],
  "Ночник": [
    { action: "on", values: [] },
    { action: "temp", values: [2000] },
    { action: "brightness", values: [8] },
  ],
};

const state = {
  managers: [],
  modes: [],
  lamps: [],
  busy: false,
};

function currentManager() {
  return selectedManager(state.managers, $("#manager-select"));
}

function selectedIp() {
  return $("#lamp-select")?.value || "";
}

function describeStep(step) {
  if (step.action === "color") return `color ${step.values.join(", ")}`;
  if (step.values.length) return `${step.action} ${step.values.join(" ")}`;
  return step.action;
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
  const previous = select.value;
  if (!state.managers.some((manager) => manager.id === previous)) {
    const firstOnline = state.managers.find((manager) => manager.online) || state.managers[0];
    if (firstOnline) select.value = firstOnline.id;
  }
  updateManagerState();
}

async function refreshLamps() {
  const manager = currentManager();
  const select = $("#lamp-select");
  const previous = select.value;
  state.lamps = manager ? await loadManagerLamps(manager.id) : [];
  select.replaceChildren();
  if (!state.lamps.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "Нет известных ламп";
    select.append(option);
  } else {
    for (const lamp of state.lamps) {
      const option = document.createElement("option");
      option.value = lamp.ip;
      option.textContent = `${lamp.name || lamp.ip} · ${lamp.ip}`;
      select.append(option);
    }
    if (state.lamps.some((lamp) => lamp.ip === previous)) select.value = previous;
  }
}

function renderPresets() {
  const container = $("#mode-presets");
  container.replaceChildren();
  for (const [name, steps] of Object.entries(PRESETS)) {
    const wrapper = document.createElement("span");
    wrapper.className = "preset";
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = name;
    button.addEventListener("click", () => {
      for (const step of steps) addTask(step);
      log(`Пресет «${name}» добавлен в редактор.`);
    });
    wrapper.append(button);
    container.append(wrapper);
  }
}

function valueControl(action, value) {
  if (action === "brightness") {
    return `<label class="field"><span>Яркость 1–100</span><input type="number" min="1" max="100" value="${Number(value ?? 50)}" data-value="number"></label>`;
  }
  if (action === "temp") {
    return `<label class="field"><span>Температура 1700–6500 K</span><input type="number" min="1700" max="6500" step="100" value="${Number(value ?? 4000)}" data-value="number"></label>`;
  }
  if (action === "color") {
    const rgb = Array.isArray(value) && value.length === 3 ? value : [51, 170, 255];
    const hex = `#${rgb.map((channel) => Number(channel).toString(16).padStart(2, "0")).join("")}`;
    return `<label class="field"><span>Цвет</span><input type="color" value="${hex}" data-value="color"></label>`;
  }
  return '<span class="field-hint">Без значений</span>';
}

function addTask(step = { action: "on", values: [] }, index = null) {
  const list = $("#task-list");
  const item = document.createElement("div");
  item.className = "task-item";
  const options = ACTIONS.map((action) => `<option value="${action}" ${action === step.action ? "selected" : ""}>${action}</option>`).join("");
  item.innerHTML = `
    <select class="task-action" aria-label="Действие">${options}</select>
    <div class="task-value">${valueControl(step.action, step.values[0])}</div>
    <div class="task-controls">
      <button type="button" data-task="up" title="Выше">↑</button>
      <button type="button" data-task="down" title="Ниже">↓</button>
      <button type="button" data-task="delete" class="danger" title="Удалить">×</button>
    </div>`;
  if (step.action === "color" && Array.isArray(step.values)) {
    const color = item.querySelector('input[type="color"]');
    if (color) {
      color.value = `#${step.values.map((channel) => Number(channel).toString(16).padStart(2, "0")).join("")}`;
    }
  }
  item.querySelector(".task-action").addEventListener("change", (event) => {
    item.querySelector(".task-value").innerHTML = valueControl(event.target.value);
  });
  item.querySelector('[data-task="delete"]').addEventListener("click", () => item.remove());
  item.querySelector('[data-task="up"]').addEventListener("click", () => {
    const previous = item.previousElementSibling;
    if (previous) list.insertBefore(item, previous);
  });
  item.querySelector('[data-task="down"]').addEventListener("click", () => {
    const next = item.nextElementSibling;
    if (next) list.insertBefore(next, item);
  });
  list.append(item);
}

function collectSteps() {
  return Array.from($("#task-list").children).map((item) => {
    const action = item.querySelector(".task-action").value;
    const values = [];
    if (action === "brightness" || action === "temp") {
      values.push(Number(item.querySelector('[data-value="number"]').value));
    } else if (action === "color") {
      const hex = item.querySelector('[data-value="color"]').value;
      const value = Number.parseInt(hex.slice(1), 16);
      values.push((value >> 16) & 255, (value >> 8) & 255, value & 255);
    }
    return { action, values };
  });
}

function resetEditor() {
  $("#mode-id").value = "";
  $("#mode-name").value = "";
  $("#mode-delay").value = "1";
  $("#task-list").replaceChildren();
  addTask({ action: "on", values: [] });
}

function editMode(mode) {
  $("#mode-id").value = mode.id;
  $("#mode-name").value = mode.name;
  $("#mode-delay").value = String(mode.delay_seconds);
  $("#task-list").replaceChildren();
  for (const step of mode.steps) addTask(step);
  $("#mode-name").focus();
  $("#mode-name").scrollIntoView({ behavior: "smooth", block: "center" });
}

function renderModes() {
  const list = $("#modes");
  const count = $("#modes-count");
  count.textContent = String(state.modes.length);
  list.replaceChildren();
  if (!state.modes.length) {
    list.append(empty("Сохранённых режимов нет. Соберите первый в редакторе выше."));
    return;
  }
  for (const mode of state.modes) {
    const item = document.createElement("article");
    item.className = "mode";
    item.dataset.modeId = mode.id;
    const ip = selectedIp();
    const steps = mode.steps.map(describeStep).join(" → ");
    item.innerHTML = `
      <div class="mode-info">
        <div class="mode-running-label">${escapeHtml(mode.name)} <span class="status-badge ${mode.running ? "ok" : "muted"}">${mode.running ? "выполняется" : "остановлен"}</span></div>
        <div class="mode-commands">${escapeHtml(steps)}</div>
        <div class="mode-meta">пауза ${escapeHtml(mode.delay_seconds)} с${mode.last_error ? ` · ошибка: ${escapeHtml(mode.last_error)}` : ""}${mode.running_ip ? ` · ${escapeHtml(mode.running_ip)}` : ""}</div>
      </div>
      <div class="actions">
        <button type="button" data-mode-action="start" ${!ip || mode.running ? "disabled" : ""}>Запустить</button>
        <button type="button" data-mode-action="stop" ${mode.running ? "" : "disabled"}>Остановить</button>
        <button type="button" data-mode-action="edit" ${mode.running ? "disabled" : ""}>Изменить</button>
        <button type="button" data-mode-action="delete" class="danger" ${mode.running ? "disabled" : ""}>Удалить</button>
      </div>`;
    list.append(item);
  }
}

async function refreshModes() {
  const data = await api("/api/v1/modes");
  state.modes = data.modes || [];
  renderModes();
}

async function saveMode(event) {
  event.preventDefault();
  const name = $("#mode-name").value.trim();
  const delay = Number($("#mode-delay").value);
  const steps = collectSteps();
  if (!name) {
    log("Введите название режима.", "error");
    return;
  }
  if (!steps.length) {
    log("Добавьте хотя бы одну задачу.", "error");
    return;
  }
  try {
    const data = await api("/api/v1/modes", {
      method: "POST",
      body: JSON.stringify({ name, steps, delay_seconds: delay }),
    });
    log(`Режим «${data.mode.name}» сохранён.`);
    resetEditor();
    await refreshModes();
  } catch (error) {
    log(`Ошибка сохранения: ${error.message}`, "error");
  }
}

async function modeAction(mode, action) {
  const manager = currentManager();
  const ip = selectedIp();
  if (action === "edit") {
    editMode(mode);
    return;
  }
  if (action === "delete") {
    if (!window.confirm(`Удалить режим «${mode.name}»?`)) return;
    try {
      await api(`/api/v1/modes/${encodeURIComponent(mode.id)}`, { method: "DELETE" });
      log(`Режим «${mode.name}» удалён.`);
      await refreshModes();
    } catch (error) {
      log(error.message, "error");
    }
    return;
  }
  if (action === "start") {
    if (!manager || !ip) {
      log("Выберите менеджер и лампу.", "error");
      return;
    }
    try {
      const data = await api(`/api/v1/modes/${encodeURIComponent(mode.id)}/start`, {
        method: "POST",
        body: JSON.stringify({ manager_id: manager.id, ip }),
      });
      log(`Режим «${data.mode.name}» запущен на ${data.ip}.`);
      await refreshModes();
    } catch (error) {
      log(`Ошибка запуска: ${error.message}`, "error");
    }
    return;
  }
  if (action === "stop") {
    try {
      await api(`/api/v1/modes/${encodeURIComponent(mode.id)}/stop`, { method: "POST" });
      log(`Режим «${mode.name}» остановлен.`);
      await refreshModes();
    } catch (error) {
      log(error.message, "error");
    }
  }
}

async function main() {
  resetEditor();
  renderPresets();

  $("#mode-form").addEventListener("submit", saveMode);
  $("#add-task").addEventListener("click", () => addTask());
  $("#reset-mode").addEventListener("click", resetEditor);

  $("#manager-select").addEventListener("change", async () => {
    updateManagerState();
    try {
      await refreshLamps();
      renderModes();
    } catch (error) {
      log(error.message, "error");
    }
  });
  $("#lamp-select").addEventListener("change", renderModes);

  $("#modes").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-mode-action]");
    if (!button) return;
    const mode = state.modes.find((item) => item.id === button.closest(".mode")?.dataset.modeId);
    if (mode) modeAction(mode, button.dataset.modeAction);
  });

  await startPage({
    ready: async () => {
      await refreshManagers();
      await refreshLamps();
      await refreshModes();
    },
    tick: async () => {
      if (state.busy) return;
      await refreshManagers();
      await refreshModes();
    },
    intervalMs: 5000,
  });
}

main();
