const form = document.querySelector("#login-form");
const errorBox = document.querySelector("#login-error");
const submit = document.querySelector("#login-submit");
const username = document.querySelector("#login-username");
const password = document.querySelector("#login-password");

function showError(message) {
  errorBox.hidden = false;
  errorBox.textContent = message;
}

function safeNext(value) {
  if (!value || !value.startsWith("/") || value.startsWith("//") || value.includes("\\")) {
    return "/";
  }
  return value;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  errorBox.hidden = true;
  submit.disabled = true;
  submit.textContent = "Проверяем…";
  try {
    const response = await fetch("/api/v1/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({
        username: username.value.trim(),
        password: password.value,
      }),
    });
    let body = {};
    try {
      body = await response.json();
    } catch {
      body = {};
    }
    if (!response.ok) {
      if (response.status === 429) {
        throw new Error("Слишком много попыток. Подождите минуту.");
      }
      throw new Error(body.detail || "Неверный пользователь или пароль.");
    }
    password.value = "";
    window.location.assign(safeNext(form.dataset.next));
  } catch (error) {
    showError(error.message || "Не удалось войти.");
    submit.disabled = false;
    submit.textContent = "Войти";
  }
});
