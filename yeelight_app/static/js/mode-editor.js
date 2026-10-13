const ACTIONS = [
  ["on", "Включить"],
  ["off", "Выключить"],
  ["toggle", "Переключить"],
  ["brightness", "Задать яркость"],
  ["color", "Задать цвет"],
  ["temp", "Задать температуру"],
  ["status", "Проверить состояние"],
];

export class ModeEditor {
  constructor(container) {
    this.container = container;
    this.steps = [];
  }

  setSteps(steps) {
    this.steps = steps.map((step) => ({
      action: step.action,
      values: [...step.values],
    }));
    this.render();
  }

  addStep() {
    this.steps.push({ action: "on", values: [] });
    this.render();
  }

  clear() {
    this.steps = [];
    this.render();
  }

  render() {
    this.container.replaceChildren();
    this.steps.forEach((step, index) => {
      const row = document.createElement("div");
      row.className = "task-item";
      row.append(this.createActionSelect(step, index));
      row.append(this.createValueEditor(step));
      row.append(this.createControls(index));
      this.container.append(row);
    });
  }

  createActionSelect(step, index) {
    const action = document.createElement("select");
    action.setAttribute("aria-label", `Действие задачи ${index + 1}`);
    for (const [value, label] of ACTIONS) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      action.append(option);
    }
    action.value = step.action;
    action.addEventListener("change", () => {
      step.action = action.value;
      step.values = step.action === "color"
        ? [255, 255, 255]
        : step.action === "temp"
          ? [4000]
          : step.action === "brightness"
            ? [100]
            : [];
      this.render();
    });
    return action;
  }

  createValueEditor(step) {
    if (step.action === "brightness") {
      return this.createSlider(step, {
        label: "Яркость в процентах",
        min: 1,
        max: 100,
        format: (value) => `${value}%`,
      });
    }
    if (step.action === "temp") {
      const value = this.createSlider(step, {
        label: "Цветовая температура, K",
        min: 1700,
        max: 6500,
        step: 100,
        format: (current) => `${current} K`,
      });
      value.querySelector("input").classList.add("temperature-slider");
      return value;
    }
    if (step.action === "color") {
      const picker = document.createElement("input");
      picker.type = "color";
      picker.value = `#${step.values.map((value) => Number(value).toString(16).padStart(2, "0")).join("")}`;
      picker.setAttribute("aria-label", "Цвет задачи");
      picker.addEventListener("input", () => {
        step.values = [1, 3, 5].map((offset) => parseInt(picker.value.slice(offset, offset + 2), 16));
      });
      return picker;
    }
    const description = document.createElement("span");
    description.textContent = taskDescription(step);
    return description;
  }

  createSlider(step, { label, min, max, step: increment = 1, format }) {
    const value = document.createElement("div");
    value.className = "task-value";
    const slider = document.createElement("input");
    slider.type = "range";
    slider.min = String(min);
    slider.max = String(max);
    slider.step = String(increment);
    slider.value = step.values[0];
    slider.setAttribute("aria-label", label);
    const output = document.createElement("output");
    output.textContent = format(step.values[0]);
    slider.addEventListener("input", () => {
      step.values[0] = Number(slider.value);
      output.textContent = format(slider.value);
    });
    value.append(slider, output);
    return value;
  }

  createControls(index) {
    const controls = document.createElement("div");
    controls.className = "task-controls";
    controls.append(
      this.createMoveButton(index, -1, "↑", "Переместить шаг выше"),
      this.createMoveButton(index, 1, "↓", "Переместить шаг ниже"),
    );
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "danger";
    remove.textContent = "Убрать";
    remove.addEventListener("click", () => {
      this.steps.splice(index, 1);
      this.render();
    });
    controls.append(remove);
    return controls;
  }

  createMoveButton(index, offset, text, title) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = text;
    button.title = title;
    button.disabled = index + offset < 0 || index + offset >= this.steps.length;
    button.addEventListener("click", () => {
      const target = index + offset;
      if (target < 0 || target >= this.steps.length) return;
      [this.steps[index], this.steps[target]] = [this.steps[target], this.steps[index]];
      this.render();
    });
    return button;
  }
}

export function taskDescription(step) {
  const labels = {
    on: "Вкл",
    off: "Выкл",
    toggle: "Перекл.",
    status: "Статус",
    brightness: `Яркость ${step.values[0]}%`,
    color: `RGB(${step.values.join(", ")})`,
    temp: `${step.values[0]} K`,
  };
  return labels[step.action] || step.action;
}

export function modeSummary(steps) {
  const descriptions = steps.map(taskDescription);
  if (descriptions.length <= 2) return descriptions.join(" → ");
  return `${descriptions[0]} → … → ${descriptions[descriptions.length - 1]}`;
}
