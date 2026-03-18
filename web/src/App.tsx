import { type FormEvent, useEffect, useMemo, useState } from "react";
import { CommandPalette, type CommandPaletteAction } from "./components/CommandPalette";
import {
  archiveProject,
  createProject,
  fetchProjects,
  restoreProject,
  runOrchestratorPass,
  runSupervisorPass
} from "./lib/controlRoomApi";
import { getSelectedProjectId, setSelectedProjectId as persistSelectedProjectId } from "./lib/projectScope";
import { LivePulseProvider, useLiveStatus } from "./lib/useLivePulse";
import { HomePage } from "./pages/HomePage";
import { IncidentsPage } from "./pages/IncidentsPage";
import { ProjectsPage, type ProjectFormState } from "./pages/ProjectsPage";
import { RunsPage } from "./pages/RunsPage";
import { WorkPage } from "./pages/WorkPage";
import type { ProjectSummary } from "./types";

type View = "home" | "work" | "runs" | "incidents" | "projects";
type ThemeMode = "light" | "dark";

const THEME_STORAGE_KEY = "maas:theme";

const VIEWS: Array<{ id: View; label: string; summary: string }> = [
  {
    id: "home",
    label: "Cockpit",
    summary: "Supervisor overview for agents, incident pressure, and the next operator decision."
  },
  {
    id: "work",
    label: "Board",
    summary: "The only task workspace: kanban in the center, inspector on the right."
  },
  {
    id: "runs",
    label: "Execution",
    summary: "Providers, workers, queued jobs, and runtime outputs."
  },
  {
    id: "incidents",
    label: "Incidents",
    summary: "Recovery queues, alerts, failures, and incident replay."
  },
  {
    id: "projects",
    label: "Projects",
    summary: "Portfolio health, project lifecycle, and multi-project supervision."
  }
];

const DEFAULT_PROJECT_FORM: ProjectFormState = {
  name: "",
  description: "",
  projectType: "custom",
  mode: "auto",
  sourceRoot: ""
};

function getInitialView(): View {
  const hash = window.location.hash.replace("#", "");
  return (VIEWS.find((view) => view.id === hash)?.id ?? "home") as View;
}

