import { useState } from "react";

// Карточка лампы: питание, яркость, цвет и температура.
// Все изменения уходят через onAction (объект действия).
export default function BulbCard({ bulb, onAction }) {
  const props = bulb.props ?? {};
  const [bright, setBright] = useState(props.bright ?? 50);
  const [hex, setHex] = useState("#ffffff");
  const [kelvin, setKelvin] = useState(props.ct ?? 4000);
  const online = Boolean(bulb.online);

  const command = (cmd) => onAction({ kind: "command", command: { ...cmd, ip: bulb.ip } });

  const parseHex = (value) => {
    const match = /^#?([0-9a-fA-F]{6})$/.exec(value.trim());
    return match ? match[1] : null;
  };

  const applyHex = () => {
    const clean = parseHex(hex);
    if (clean) {
      command({ type: "set_hex", value: clean });
    }
  };

  return (
    <article className="bulb">
      <div className="bulb-info">
        <span className="bulb-ip">
          <span className={`bulb-dot ${online ? "online" : "offline"}`} /> {bulb.ip}
        </span>
        <span className="bulb-state">{props.power ?? "нет данных"}</span>
        <span className="bulb-current">
          Яркость: {props.bright ?? "—"} · Температура: {props.ct ?? "—"} K
        </span>
      </div>

      <div className="settings">
        <div className="connection-actions">
          <button className="btn btn-primary" type="button" onClick={() => command({ type: "turn_on" })}>
            Вкл
          </button>
          <button className="btn btn-ghost" type="button" onClick={() => command({ type: "turn_off" })}>
            Выкл
          </button>
          <button className="btn btn-ghost" type="button" onClick={() => command({ type: "toggle" })}>
            Переключить
          </button>
          <button className="btn btn-ghost" type="button" onClick={() => onAction({ kind: "undo", ip: bulb.ip })}>
            Откатить
          </button>
        </div>

        <label className="field">
          Яркость: {bright}%
          <input
            type="range"
            min="1"
            max="100"
            value={bright}
            onChange={(e) => setBright(Number(e.target.value))}
            onMouseUp={() => command({ type: "set_brightness", value: bright })}
            onTouchEnd={() => command({ type: "set_brightness", value: bright })}
          />
        </label>

        <label className="field">
          Цвет
          <input value={hex} onChange={(e) => setHex(e.target.value)} onBlur={applyHex} />
        </label>

        <label className="field">
          Температура: {kelvin} K
          <input
            type="range"
            min="1700"
            max="6500"
            step="50"
            value={kelvin}
            onChange={(e) => setKelvin(Number(e.target.value))}
            onMouseUp={() => command({ type: "set_color_temp", kelvin })}
            onTouchEnd={() => command({ type: "set_color_temp", kelvin })}
          />
        </label>

        <div className="connection-actions">
          <button className="btn btn-ghost" type="button" onClick={() => onAction({ kind: "remove", ip: bulb.ip })}>
            Удалить
          </button>
        </div>
      </div>
    </article>
  );
}
