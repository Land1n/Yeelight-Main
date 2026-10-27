export default function Help() {
  return (
    <>
      <div className="page-head">
        <div>
          <span className="eyebrow">Справка</span>
          <h1>Как пользоваться</h1>
        </div>
      </div>

      <section className="card">
        <ol className="steps">
          <li className="step">
            <span className="step-number">1</span>
            <div className="step-body">
              <h3>Запустите агент</h3>
              <p>Агент (manager) должен работать на компьютере в той же сети, что и лампы.</p>
            </div>
          </li>
          <li className="step">
            <span className="step-number">2</span>
            <div className="step-body">
              <h3>Добавьте лампы</h3>
              <p>На вкладке «Лампы» укажите IP-адрес или выполните поиск в сети.</p>
            </div>
          </li>
          <li className="step">
            <span className="step-number">3</span>
            <div className="step-body">
              <h3>Создайте режим</h3>
              <p>На вкладке «Режимы» соберите шаги и запустите режим для выбранной лампы.</p>
            </div>
          </li>
        </ol>
      </section>
    </>
  );
}
