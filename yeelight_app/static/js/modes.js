import { modeSummary } from "./mode-editor.js";

export class ModeList {
  constructor(container, { request, log, bulbs, editor }) {
    this.container = container;
    this.request = request;
    this.log = log;
    this.bulbs = bulbs;
    this.editor = editor;
    this.items = [];
  }

  get modes() {
    return this.items;
  }

  async refresh() {
    const data = await this.request("/api/modes");
    this.items = data.modes;

    for (const mode of this.items) {
      if (mode.running_ip && !this.bulbs().some((bulb) => bulb.ip === mode.running_ip)) {
        await this.request(`/api/modes/${encodeURIComponent(mode.name)}/stop`, {
          method: "POST",
        });
        mode.running = false;
        mode.running_ip = null;
      }
    }
    this.render();
  }

  async refreshStatuses() {
    const data = await this.request("/api/modes");
    this.items = data.modes;
    for (const mode of this.items) {
      const row = [...this.container.querySelectorAll(".mode")]
        .find((item) => item.dataset.name === mode.name);
      if (!row) continue;
      row.querySelector(".mode-running-label").textContent = modeLabel(mode);
      row.querySelector(".mode-edit").disabled = mode.running;
      const button = row.querySelector(".mode-toggle");
      button.textContent = mode.running ? "Остановить" : "Запустить";
      const select = row.querySelector("select");
      select.disabled = mode.running || this.bulbs().length === 0;
      button.disabled = !mode.running && this.bulbs().length === 0;
    }
    this.bulbsView?.updateModeControls();
  }

  setBulbsView(view) {
    this.bulbsView = view;
  }

  render() {
    this.container.replaceChildren();
    if (!this.items.length) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = "Режимов пока нет. Создайте последовательность команд выше.";
      this.container.append(empty);
      this.bulbsView?.updateModeControls();
      return;
    }
    for (const mode of this.items) this.container.append(this.createModeRow(mode));
    this.bulbsView?.updateModeControls();
  }

  createModeRow(mode) {
    const row = document.createElement("article");
    row.className = "mode";
    row.dataset.name = mode.name;
    const info = document.createElement("div");
    info.className = "mode-info";
    const title = document.createElement("strong");
    title.className = "mode-running-label";
    title.textContent = modeLabel(mode);
    const summary = document.createElement("div");
    summary.className = "mode-commands";
    summary.textContent = mode.last_error ? `Ошибка: ${mode.last_error}` : modeSummary(mode.steps);
    info.append(title, summary);

    const buttons = document.createElement("div");
    buttons.className = "actions";
    const target = this.createTargetSelect(mode);
    const startStop = this.createStartStopButton(mode, target);
    const edit = this.createEditButton(mode);
    const remove = this.createDeleteButton(mode);
    const label = document.createElement("label");
    label.className = "mode-ip";
    label.append(document.createTextNode("IP лампы при запуске"), target);
    buttons.append(label, startStop, edit, remove);
    row.append(info, buttons);
    return row;
  }

  createTargetSelect(mode) {
    const target = document.createElement("select");
    target.setAttribute("aria-label", `Лампа для режима ${mode.name}`);
    for (const bulb of this.bulbs()) {
      const option = document.createElement("option");
      option.value = bulb.ip;
      option.textContent = bulb.ip;
      target.append(option);
    }
    if (mode.running && mode.running_ip) target.value = mode.running_ip;
    target.disabled = mode.running || this.bulbs().length === 0;
    return target;
  }

  createStartStopButton(mode, target) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "mode-toggle";
    button.textContent = mode.running ? "Остановить" : "Запустить";
    button.disabled = !mode.running && this.bulbs().length === 0;
    button.addEventListener("click", async () => {
      try {
        const action = mode.running ? "stop" : "start";
        await this.request(`/api/modes/${encodeURIComponent(mode.name)}/${action}`, {
          method: "POST",
          body: mode.running ? undefined : JSON.stringify({ ip: target.value }),
        });
        await this.refresh();
      } catch (error) {
        this.log(`Ошибка режима: ${error.message}`, "error");
      }
    });
    return button;
  }

  createEditButton(mode) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "mode-edit";
    button.textContent = "Изменить";
    button.disabled = mode.running;
    button.title = mode.running ? "Сначала остановите режим" : "Редактировать задачи режима";
    button.addEventListener("click", () => this.editor.load(mode));
    return button;
  }

  createDeleteButton(mode) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "Удалить";
    button.addEventListener("click", async () => {
      try {
        await this.request(`/api/modes/${encodeURIComponent(mode.name)}`, {
          method: "DELETE",
        });
        await this.refresh();
      } catch (error) {
        this.log(`Ошибка режима: ${error.message}`, "error");
      }
    });
    return button;
  }
}

function modeLabel(mode) {
  return `${mode.name}${mode.running ? ` • выполняется на ${mode.running_ip}` : ""}`;
}
