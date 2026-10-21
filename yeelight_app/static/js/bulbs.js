function responseState(online) {
  if (online === true) return { className: "online", label: "Есть ответ" };
  if (online === false) return { className: "offline", label: "Нет ответа" };
  return { className: "", label: "Проверяем связь…" };
}

function modeButtonState(mode, ip) {
  const runningHere = Boolean(mode?.running && mode.running_ip === ip);
  const runningElsewhere = Boolean(mode?.running && mode.running_ip !== ip);
  return {
    runningHere,
    disabled: !mode || runningElsewhere,
    label: runningHere
      ? "Остановить режим"
      : runningElsewhere ? `Уже запущен на ${mode.running_ip}` : "Запустить режим",
  };
}

export class BulbList {
  constructor(container, {
    request,
    runCommand,
    log,
    setConnection,
    getModes,
    refreshModes,
  }) {
    this.container = container;
    this.request = request;
    this.runCommand = runCommand;
    this.log = log;
    this.setConnection = setConnection;
    this.getModes = getModes;
    this.refreshModes = refreshModes;
    this.items = [];
    this.rendered = false;
  }

  get bulbs() {
    return this.items;
  }

  async refresh() {
    const data = await this.request("/api/bulbs");
    const oldIps = this.items.map((bulb) => bulb.ip).sort().join(",");
    const newIps = data.bulbs.map((bulb) => bulb.ip).sort().join(",");
    this.items = data.bulbs;

    if (
      this.rendered &&
      oldIps === newIps &&
      this.container.querySelectorAll(".bulb").length === data.bulbs.length
    ) {
      this.updateIndicators(data.bulbs);
      return;
    }
    this.render();
    this.rendered = true;
    await this.refreshModes();
  }

