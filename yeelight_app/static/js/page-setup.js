import { startPage } from "./page.js";

const $ = (selector) => document.querySelector(selector);
let apiRequest = null;
let log = () => {};
let lanControlSubmitting = false;

function wifiPasswordError(password) {
  if (!password) return "Введите пароль Wi-Fi.";
  if (password.includes("\u0000")) return "Пароль не должен содержать нулевой символ.";
  const length = new TextEncoder().encode(password).length;
  if (length === 64 && /^[0-9a-fA-F]{64}$/.test(password)) return "";
  if (length < 8 || length > 63) {
    return `Пароль Wi-Fi должен содержать от 8 до 63 символов, сейчас ${length}.`;
  }
  return "";
}

async function submitWifiSetup(event) {
  event.preventDefault();
  const submit = $("#wifi-submit");
  const result = $("#wifi-result");
  const lanControlResult = $("#wifi-lan-control-result");
  const passwordInput = $("#wifi-password");
  const lanControlInput = $("#wifi-enable-lan-control");
  const enableLanControl = lanControlInput.checked;
  const payload = {
    ip: $("#wifi-ip").value.trim(),
    ssid: $("#wifi-ssid").value,
    password: passwordInput.value,
    enable_lan_control: enableLanControl,
  };
  const passwordError = wifiPasswordError(payload.password);
  if (passwordError) {
    result.textContent = passwordError;
    result.classList.add("error");
    lanControlResult.textContent = "Попытка включения LAN Control не выполнялась: запрос отклонён до отправки.";
    lanControlResult.classList.remove("warning", "error");
    passwordInput.focus();
    return;
  }
  submit.disabled = true;
  result.textContent = "Отправка запроса…";
  lanControlResult.classList.remove("error");
  lanControlResult.classList.remove("warning");
  lanControlResult.textContent = enableLanControl
    ? "Попытка включить LAN Control будет выполнена до настройки Wi-Fi…"
    : "Попытка включения LAN Control не запрашивалась.";
  lanControlInput.checked = false;
  try {
    const response = await apiRequest("/api/provisioning/wifi", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    result.textContent = response.message;
    result.classList.toggle(
      "error",
      response.status === "rejected" || response.status === "failed",
    );
    log(
      response.message,
      response.status === "rejected" || response.status === "failed"
        ? "error"
        : "command",
    );
    lanControlResult.textContent = response.lan_control_message;
    lanControlResult.classList.toggle(
      "error",
      !["not_requested", "responded_unverified"].includes(
        response.lan_control_status,
      ),
    );
    lanControlResult.classList.toggle(
      "warning",
      response.lan_control_status === "responded_unverified",
    );
    log(
      response.lan_control_message,
      response.lan_control_status === "rejected" ||
        response.lan_control_status === "failed"
        ? "error"
        : "command",
    );
  } catch (error) {
    const errorPayload =
      error.payload && typeof error.payload === "object" ? error.payload : null;
    const notSent = error.httpStatus === 422;
    result.textContent = errorPayload?.message
      || `Не удалось отправить настройки: ${error.message}`;
    result.classList.add("error");
    if (errorPayload?.lan_control_message) {
      lanControlResult.textContent = errorPayload.lan_control_message;
    } else if (notSent) {
      lanControlResult.textContent =
        "Попытка включения LAN Control не выполнялась: запрос отклонён до отправки.";
    } else if (enableLanControl) {
      lanControlResult.textContent =
        "Не удалось получить результат попытки включения LAN Control; проверьте состояние лампы.";
    }
    if (enableLanControl && !notSent) lanControlResult.classList.add("error");
    lanControlResult.classList.remove("warning");
    log(`Настройки Wi-Fi не отправлены: ${error.message}`, "error");
  } finally {
    payload.password = "";
    passwordInput.value = "";
    lanControlInput.checked = false;
    submit.disabled = false;
  }
}

async function submitLanControl() {
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

startPage({
  create(context) {
    apiRequest = context.request;
    log = context.log;
    $("#wifi-form").addEventListener("submit", submitWifiSetup);
    $("#lan-control-form").addEventListener("submit", (event) => {
      event.preventDefault();
      submitLanControl();
    });
    $("#lan-control-submit").addEventListener("click", submitLanControl);
  },

  unauthorized(context, message) {
    const result = $("#wifi-result");
    if (result) result.textContent = message;
  },
});
