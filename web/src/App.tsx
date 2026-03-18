import { type FormEvent, useEffect, useState } from "react";
import { ActivityPage } from "./pages/ActivityPage";
import { AgentRosterPage } from "./pages/AgentRosterPage";
import { AlertsPage } from "./pages/AlertsPage";
import { ArtifactsPage } from "./pages/ArtifactsPage";
import { BoardPage } from "./pages/BoardPage";
import { EscalationsPage } from "./pages/EscalationsPage";
import { FailuresPage } from "./pages/FailuresPage";
import { GoalTreePage } from "./pages/GoalTreePage";
import { LivePulseProvider, useLiveStatus } from "./lib/useLivePulse";
import { archiveProject, createProject, fetchProjects, restoreProject } from "./lib/controlRoomApi";
import { getSelectedProjectId, setSelectedProjectId } from "./lib/projectScope";
import { OverviewPage } from "./pages/OverviewPage";
import { PortfolioPage } from "./pages/PortfolioPage";
import { ProvidersPage } from "./pages/ProvidersPage";
import { RecoveryPage } from "./pages/RecoveryPage";
import type { ProjectSummary } from "./types";

type View =
  | "portfolio"
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
  { id: "portfolio", label: "Portfolio" },
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

const DEFAULT_PROJECT_FORM = {
  name: "",
  description: "",
  projectType: "custom",
  mode: "auto" as const,
  sourceRoot: ""
};

