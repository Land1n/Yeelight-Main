import { useState } from "react";
import { useManagerState } from "./api.js";
import Home from "./pages/Home.jsx";
import Bulbs from "./pages/Bulbs.jsx";
import Modes from "./pages/Modes.jsx";
import Console from "./pages/Console.jsx";
import Help from "./pages/Help.jsx";

const PAGES = [
  { key: "home", title: "Главная", component: Home },
  { key: "bulbs", title: "Лампы", component: Bulbs },
  { key: "modes", title: "Режимы", component: Modes },
  { key: "console", title: "Консоль", component: Console },
  { key: "help", title: "Справка", component: Help },
];

export default function App() {
  const [current, setCurrent] = useState("home");
  const { state, error } = useManagerState();
  const online = Boolean(state?.online);
  const page = PAGES.find((item) => item.key === current) ?? PAGES[0];
  const Page = page.component;

  return (
    <>
      <div className="backdrop" aria-hidden="true">
        <div className="backdrop-glow" />
        <div className="backdrop-grid" />
      </div>

      <header className="topbar">
        <div className="topbar-inner">
          <div className="brand">
            <span className="brand-mark">
              <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
                <path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2.1h5c0-.9.4-1.6 1-2.1A6 6 0 0 0 12 3z" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </span>
            <span className="brand-text">
              Yeelight <em>Manager</em>
            </span>
          </div>

          <nav className="topnav">
            {PAGES.map((item) => (
              <button
                key={item.key}
                type="button"
                className={item.key === current ? "active" : ""}
                onClick={() => setCurrent(item.key)}
              >
                {item.title}
              </button>
            ))}
          </nav>

          <div className="connection" title={error ?? ""}>
            <span className={`dot ${online ? "ok" : "error"}`} />
            <span>{online ? "Агент online" : "Агент offline"}</span>
          </div>
        </div>
      </header>

      <main className="shell">
        <Page state={state} />
      </main>

      <footer className="footer">
        <div className="footer-links">
          <span>Yeelight Manager</span>
        </div>
      </footer>
    </>
  );
}
