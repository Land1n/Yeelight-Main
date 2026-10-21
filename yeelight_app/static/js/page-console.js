import { runCommand, startPage } from "./page.js";

const $ = (selector) => document.querySelector(selector);
let context = null;

startPage({
  create(page) {
    context = page;
    const commandInput = $("#command");
    $("#command-form").addEventListener("submit", (event) => {
      event.preventDefault();
      const text = commandInput.value;
      commandInput.value = "";
      runCommand(context, text);
    });
    document.querySelectorAll("[data-command]").forEach((button) => {
      button.addEventListener("click", () => {
        const value = button.dataset.command;
        commandInput.value = value;
        commandInput.focus();
        if (value === "add ") return;
        commandInput.value = "";
        runCommand(context, value);
      });
    });
    document.querySelectorAll("#commands-table code").forEach((code) => {
      const text = code.textContent;
      if (!text || text.includes("&lt;")) return;
      const row = code.closest("tr");
      if (!row) return;
      row.style.cursor = "pointer";
      row.title = "Подставить в поле ввода";
      row.addEventListener("click", () => {
        commandInput.value = text.replace(/\s+/g, " ").trim();
        commandInput.focus();
      });
    });
    context.log("Консоль готова. Команды: discover, list, add, remove, on, off, toggle, status, brightness, color, temp.", "command");
  },
});
