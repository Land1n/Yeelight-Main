import { BulbList } from "./bulbs.js";
import { $, empty, runCommand, startPage } from "./page.js";

let bulbs;
let modes = [];

async function loadModes(context) {
  const data = await context.request("/api/modes");
  modes = data.modes;
  bulbs?.updateModeControls();
  return modes;
}

async function refreshAll(context) {
  await bulbs.refresh();
  await loadModes(context);
  updateCount();
}

function updateCount() {
  const pill = $("#bulbs-count");
  if (!pill) return;
  const online = bulbs.bulbs.filter((bulb) => bulb.online === true).length;
  pill.textContent = bulbs.bulbs.length
    ? `${bulbs.bulbs.length} шт. · отвечают: ${online}`
    : "пусто";
}

async function loadMonitorSettings(context) {
  const pill = $("#monitor-settings");
  if (!pill) return;
  try {
    const settings = await context.request("/api/settings");
    pill.textContent =
      `Проверка ламп каждые ${settings.poll_interval_seconds} сек. ` +
      `Удаление после ${settings.offline_timeout_seconds} сек. без ответа (настройки сервера).`;
  } catch (error) {
    pill.textContent = `Настройки мониторинга не получены: ${error.message}`;
  }
}

startPage({
  create(context) {
    bulbs = new BulbList($("#bulbs"), {
      request: context.request,
      runCommand: (text) => runCommand(context, text),
      log: context.log,
      setConnection: context.setConnection,
      getModes: () => modes,
      refreshModes: () => loadModes(context),
    });

    $("#discover").addEventListener("click", async () => {
      const button = $("#discover");
      button.disabled = true;
      button.textContent = "Ищем лампы…";
      try {
        await runCommand(context, "discover");
        if (context.authorized) await refreshAll(context);
      } finally {
        button.disabled = false;
        button.textContent = "Найти лампы";
      }
    });
  },

  async ready(context) {
    await refreshAll(context);
    await loadMonitorSettings(context);
  },

  async tick(context) {
    await bulbs.refresh();
    await loadModes(context);
    updateCount();
  },

  unauthorized(context, message) {
    const list = $("#bulbs");
    if (!list) return;
    list.replaceChildren(empty(message));
    const pill = $("#bulbs-count");
    if (pill) pill.textContent = "";
  },
});
