import { ModeEditor } from "./mode-editor.js";
import { MODE_PRESETS } from "./mode-presets.js";
import { ModeList } from "./modes.js";
import { $, empty, startPage } from "./page.js";

const editor = new ModeEditor($("#task-list"));
let bulbs = [];
let editingModeName = null;

const modes = new ModeList($("#modes"), {
  request: null,
  log: null,
  bulbs: () => bulbs,
  editor: { load: loadMode },
});

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

function resetModeEditor() {
  editingModeName = null;
  $("#mode-name").value = "";
  $("#mode-name").disabled = false;
  $("#save-mode").textContent = "Сохранить режим";
  $("#cancel-mode-edit").hidden = true;
  editor.clear();
}

function renderModePresets(context) {
  const container = $("#mode-presets");
  if (!container) return;
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
    add.addEventListener("click", () => addModePreset(context, preset, add));
    card.append(name, description, colors, add);
    container.append(card);
  }
}

async function addModePreset(context, preset, button) {
  if (modes.modes.some((mode) => mode.name === preset.name)) {
    context.log(`Режим «${preset.name}» уже существует — он не был перезаписан.`, "error");
    renderModePresets(context);
    return;
  }
  button.disabled = true;
  try {
    await context.request("/api/modes", {
      method: "POST",
      body: JSON.stringify({
        name: preset.name,
        steps: preset.steps,
        delay_seconds: preset.delay_seconds,
      }),
    });
    await refreshAll(context);
    context.log(`Готовый режим «${preset.name}» добавлен и сохранён.`, "command");
  } catch (error) {
    context.log(`Не удалось добавить режим «${preset.name}»: ${error.message}`, "error");
  } finally {
    renderModePresets(context);
  }
}

async function saveMode(context, event) {
  event.preventDefault();
  if (!editor.steps.length) {
    context.log("Добавьте хотя бы одну задачу в режим.", "error");
    return;
  }
  const name = editingModeName || $("#mode-name").value.trim();
  if (!name) {
    context.log("Введите название режима.", "error");
    $("#mode-name").focus();
    return;
  }
  const existing = modes.modes.find((mode) => mode.name === name);
  if (!editingModeName && existing && !confirm(
    `Режим «${name}» уже существует. Заменить его новыми задачами?`,
  )) {
    return;
  }
  try {
    await context.request("/api/modes", {
      method: "POST",
      body: JSON.stringify({
        name,
        steps: editor.steps,
        delay_seconds: Number($("#mode-delay").value),
      }),
    });
    resetModeEditor();
    await refreshAll(context);
    context.log(
      existing && !editingModeName
        ? `Режим «${name}» перезаписан.`
        : `Режим «${name}» сохранён.`,
      "command",
    );
  } catch (error) {
    context.log(`Не удалось сохранить режим: ${error.message}`, "error");
  }
}

async function refreshAll(context) {
  const data = await context.request("/api/bulbs");
  bulbs = data.bulbs;
  await modes.refresh();
  renderModePresets(context);
}

startPage({
  create(context) {
    modes.request = context.request;
    modes.log = context.log;
    $("#add-task").addEventListener("click", () => editor.addStep());
    $("#cancel-mode-edit").addEventListener("click", resetModeEditor);
    $("#mode-form").addEventListener("submit", (event) => saveMode(context, event));
    resetModeEditor();
  },

  async ready(context) {
    await refreshAll(context);
  },

  async tick(context) {
    const data = await context.request("/api/bulbs");
    bulbs = data.bulbs;
    await modes.refreshStatuses();
  },

  unauthorized(context, message) {
    const list = $("#modes");
    if (list) list.replaceChildren(empty(message));
    const presets = $("#mode-presets");
    if (presets) presets.replaceChildren(empty(message));
  },
});
