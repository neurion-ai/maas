import { useEffect, useState } from "react";
import { ActivityPage } from "./pages/ActivityPage";
import { AgentRosterPage } from "./pages/AgentRosterPage";
import { BoardPage } from "./pages/BoardPage";
import { GoalTreePage } from "./pages/GoalTreePage";
import { OverviewPage } from "./pages/OverviewPage";

type View = "overview" | "board" | "goals" | "agents" | "activity";

const VIEWS: { id: View; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "board", label: "Board" },
  { id: "goals", label: "Goal Tree" },
  { id: "agents", label: "Agent Roster" },
  { id: "activity", label: "Activity" }
];

function getInitialView(): View {
  const hash = window.location.hash.replace("#", "");
  return (VIEWS.find((view) => view.id === hash)?.id ?? "overview") as View;
}

export default function App() {
  const [activeView, setActiveView] = useState<View>(getInitialView);

  useEffect(() => {
    window.location.hash = activeView;
  }, [activeView]);

  useEffect(() => {
    function handleHashChange() {
      const nextView = getInitialView();
      setActiveView((current) => (current === nextView ? current : nextView));
    }

    window.addEventListener("hashchange", handleHashChange);
    return () => {
      window.removeEventListener("hashchange", handleHashChange);
    };
  }, []);

  return (
    <div className="app-shell">
      <header className="app-header">
        <div>
          <span className="eyebrow">MAAS</span>
          <h1>Multi-agent control room</h1>
        </div>
        <nav className="app-nav" aria-label="MAAS views">
          {VIEWS.map((view) => (
            <button
              key={view.id}
              type="button"
              className={`app-nav__button ${activeView === view.id ? "is-active" : ""}`}
              onClick={() => setActiveView(view.id)}
            >
              {view.label}
            </button>
          ))}
        </nav>
      </header>

      <div className="app-content">
        {activeView === "overview" ? <OverviewPage /> : null}
        {activeView === "board" ? <BoardPage /> : null}
        {activeView === "goals" ? <GoalTreePage /> : null}
        {activeView === "agents" ? <AgentRosterPage /> : null}
        {activeView === "activity" ? <ActivityPage /> : null}
      </div>
    </div>
  );
}
