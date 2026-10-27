import { useState } from "react";
import { send } from "../api.js";

const EMPTY_STEP = { type: "turn_on", ip: "", value: "" };

// Шаг режима: без ip (ip подставляется при запуске режима).
function stepFromForm(form) {
  const step = { type: form.type };
  if (form.type === "set_brightness") step.value = Number(form.value);
  if (form.type === "set_hex") step.value = form.value.replace("#", "");
  if (form.type === "set_color_temp") step.kelvin = Number(form.value);
  return step;
}

export default function Modes({ state }) {
  const modes = state?.modes ?? [];
  const lamps = state?.lamps ?? [];
  const [name, setName] = useState("");
  const [delay, setDelay] = useState(1);
  const [steps, setSteps] = useState([]);
  const [draft, setDraft] = useState(EMPTY_STEP);
  const [ip, setIp] = useState("");
  const [error, setError] = useState(null);

  const run = (action) =>
    send(action).then(
      () => setError(null),
      (err) => setError(err.message),
    );

  const save = () => {
    run({ kind: "mode_save", mode: { name, steps, delay_seconds: Number(delay) } });
  };

  return (
    <>
      <div className="page-head">
        <div>
          <span className="eyebrow">Сценарии</span>
          <h1>Режимы</h1>
          <p className="lead">Последовательности команд для ламп.</p>
        </div>
      </div>

      {error && <div className="notice">{error}</div>}

      <section className="card">
        <div className="card-head">
          <div className="card-heading">
            <span className="icon-chip">+</span>
            <h2>Новый режим</h2>
          </div>
        </div>
        <div className="mode-form">
          <div className="mode-fields">
            <label className="field">
              Название
              <input value={name} onChange={(e) => setName(e.target.value)} />
            </label>
            <label className="field">
              Пауза между шагами, с
              <input type="number" min="0" step="0.1" value={delay} onChange={(e) => setDelay(e.target.value)} />
            </label>
          </div>

          <ol className="steps">
            {steps.map((step, index) => (
              <li className="step" key={index}>
                <span className="step-number">{index + 1}</span>
                <div className="step-body">
                  <h3>{step.type}</h3>
                  <p>{JSON.stringify(step)}</p>
                  <button
                    className="btn btn-ghost"
                    type="button"
                    onClick={() => setSteps(steps.filter((_, i) => i !== index))}
                  >
                    Убрать
                  </button>
                </div>
              </li>
            ))}
          </ol>

          <div className="mode-fields">
            <label className="field">
              Команда
              <select value={draft.type} onChange={(e) => setDraft({ ...draft, type: e.target.value })}>
                <option value="turn_on">Вкл</option>
                <option value="turn_off">Выкл</option>
                <option value="set_brightness">Яркость (1–100)</option>
                <option value="set_hex">Цвет (hex)</option>
                <option value="set_color_temp">Температура (K)</option>
              </select>
            </label>
            <label className="field">
              Значение
              <input value={draft.value} onChange={(e) => setDraft({ ...draft, value: e.target.value })} />
            </label>
          </div>
          <div className="mode-form-actions">
            <button
              className="btn btn-ghost"
              type="button"
              onClick={() => {
                setSteps([...steps, stepFromForm(draft)]);
                setDraft(EMPTY_STEP);
              }}
            >
              Добавить шаг
            </button>
            <button className="btn btn-primary" type="button" onClick={save} disabled={!name.trim() || !steps.length}>
              Сохранить режим
            </button>
          </div>
        </div>
      </section>

      <section className="card">
        <div className="card-head">
          <div className="card-heading">
            <span className="icon-chip">▶</span>
            <h2>Список режимов</h2>
          </div>
        </div>
        <div className="mode-ip">
          <span>Лампа для запуска:</span>
          <select value={ip} onChange={(e) => setIp(e.target.value)}>
            <option value="">выберите</option>
            {lamps.map((lamp) => (
              <option key={lamp.ip} value={lamp.ip}>{lamp.ip}</option>
            ))}
          </select>
        </div>
        {modes.length === 0 ? (
          <div className="empty">Режимов пока нет.</div>
        ) : (
          <div className="mode-list">
            {modes.map((mode) => (
              <div className="mode" key={mode.name}>
                <div className="mode-info">
                  <strong>{mode.name}</strong>
                  <div className="mode-commands">{mode.steps.length} шаг(ов), пауза {mode.delay_seconds} с</div>
                  {mode.last_error && <div className="field-hint">Ошибка: {mode.last_error}</div>}
                </div>
                <div className="actions">
                  {mode.running ? (
                    <button className="btn btn-ghost" type="button" onClick={() => run({ kind: "mode_stop", name: mode.name })}>
                      Остановить
                    </button>
                  ) : (
                    <button
                      className="btn btn-primary"
                      type="button"
                      disabled={!ip}
                      onClick={() => run({ kind: "mode_start", name: mode.name, ip })}
                    >
                      Запустить
                    </button>
                  )}
                  <button className="btn btn-ghost" type="button" onClick={() => run({ kind: "mode_delete", name: mode.name })}>
                    Удалить
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </>
  );
}
