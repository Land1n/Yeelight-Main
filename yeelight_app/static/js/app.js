import { createApi } from "./api.js";
import { BulbList } from "./bulbs.js";
import { ModeEditor } from "./mode-editor.js";
import { ModeList } from "./modes.js";
import { MODE_PRESETS } from "./mode-presets.js";

const $ = (selector) => document.querySelector(selector);
const output = $("#output");
const commandInput = $("#command");
const bulbsElement = $("#bulbs");
const tokenInput = $("#api-token");
const serverInput = $("#server-url");
const apiRequest = createApi(serverInput, tokenInput);
const editor = new ModeEditor($("#task-list"));
let busy = false;
let apiAuthorized = false;
let bulbs;
let modes;
let editingModeName = null;
let lanControlSubmitting = false;

serverInput.value = window.location.origin;
let storageWarningShown = false;

function warnStorageUnavailable() {
  if (storageWarningShown) return;
  storageWarningShown = true;
  log("Браузер не разрешил сохранить токен для этой вкладки; введите его снова после перезагрузки.", "error");
}

try {
  tokenInput.value = sessionStorage.getItem("yeelight-api-token") || "";
} catch {
  warnStorageUnavailable();
}
tokenInput.addEventListener("input", () => {
  try {
    sessionStorage.setItem("yeelight-api-token", tokenInput.value);
  } catch {
    warnStorageUnavailable();
  }
});

function log(text, kind = "") {
  const line = document.createElement("div");
  line.className = `entry ${kind}`;
  line.textContent = text;
  output.append(line);
  while (output.children.length > 100) output.firstElementChild.remove();
  output.scrollTop = output.scrollHeight;
}

function setConnection(ok, message) {
  $("#status-dot").className = `dot ${ok ? "ok" : "error"}`;
  $("#status-text").textContent = message;
}

function renderModePresets() {
  const container = $("#mode-presets");
  container.replaceChildren();
  for (const preset of MODE_PRESETS) {
    const card = document.createElement("article");
    card.className = "preset";
    const name = document.createElement("strong");
    name.textContent = preset.name;
    const description = document.createElement("p");
    description.textContent = preset.description;
    const colors = document.createElement("div");
    colors.className = "preset-colors";
    for (const color of preset.steps.map((step) => step.values)) {
      const swatch = document.createElement("span");
      swatch.style.backgroundColor = `rgb(${color.join(",")})`;
      swatch.setAttribute("aria-hidden", "true");
      colors.append(swatch);
    }
    const add = document.createElement("button");
    add.type = "button";
    const exists = modes.modes.some((mode) => mode.name === preset.name);
    add.textContent = exists ? "Уже добавлен" : "Добавить режим";
    add.disabled = exists;
    add.addEventListener("click", () => addModePreset(preset, add));
    card.append(name, description, colors, add);
    container.append(card);
  }
}

async function addModePreset(preset, button) {
  if (modes.modes.some((mode) => mode.name === preset.name)) {
    log(`Режим «${preset.name}» уже существует — он не был перезаписан.`, "error");
    renderModePresets();
    return;
  }
  button.disabled = true;
  try {
    await apiRequest("/api/modes", {
      method: "POST",
      body: JSON.stringify({
        name: preset.name,
        steps: preset.steps,
        delay_seconds: preset.delay_seconds,
      }),
    });
    await refreshModes();
    log(`Готовый режим «${preset.name}» добавлен и сохранён.`, "command");
  } catch (error) {
    log(`Не удалось добавить режим «${preset.name}»: ${error.message}`, "error");
  } finally {
    renderModePresets();
  }
}

async function refreshModes() {
  await modes.refresh();
  renderModePresets();
}

async function refreshBulbs() {
  await bulbs.refresh();
}

