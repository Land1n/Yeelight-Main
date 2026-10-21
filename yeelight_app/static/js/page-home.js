import { startPage } from "./page.js";

const $ = (selector) => document.querySelector(selector);

function setText(id, value) {
  const element = $(id);
  if (element) element.textContent = value;
}

async function refreshSummary(context) {
  const bulbs = await context.request("/api/bulbs");
  const modes = await context.request("/api/modes");
  const running = modes.modes.filter((mode) => mode.running);
  setText("#summary-bulbs", String(bulbs.bulbs.length));
  setText("#summary-modes", String(modes.modes.length));
  setText(
    "#summary-running",
    running.length
      ? running.map((mode) => `${mode.name} → ${mode.running_ip}`).join(", ")
      : "нет режимов",
  );
}

startPage({
  panel: null,

  async ready(context) {
    try {
      await refreshSummary(context);
    } catch (error) {
      context.log(`Сводка не обновлена: ${error.message}`, "error");
    }
  },

  async tick(context) {
    await refreshSummary(context);
  },

  unauthorized() {
    setText("#summary-bulbs", "—");
    setText("#summary-modes", "—");
    setText("#summary-running", "нужен токен");
  },
});