function AppShell() {
  const [activeView, setActiveView] = useState<View>(getInitialView);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [selectedProjectId, setSelectedProjectIdState] = useState<string | null>(getSelectedProjectId);
  const [projectPanelOpen, setProjectPanelOpen] = useState(false);
  const [projectForm, setProjectForm] = useState(DEFAULT_PROJECT_FORM);
  const [projectNotice, setProjectNotice] = useState<string | null>(null);
  const [projectSubmitting, setProjectSubmitting] = useState(false);
  const { connected, transport } = useLiveStatus();

  const activeProjects = projects.filter((project) => project.state !== "archived");
  const archivedProjects = projects.filter((project) => project.state === "archived");

  async function loadProjects(preferredProjectId?: string | null) {
    const payload = await fetchProjects();
    setProjects(payload.projects);
    const existingSelection = preferredProjectId ?? getSelectedProjectId();
    const nextSelection =
      payload.projects.find((project) => project.project_id === existingSelection && project.state !== "archived")?.project_id ??
      payload.projects.find((project) => project.state !== "archived")?.project_id ??
      null;
    if (nextSelection !== getSelectedProjectId()) {
      setSelectedProjectId(nextSelection);
    }
    setSelectedProjectIdState(nextSelection);
    return payload.projects;
  }

  useEffect(() => {
    let mounted = true;

    async function loadInitialProjects() {
      const payload = await fetchProjects();
      if (!mounted) {
        return;
      }
      setProjects(payload.projects);
      const existingSelection = getSelectedProjectId();
      const nextSelection =
        payload.projects.find((project) => project.project_id === existingSelection && project.state !== "archived")?.project_id ??
        payload.projects.find((project) => project.state !== "archived")?.project_id ??
        null;
      if (nextSelection !== existingSelection) {
        setSelectedProjectId(nextSelection);
      }
      setSelectedProjectIdState(nextSelection);
    }

    void loadInitialProjects();
    return () => {
      mounted = false;
    };
  }, []);

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

  async function handleCreateProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setProjectSubmitting(true);
    setProjectNotice(null);
    try {
      const payload = await createProject({
        actor_id: "agent_allocator",
        name: projectForm.name.trim(),
        description: projectForm.description.trim(),
        project_type: projectForm.projectType.trim() || "custom",
        mode: projectForm.mode,
        source_root: projectForm.sourceRoot.trim() || undefined
      });
      await loadProjects(payload.project.project_id);
      setProjectForm(DEFAULT_PROJECT_FORM);
      setProjectNotice(
        `Created ${payload.project.name} in ${payload.mode} mode from ${payload.metadata.source_root}.`
      );
    } catch (error) {
      setProjectNotice(error instanceof Error ? error.message : "Could not create project.");
    } finally {
      setProjectSubmitting(false);
    }
  }

  async function handleArchiveProject(projectId: string) {
    setProjectSubmitting(true);
    setProjectNotice(null);
    try {
      await archiveProject(projectId);
      await loadProjects(projectId === selectedProjectId ? null : selectedProjectId);
      setProjectNotice("Archived project.");
    } catch (error) {
      setProjectNotice(error instanceof Error ? error.message : "Could not archive project.");
    } finally {
      setProjectSubmitting(false);
    }
  }

  async function handleRestoreProject(projectId: string) {
    setProjectSubmitting(true);
    setProjectNotice(null);
    try {
      await restoreProject(projectId);
      await loadProjects(selectedProjectId);
      setProjectNotice("Restored project.");
    } catch (error) {
      setProjectNotice(error instanceof Error ? error.message : "Could not restore project.");
    } finally {
      setProjectSubmitting(false);
    }
  }

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
          {activeProjects.length > 0 ? (
            <label className="status-chip" htmlFor="project-scope-select">
              <span>Project</span>
              <select
                id="project-scope-select"
                value={selectedProjectId ?? ""}
                onChange={(event) => {
                  const nextProjectId = event.target.value || null;
                  setSelectedProjectId(nextProjectId);
                  setSelectedProjectIdState(nextProjectId);
                }}
              >
                {activeProjects.map((project) => (
                  <option key={project.project_id} value={project.project_id}>
                    {project.name}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          <button
            type="button"
            className={`app-nav__button ${projectPanelOpen ? "is-active" : ""}`}
            onClick={() => setProjectPanelOpen((current) => !current)}
          >
            {projectPanelOpen ? "Hide Projects" : "Manage Projects"}
          </button>
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
        {projectPanelOpen ? (
          <section className="project-panel" aria-label="Project lifecycle">
            <div className="project-panel__section">
              <div>
                <span className="eyebrow">Project Lifecycle</span>
                <h2>Create or import a project</h2>
                <p>Blank source root uses the current MAAS workspace root. Brownfield mode scans an existing repo; greenfield keeps the seeded backlog path.</p>
              </div>
              <form className="project-form" onSubmit={handleCreateProject}>
                <input
                  type="text"
                  placeholder="Project name"
                  value={projectForm.name}
                  onChange={(event) => setProjectForm((current) => ({ ...current, name: event.target.value }))}
                  required
                />
                <input
                  type="text"
                  placeholder="Description"
                  value={projectForm.description}
                  onChange={(event) => setProjectForm((current) => ({ ...current, description: event.target.value }))}
                />
                <div className="project-form__row">
                  <input
                    type="text"
                    placeholder="Type"
                    value={projectForm.projectType}
                    onChange={(event) => setProjectForm((current) => ({ ...current, projectType: event.target.value }))}
                  />
                  <select
                    value={projectForm.mode}
                    onChange={(event) =>
                      setProjectForm((current) => ({
                        ...current,
                        mode: event.target.value as "auto" | "greenfield" | "brownfield"
                      }))
                    }
                  >
                    <option value="auto">Auto</option>
                    <option value="greenfield">Greenfield</option>
                    <option value="brownfield">Brownfield</option>
                  </select>
                </div>
                <input
                  type="text"
                  placeholder="Source root / existing repo path"
                  value={projectForm.sourceRoot}
                  onChange={(event) => setProjectForm((current) => ({ ...current, sourceRoot: event.target.value }))}
                />
                <button type="submit" disabled={projectSubmitting}>
                  {projectSubmitting ? "Working..." : "Create project"}
                </button>
              </form>
              {projectNotice ? <p className="project-panel__notice">{projectNotice}</p> : null}
            </div>

            <div className="project-panel__lists">
              <section className="project-panel__section">
                <div className="project-panel__heading">
                  <h3>Active projects</h3>
                  <span>{activeProjects.length}</span>
                </div>
                {activeProjects.length === 0 ? (
                  <p>No active projects yet.</p>
                ) : (
                  <div className="project-list">
                    {activeProjects.map((project) => (
                      <article key={project.project_id} className="project-card">
                        <div>
                          <strong>{project.name}</strong>
                          <p>{project.description || "No description yet."}</p>
                          <p>
                            {project.onboarding_mode ?? "greenfield"} · {project.task_count} tasks · {project.open_alert_count} open alerts
                          </p>
                        </div>
                        <div className="project-card__actions">
                          <button
                            type="button"
                            onClick={() => {
                              setSelectedProjectId(project.project_id);
                              setSelectedProjectIdState(project.project_id);
                            }}
                          >
                            Open
                          </button>
                          {activeProjects.length > 1 ? (
                            <button
                              type="button"
                              className="button-danger"
                              disabled={projectSubmitting}
                              onClick={() => void handleArchiveProject(project.project_id)}
                            >
                              Archive
                            </button>
                          ) : null}
                        </div>
                      </article>
                    ))}
                  </div>
                )}
              </section>

              <section className="project-panel__section">
                <div className="project-panel__heading">
                  <h3>Archived projects</h3>
                  <span>{archivedProjects.length}</span>
                </div>
                {archivedProjects.length === 0 ? (
                  <p>No archived projects.</p>
                ) : (
                  <div className="project-list">
                    {archivedProjects.map((project) => (
                      <article key={project.project_id} className="project-card">
                        <div>
                          <strong>{project.name}</strong>
                          <p>{project.description || "No description yet."}</p>
                          <p>
                            Archived {project.archived_at ?? "recently"} · {project.task_count} tasks
                          </p>
                        </div>
                        <div className="project-card__actions">
                          <button
                            type="button"
                            disabled={projectSubmitting}
                            onClick={() => void handleRestoreProject(project.project_id)}
                          >
                            Restore
                          </button>
                        </div>
                      </article>
                    ))}
                  </div>
                )}
              </section>
            </div>
          </section>
        ) : null}
      </header>

      <div className="app-content">
        {activeView === "overview" ? <OverviewPage /> : null}
        {activeView === "portfolio" ? <PortfolioPage /> : null}
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