function getInitialTheme(): ThemeMode {
  const savedTheme = window.localStorage.getItem(THEME_STORAGE_KEY);
  if (savedTheme === "light" || savedTheme === "dark") {
    return savedTheme;
  }
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function AppShell() {
  const [activeView, setActiveView] = useState<View>(getInitialView);
  const [theme, setTheme] = useState<ThemeMode>(getInitialTheme);
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(getSelectedProjectId);
  const [projectForm, setProjectForm] = useState<ProjectFormState>(DEFAULT_PROJECT_FORM);
  const [projectNotice, setProjectNotice] = useState<string | null>(null);
  const [projectSubmitting, setProjectSubmitting] = useState(false);
  const { connected, transport } = useLiveStatus();

  const activeProjects = projects.filter((project) => project.state !== "archived");
  const activeProject =
    activeProjects.find((project) => project.project_id === selectedProjectId) ?? activeProjects[0] ?? null;

  async function loadProjects(preferredProjectId?: string | null) {
    const payload = await fetchProjects();
    setProjects(payload.projects);
    const existingSelection = preferredProjectId ?? getSelectedProjectId();
    const nextSelection =
      payload.projects.find((project) => project.project_id === existingSelection && project.state !== "archived")
        ?.project_id ??
      payload.projects.find((project) => project.state !== "archived")?.project_id ??
      null;
    persistSelectedProjectId(nextSelection);
    setSelectedProjectId(nextSelection);
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
        payload.projects.find((project) => project.project_id === existingSelection && project.state !== "archived")
          ?.project_id ??
        payload.projects.find((project) => project.state !== "archived")?.project_id ??
        null;
      persistSelectedProjectId(nextSelection);
      setSelectedProjectId(nextSelection);
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

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  }, [theme]);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setCommandPaletteOpen((current) => !current);
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, []);

  const liveTransportTone = connected ? (transport === "polling" ? "warn" : "good") : transport === "polling" ? "warn" : "default";
  const liveTransportLabel = connected
    ? transport === "websocket"
      ? "Live"
      : transport === "sse"
        ? "Fallback live"
        : "Polling"
    : transport === "websocket"
      ? "Syncing"
      : transport === "sse"
        ? "Retrying"
        : "Polling";
  const liveTransportDetail = connected
    ? transport === "websocket"
      ? "Live updates active"
      : transport === "sse"
        ? "Server stream fallback"
        : "Polling every 15s"
    : transport === "websocket"
      ? "Opening live stream"
      : transport === "sse"
        ? "Retrying live stream"
        : "Live transport unavailable";

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
      setActiveView("home");
      setProjectNotice(`Created ${payload.project.name} in ${payload.mode} mode from ${payload.metadata.source_root}.`);
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

  const commandActions = useMemo<CommandPaletteAction[]>(() => {
    const navigationActions: CommandPaletteAction[] = VIEWS.map((view) => ({
      id: `view:${view.id}`,
      label: `Go to ${view.label}`,
      description: view.summary,
      keywords: [view.id, view.label.toLowerCase()],
      run: () => setActiveView(view.id)
    }));

    const projectActions: CommandPaletteAction[] = activeProjects.map((project) => ({
      id: `project:${project.project_id}`,
      label: `Switch to ${project.name}`,
      description: project.description || `${project.task_count} tasks · ${project.open_alert_count} open alerts`,
      keywords: [project.name.toLowerCase(), project.project_type.toLowerCase(), project.onboarding_mode ?? ""],
      run: () => {
        persistSelectedProjectId(project.project_id);
        setSelectedProjectId(project.project_id);
      }
    }));

    return [
      ...navigationActions,
      {
        id: "command:run",
        label: "Run work loop",
        description: "Advance the board and drain the queue using the default operator path.",
        keywords: ["run", "queue", "board", "supervisor", "orchestrator"],
        run: () => {
          if ((activeProject?.task_count ?? 0) > 0) {
            void runOrchestratorPass(4, 2);
          } else {
            void runSupervisorPass(3);
          }
        }
      },
      {
        id: "command:theme",
        label: theme === "dark" ? "Switch to light theme" : "Switch to dark theme",
        description: "Toggle the MAAS theme.",
        keywords: ["theme", "dark", "light"],
        run: () => setTheme((current) => (current === "dark" ? "light" : "dark"))
      },
      ...projectActions
    ];
  }, [activeProject?.task_count, activeProjects, theme]);

  return (
    <div className="cockpit-shell">
      <header className="cockpit-shell__topbar">
        <div className="cockpit-shell__topbar-main">
          <div className="cockpit-shell__brand">
            <span className="cockpit-shell__eyebrow">MAAS operator system</span>
            <strong>MAAS</strong>
            <span>operator cockpit and board workspace</span>
          </div>

          <div className="cockpit-shell__project">
            <label htmlFor="active-project-select">Workspace</label>
            <div className="cockpit-shell__project-row">
              <select
                id="active-project-select"
                aria-label="Selected project"
                value={activeProject?.project_id ?? ""}
                onChange={(event) => {
                  const nextProjectId = event.target.value || null;
                  persistSelectedProjectId(nextProjectId);
                  setSelectedProjectId(nextProjectId);
                }}
              >
                {activeProjects.map((project) => (
                  <option key={project.project_id} value={project.project_id}>
                    {project.name}
                  </option>
                ))}
              </select>
              <div className="cockpit-shell__project-copy">
                <strong>{activeProject?.name ?? "No active project"}</strong>
                <span>{activeProject?.description ?? "Create or restore a project to begin."}</span>
              </div>
            </div>
          </div>
        </div>

        <div className="cockpit-shell__topbar-side">
          <div className="cockpit-shell__telemetry">
            <div className="telemetry-chip telemetry-chip--wide">
              <span className={`status-dot status-dot--${liveTransportTone}`} />
              <div>
                <strong>{liveTransportLabel}</strong>
                <span>{liveTransportDetail}</span>
              </div>
            </div>
            <div className="telemetry-chip">
              <strong>{activeProject?.task_count ?? 0}</strong>
              <span>tasks</span>
            </div>
            <div className="telemetry-chip">
              <strong>{activeProject?.agent_count ?? 0}</strong>
              <span>agents</span>
            </div>
            <div className="telemetry-chip">
              <strong>{activeProject?.open_alert_count ?? 0}</strong>
              <span>alerts</span>
            </div>
          </div>

          <div className="cockpit-shell__actions">
            <button
              type="button"
              className="hero-button hero-button--ghost hero-button--compact"
              onClick={() => setTheme((current) => (current === "dark" ? "light" : "dark"))}
            >
              {theme === "dark" ? "Light" : "Dark"}
            </button>
            <button type="button" className="hero-button hero-button--compact" onClick={() => setCommandPaletteOpen(true)}>
              Command
            </button>
          </div>
        </div>
      </header>

      <div className="cockpit-tabs" aria-label="Primary views">
        {VIEWS.map((view) => (
          <button
            key={view.id}
            type="button"
            className={`cockpit-tabs__item ${activeView === view.id ? "is-active" : ""}`}
            title={view.summary}
            onClick={() => setActiveView(view.id)}
          >
            <strong>{view.label}</strong>
          </button>
        ))}
      </div>

      <main className="cockpit-shell__main">
        <div className={`product-content product-content--${activeView}`}>
          {activeView === "home" ? <HomePage onNavigate={setActiveView} mode="ops" /> : null}
          {activeView === "work" ? <WorkPage onNavigate={setActiveView} /> : null}
          {activeView === "runs" ? <RunsPage /> : null}
          {activeView === "incidents" ? <IncidentsPage /> : null}
          {activeView === "projects" ? (
            <ProjectsPage
              projects={projects}
              selectedProjectId={selectedProjectId}
              projectForm={projectForm}
              projectSubmitting={projectSubmitting}
              projectNotice={projectNotice}
              onSelectProject={(projectId) => {
                persistSelectedProjectId(projectId);
                setSelectedProjectId(projectId);
              }}
              onProjectFormChange={setProjectForm}
              onCreateProject={handleCreateProject}
              onArchiveProject={handleArchiveProject}
              onRestoreProject={handleRestoreProject}
              onNavigate={setActiveView}
            />
          ) : null}
        </div>
      </main>

      <CommandPalette
        open={commandPaletteOpen}
        onClose={() => setCommandPaletteOpen(false)}
        actions={commandActions}
      />
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