  render() {
    this.container.replaceChildren();
    if (!this.items.length) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = "Ламп пока нет. Нажмите «Найти лампы» или добавьте адрес через команду add.";
      this.container.append(empty);
      return;
    }
    for (const bulb of this.items) this.container.append(this.createCard(bulb));
  }

  updateIndicators(bulbs) {
    for (const bulb of bulbs) {
      const card = [...this.container.querySelectorAll(".bulb")]
        .find((item) => item.dataset.ip === bulb.ip);
      if (!card) continue;
      const state = responseState(bulb.online);
      card.querySelector(".bulb-dot").className = `bulb-dot ${state.className}`;
      card.querySelector(".bulb-state-text").textContent = state.label;
    }
  }

  createCard(bulb) {
    const card = document.createElement("article");
    card.className = "bulb";
    card.dataset.ip = bulb.ip;

    const info = document.createElement("div");
    info.className = "bulb-info";
    const ip = document.createElement("div");
    ip.className = "bulb-ip";
    ip.textContent = bulb.ip;
    const state = document.createElement("div");
    state.className = "bulb-state";
    const dot = document.createElement("span");
    const visual = responseState(bulb.online);
    dot.className = `bulb-dot ${visual.className}`;
    dot.setAttribute("aria-hidden", "true");
    const label = document.createElement("span");
    label.className = "bulb-state-text";
    label.textContent = visual.label;
    state.append(dot, label);
    const current = document.createElement("div");
    current.className = "bulb-current";
    current.textContent = "Откройте «Управление», чтобы прочитать текущее состояние.";
    info.append(ip, state, current);

    const menu = document.createElement("details");
    menu.className = "bulb-menu";
    const summary = document.createElement("summary");
    summary.textContent = "Управление";
    const panel = document.createElement("div");
    panel.className = "menu-panel";
    panel.append(this.createActions(bulb), this.createColorControl(bulb));
    panel.append(
      this.createSliderControl(bulb, "brightness", "Яркость", 1, 100, "100"),
      this.createSliderControl(bulb, "temp", "Температура цвета", 1700, 6500, "4000", 100),
      this.createModeControl(bulb),
      this.createRemoveButton(bulb),
    );
    menu.append(summary, panel);
    menu.addEventListener("toggle", () => {
      if (menu.open) this.loadState(bulb, card);
    });
    card.append(info, menu);
    return card;
  }

  async loadState(bulb, card) {
    const current = card.querySelector(".bulb-current");
    current.textContent = "Читаем состояние с лампы…";
    try {
      const data = await this.request("/api/commands", {
        method: "POST",
        body: JSON.stringify({ command: `status ${bulb.ip}` }),
      });
      this.applyState(card, data.result?.properties || {});
    } catch (error) {
      current.textContent = `Не удалось прочитать состояние: ${error.message}`;
    }
  }

  applyState(card, properties) {
    const power =
      properties.power === "on" ? "включена"
        : properties.power === "off" ? "выключена"
          : "состояние неизвестно";
    const details = [power];
    const brightness = Number(properties.bright);
    if (Number.isFinite(brightness) && properties.bright !== null) {
      details.push(`яркость ${brightness}%`);
    }
    const rgb = Number(properties.rgb);
    if (properties.color_mode === "2" && Number.isFinite(rgb)) {
      details.push(`RGB(${(rgb >> 16) & 255}, ${(rgb >> 8) & 255}, ${rgb & 255})`);
    } else if (properties.ct !== null && properties.ct !== undefined) {
      details.push(`${properties.ct} K`);
    }
    card.querySelector(".bulb-current").textContent = `Сейчас: ${details.join(" · ")}`;

    const brightnessControl = card.querySelector('[data-control="brightness"]');
    if (brightnessControl && Number.isFinite(brightness) && properties.bright !== null) {
      brightnessControl.querySelector(".control-slider").value = String(brightness);
      brightnessControl.querySelector(".control-output").textContent = `${brightness}%`;
    }
    const tempControl = card.querySelector('[data-control="temp"]');
    const temperature = Number(properties.ct);
    if (tempControl && properties.ct !== null && Number.isFinite(temperature)) {
      tempControl.querySelector(".control-slider").value = String(temperature);
      tempControl.querySelector(".control-output").textContent = `${temperature} K`;
    }
    const picker = card.querySelector(".color-picker");
    if (picker && properties.color_mode === "2" && Number.isFinite(rgb)) {
      picker.value = `#${(rgb & 0xffffff).toString(16).padStart(6, "0")}`;
    }
  }

  async applyControl(bulb, command, card) {
    const current = card.querySelector(".bulb-current");
    current.textContent = "Применяем…";
    try {
      await this.request("/api/commands", {
        method: "POST",
        body: JSON.stringify({ command }),
      });
      await this.loadState(bulb, card);
    } catch (error) {
      current.textContent = `Ошибка: ${error.message}`;
    }
  }

  createActions(bulb) {
    const actions = document.createElement("div");
    actions.className = "menu-actions";
    for (const [label, operation] of [
      ["Вкл", "on"], ["Выкл", "off"], ["Переключить", "toggle"], ["Статус", "status"],
    ]) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = label;
      button.addEventListener("click", () =>
        this.applyControl(bulb, `${operation} ${bulb.ip}`, button.closest(".bulb")));
      actions.append(button);
    }
    return actions;
  }

  createColorControl(bulb) {
    const row = document.createElement("div");
    row.className = "palette-row";
    const label = document.createElement("span");
    label.textContent = "Цвет";
    const picker = document.createElement("input");
    picker.type = "color";
    picker.className = "color-picker";
    picker.value = "#ffffff";
    picker.setAttribute("aria-label", `Выбрать цвет лампы ${bulb.ip}`);
    const apply = document.createElement("button");
    apply.type = "button";
    apply.textContent = "Применить";
    apply.addEventListener("click", () => {
      const channels = [1, 3, 5].map((offset) =>
        parseInt(picker.value.slice(offset, offset + 2), 16));
      this.applyControl(
        bulb,
        `color ${bulb.ip} ${channels.join(" ")}`,
        apply.closest(".bulb"),
      );
    });
    row.append(label, picker, apply);
    return row;
  }

  createSliderControl(bulb, operation, labelText, min, max, initialValue, step = 1) {
    const row = document.createElement("label");
    row.className = "slider-row";
    row.dataset.control = operation;
    const label = document.createElement("span");
    label.textContent = labelText;
    const output = document.createElement("output");
    output.className = "control-output";
    output.textContent = operation === "temp" ? `${initialValue} K` : `${initialValue}%`;
    const slider = document.createElement("input");
    slider.type = "range";
    slider.className = "control-slider";
    slider.min = String(min);
    slider.max = String(max);
    slider.step = String(step);
    slider.value = initialValue;
    if (operation === "temp") slider.classList.add("temperature-slider");
    slider.setAttribute("aria-label", `${labelText} лампы ${bulb.ip}`);
    slider.addEventListener("input", () => {
      output.textContent = operation === "temp" ? `${slider.value} K` : `${slider.value}%`;
    });
    const apply = document.createElement("button");
    apply.type = "button";
    apply.textContent = "Применить";
    apply.addEventListener("click", () =>
      this.applyControl(
        bulb,
        `${operation} ${bulb.ip} ${slider.value}`,
        apply.closest(".bulb"),
      ));
    row.append(label, output, slider, apply);
    return row;
  }

  createModeControl(bulb) {
    const wrapper = document.createElement("div");
    wrapper.className = "mode-launch";
    const label = document.createElement("label");
    label.textContent = "Циклический режим";
    const select = document.createElement("select");
    select.className = "bulb-mode-select";
    select.setAttribute("aria-label", `Режим для лампы ${bulb.ip}`);
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "Запустить режим";

    const updateButton = () => {
      const mode = this.getModes().find((item) => item.name === select.value);
      const state = modeButtonState(mode, bulb.ip);
      button.textContent = state.label;
      button.disabled = state.disabled;
    };

    select.addEventListener("change", updateButton);
    button.addEventListener("click", async () => {
      const mode = this.getModes().find((item) => item.name === select.value);
      if (!mode) return;
      try {
        const path = `/api/modes/${encodeURIComponent(mode.name)}`;
        if (mode.running && mode.running_ip === bulb.ip) {
          await this.request(`${path}/stop`, { method: "POST" });
          this.log(`Режим «${mode.name}» остановлен.`, "command");
        } else {
          await this.request(`${path}/start`, {
            method: "POST",
            body: JSON.stringify({ ip: bulb.ip }),
          });
          this.log(`Режим «${mode.name}» запущен на ${bulb.ip}.`, "command");
        }
        await this.refreshModes();
        this.setConnection(true, "Сервер подключён");
      } catch (error) {
        this.log(`Не удалось запустить режим: ${error.message}`, "error");
      }
    });
    wrapper.append(label, select, button);
    this.syncModeOptions(select, updateButton);
    return wrapper;
  }

  syncModeOptions(select, updateButton) {
    const selected = select.value;
    select.replaceChildren();
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = this.getModes().length ? "Выберите режим" : "Сначала создайте режим";
    select.append(placeholder);
    for (const mode of this.getModes()) {
      const option = document.createElement("option");
      option.value = mode.name;
      option.textContent = mode.name;
      select.append(option);
    }
    select.value = this.getModes().some((mode) => mode.name === selected) ? selected : "";
    updateButton();
  }

  updateModeControls() {
    for (const select of this.container.querySelectorAll(".bulb-mode-select")) {
      const updateButton = () => {
        const button = select.parentElement.querySelector("button");
        const mode = this.getModes().find((item) => item.name === select.value);
        const ip = select.closest(".bulb").dataset.ip;
        const state = modeButtonState(mode, ip);
        button.disabled = state.disabled;
        button.textContent = state.label;
      };
      this.syncModeOptions(select, updateButton);
    }
  }

  createRemoveButton(bulb) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "danger";
    button.textContent = "Удалить лампу из списка";
    button.addEventListener("click", async () => {
      if (confirm(`Удалить лампу ${bulb.ip} из списка?`)) {
        await this.runCommand(`remove ${bulb.ip}`);
      }
    });
    return button;
  }
}