async function runCommand(text) {
  text = text.trim();
  if (!text || busy) return;
  busy = true;
  const submit = $("#command-form button");
  submit.disabled = true;
  log(`> ${text}`, "command");
  try {
    const data = await apiRequest("/api/commands", {
      method: "POST",
      body: JSON.stringify({ command: text }),
    });
    log(JSON.stringify(data.result, null, 2));
    setConnection(true, "Сервер подключён");
    if (/^(discover|add|remove|list)\b/.test(text)) {
      try {
        await refreshBulbs();
      } catch (error) {
        log(`Команда выполнена, но интерфейс не обновлён: ${error.message}`, "error");
      }
    }
  } catch (error) {
    log(`Ошибка: ${error.message}`, "error");
    setConnection(
      error.httpStatus !== undefined,
      error.httpStatus !== undefined ? "Сервер доступен • ошибка запроса" : "Нет подключения",
    );
  } finally {
    busy = false;
    submit.disabled = false;
  }
}

function resetModeEditor() {
  editingModeName = null;
  $("#mode-name").value = "";
  $("#mode-name").disabled = false;
  $("#save-mode").textContent = "Сохранить режим";
  $("#cancel-mode-edit").hidden = true;
  editor.clear();
}

function loadMode(mode) {
  editingModeName = mode.name;
  $("#mode-name").value = mode.name;
  $("#mode-name").disabled = true;
  $("#mode-delay").value = mode.delay_seconds;
  editor.setSteps(mode.steps);
  $("#save-mode").textContent = "Сохранить изменения";
  $("#cancel-mode-edit").hidden = false;
  $("#mode-name").focus({ preventScroll: true });
}

function bindEvents() {
  $("#command-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const text = commandInput.value;
    commandInput.value = "";
    runCommand(text);
  });
  $("#discover").addEventListener("click", () => runCommand("discover"));
  $("#reconnect").addEventListener("click", reconnectToServer);
  $("#wifi-form").addEventListener("submit", submitWifiSetup);
  $("#lan-control-form").addEventListener("submit", submitLanControl);
  tokenInput.addEventListener("change", () => initialize());
  $("#add-task").addEventListener("click", () => editor.addStep());
  $("#cancel-mode-edit").addEventListener("click", resetModeEditor);
  $("#mode-form").addEventListener("submit", saveMode);
  document.querySelectorAll("[data-command]").forEach((button) => {
    button.addEventListener("click", () => {
      const value = button.dataset.command;
      commandInput.value = value;
      commandInput.focus();
      if (value !== "add ") {
        commandInput.value = "";
        runCommand(value);
      }
    });
  });
}

async function reconnectToServer() {
  const button = $("#reconnect");
  if (button.disabled) return;
  button.disabled = true;
  button.textContent = "Подключение…";
  setConnection(false, "Подключаемся к серверу…");
  try {
    await initialize();
  } finally {
    button.disabled = false;
    button.textContent = "Переподключиться к серверу";
  }
}

