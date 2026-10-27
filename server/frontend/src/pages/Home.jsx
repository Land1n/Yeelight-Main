export default function Home({ state }) {
  const lamps = state?.lamps ?? [];
  const modes = state?.modes ?? [];
  const running = modes.filter((mode) => mode.running);

  return (
    <>
      <div className="page-head">
        <div>
          <span className="eyebrow">Обзор</span>
          <h1>Главная</h1>
          <p className="lead">Состояние агента, ламп и запущенных режимов.</p>
        </div>
      </div>

      <section className="card">
        <div className="card-head">
          <div className="card-heading">
            <span className="icon-chip">●</span>
            <h2>Агент</h2>
          </div>
          <span className={`pill ${state?.online ? "" : "pill-warn"}`}>
            {state?.online ? "online" : "offline"}
          </span>
        </div>
        <dl className="summary">
          <dt>Ламп</dt>
          <dd>{lamps.length}</dd>
          <dt>Запущено режимов</dt>
          <dd>{running.length}</dd>
        </dl>
        {running.length > 0 && (
          <p className="section-intro">Запущены: {running.map((mode) => mode.name).join(", ")}</p>
        )}
      </section>

      <div className="nav-cards">
        <span className="nav-card">Лампы: управление яркостью, цветом и температурой.</span>
        <span className="nav-card">Режимы: сценарии с шагами для ламп.</span>
      </div>
    </>
  );
}
