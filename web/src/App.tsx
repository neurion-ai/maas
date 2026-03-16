import { useEffect, useState } from "react";
import { ActivityPage } from "./pages/ActivityPage";
import { AgentRosterPage } from "./pages/AgentRosterPage";
import { AlertsPage } from "./pages/AlertsPage";
import { ArtifactsPage } from "./pages/ArtifactsPage";
import { BoardPage } from "./pages/BoardPage";
import { EscalationsPage } from "./pages/EscalationsPage";
import { FailuresPage } from "./pages/FailuresPage";
import { GoalTreePage } from "./pages/GoalTreePage";
import { LivePulseProvider, useLiveStatus } from "./lib/useLivePulse";
import { OverviewPage } from "./pages/OverviewPage";
import { ProvidersPage } from "./pages/ProvidersPage";
import { RecoveryPage } from "./pages/RecoveryPage";

type View =
  | "overview"
  | "board"
  | "goals"
  | "agents"
  | "activity"
  | "artifacts"
  | "providers"
  | "recovery"
  | "failures"
  | "alerts"
  | "escalations";

const VIEWS: { id: View; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "board", label: "Board" },
  { id: "goals", label: "Goal Tree" },
  { id: "agents", label: "Agent Roster" },
  { id: "activity", label: "Activity" },
  { id: "artifacts", label: "Artifacts" },
  { id: "providers", label: "Providers" },
  { id: "recovery", label: "Recovery" },
  { id: "failures", label: "Failures" },
  { id: "alerts", label: "Alerts" },
  { id: "escalations", label: "Escalations" }
];

function getInitialView(): View {
  const hash = window.location.hash.replace("#", "");
  return (VIEWS.find((view) => view.id === hash)?.id ?? "overview") as View;
}

function AppShell() {
  const [activeView, setActiveView] = useState<View>(getInitialView);
  const { connected, transport } = useLiveStatus();

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

  const liveTransportLabel =
    transport === "websocket"
      ? connected
        ? "Live via WebSocket"
        : "Connecting WebSocket"
      : transport === "sse"
        ? connected
          ? "Live via SSE"
          : "Connecting SSE"
        : "Polling fallback";

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="app-header__top">
          <div>
            <span className="eyebrow">MAAS</span>
            <h1>Multi-agent control room</h1>
          </div>
          <div className="status-chip">
            <span className={`status-chip__dot ${connected ? "is-live" : transport === "polling" ? "is-warn" : ""}`} />
            {liveTransportLabel}
          </div>
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
        {activeView === "artifacts" ? <ArtifactsPage /> : null}
        {activeView === "providers" ? <ProvidersPage /> : null}
        {activeView === "recovery" ? <RecoveryPage /> : null}
        {activeView === "failures" ? <FailuresPage /> : null}
        {activeView === "alerts" ? <AlertsPage /> : null}
        {activeView === "escalations" ? <EscalationsPage /> : null}
      </div>
    </div>
  );
}

export default function App() {
  return (
    <LivePulseProvider>
      <AppShell />
    </LivePulseProvider>
  );
}