async function submitWifiSetup(event) {
  event.preventDefault();
  const submit = $("#wifi-submit");
  const result = $("#wifi-result");
  const passwordInput = $("#wifi-password");
  const payload = {
    ip: $("#wifi-ip").value.trim(),
    ssid: $("#wifi-ssid").value,
    password: passwordInput.value,
  };
  submit.disabled = true;
  result.textContent = "Отправка запроса…";
  passwordInput.value = "";
  try {
    const response = await apiRequest("/api/provisioning/wifi", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    result.textContent = response.message;
    result.classList.toggle("error", response.status === "rejected");
    log(response.message, response.status === "rejected" ? "error" : "command");
  } catch (error) {
    result.textContent = `Не удалось отправить настройки: ${error.message}`;
    result.classList.add("error");
    log(`Настройки Wi-Fi не отправлены: ${error.message}`, "error");
  } finally {
    payload.password = "";
    passwordInput.value = "";
    submit.disabled = false;
  }
}

async function submitLanControl(event) {
  event.preventDefault();
  if (lanControlSubmitting) return;

  const submit = $("#lan-control-submit");
  const result = $("#lan-control-result");
  const ipInput = $("#lan-control-ip");
  const confirmed = $("#lan-control-confirm").checked;
  const ip = ipInput.value.trim();
  const octets = ip.split(".");
  if (
    octets.length !== 4 ||
    octets.some((octet) => !/^\d{1,3}$/.test(octet) || Number(octet) > 255)
  ) {
    result.textContent = "Введите корректный IPv4-адрес лампы.";
    result.classList.add("error");
    ipInput.focus();
    return;
  }
  if (!confirmed) {
    result.textContent = "Подтвердите включение LAN Control.";
    result.classList.add("error");
    $("#lan-control-confirm").focus();
    return;
  }

  lanControlSubmitting = true;
  submit.disabled = true;
  result.classList.remove("error");
  result.textContent = "Выполняется…";
  try {
    const response = await apiRequest("/api/provisioning/lan-control", {
      method: "POST",
      body: JSON.stringify({
        ip,
        confirmed,
      }),
    });
    result.textContent = response.message;
    result.classList.toggle(
      "error",
      response.status === "rejected" || response.status === "sent_unconfirmed",
    );
    log(response.message, response.status === "rejected" ? "error" : "command");
  } catch (error) {
    result.textContent = `Не удалось включить LAN Control: ${error.message}`;
    result.classList.add("error");
    log(`LAN Control не включён: ${error.message}`, "error");
  } finally {
    lanControlSubmitting = false;
    submit.disabled = false;
  }
}

async function saveMode(event) {
  event.preventDefault();
  if (!editor.steps.length) {
    log("Добавьте хотя бы одну задачу в режим.", "error");
    return;
  }
  try {
    await apiRequest("/api/modes", {
      method: "POST",
      body: JSON.stringify({
        name: editingModeName || $("#mode-name").value.trim(),
        steps: editor.steps,
        delay_seconds: Number($("#mode-delay").value),
      }),
    });
    resetModeEditor();
    await refreshModes();
  } catch (error) {
    log(`Не удалось сохранить режим: ${error.message}`, "error");
  }
}

async function refreshSettings() {
  const settings = await apiRequest("/api/settings");
  $("#monitor-settings").textContent =
    `Проверка ламп каждые ${settings.poll_interval_seconds} сек. ` +
    `Удаление после ${settings.offline_timeout_seconds} сек. без ответа (настройки сервера).`;
}

async function initialize() {
  if (!tokenInput.value.trim()) {
    apiAuthorized = false;
    setConnection(true, "Введите API-токен");
    bulbsElement.replaceChildren();
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "Введите YEELIGHT_API_TOKEN из файла .env.";
    bulbsElement.append(empty);
    $("#modes").replaceChildren();
    return;
  }
  try {
    await apiRequest("/api/health");
    await refreshBulbs();
    await refreshSettings();
    await refreshModes();
    apiAuthorized = true;
    setConnection(true, "Сервер подключён");
  } catch (error) {
    apiAuthorized = false;
    setConnection(false, "Нет подключения");
    bulbsElement.replaceChildren();
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = error.message;
    bulbsElement.append(empty);
    log(error.message, "error");
  }
}

function startPolling() {
  window.setInterval(() => {
    if (busy || !apiAuthorized) return;
    refreshBulbs().catch((error) =>
      log(`Список ламп не обновлён: ${error.message}`, "error"));
    modes.refreshStatuses().catch((error) =>
      log(`Состояние режимов не обновлено: ${error.message}`, "error"));
  }, 5000);
}

modes = new ModeList($("#modes"), {
  request: apiRequest,
  log,
  bulbs: () => bulbs.bulbs,
  editor: { load: loadMode },
});
bulbs = new BulbList(bulbsElement, {
  request: apiRequest,
  runCommand,
  log,
  setConnection,
  getModes: () => modes.modes,
  refreshModes,
});
modes.setBulbsView(bulbs);

bindEvents();
renderModePresets();
initialize();
startPolling();
