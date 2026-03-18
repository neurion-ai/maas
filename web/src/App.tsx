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
    label: "Home",
    summary: "Recommended next actions, current project state, and first-run guidance."
  },
  {
    id: "work",
    label: "Work",
    summary: "Board, plan, task detail, and execution steering."
  },
  {
    id: "runs",
    label: "Runs",
    summary: "Providers, workers, queueing, agents, and outputs."
  },
  {
    id: "incidents",
    label: "Incidents",
    summary: "Failures, alerts, recovery, and timeline replay."
  },
  {
    id: "projects",
    label: "Projects",
    summary: "Portfolio health, project lifecycle, and cross-project supervision."
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

  const liveTransportLabel =
    transport === "websocket"
      ? connected
        ? "Live transport: WebSocket"
        : "Connecting via WebSocket"
      : transport === "sse"
        ? connected
          ? "Live transport: SSE"
          : "Connecting via SSE"
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
        id: "command:supervisor",
        label: "Run supervisor pass",
        description: "Refresh readiness and allocate the next set of tasks.",
        keywords: ["allocate", "scheduler", "supervisor"],
        run: () => {
          void runSupervisorPass(3);
        }
      },
      {
        id: "command:orchestrator",
        label: "Run orchestrator pass",
        description: "Process project-aware orchestration, queued jobs, and assignment flow.",
        keywords: ["orchestrator", "jobs", "queue"],
        run: () => {
          void runOrchestratorPass(4, 2);
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
  }, [activeProjects, theme]);

  return (
    <div className="product-shell">
      <aside className="shell-sidebar">
        <div className="brand-block">
          <span className="eyebrow">MAAS</span>
          <h1>AI software delivery, made operable</h1>
          <p>Import a repo, supervise execution, recover from failures, and keep evidence attached to the work.</p>
        </div>

        <nav className="shell-nav" aria-label="Primary views">
          {VIEWS.map((view) => (
            <button
              key={view.id}
              type="button"
              className={`shell-nav__item ${activeView === view.id ? "is-active" : ""}`}
              onClick={() => setActiveView(view.id)}
            >
              <strong>{view.label}</strong>
              <span>{view.summary}</span>
            </button>
          ))}
        </nav>

        <div className="sidebar-footer">
          <div className="status-chip">
            <span className={`status-chip__dot ${connected ? "is-live" : transport === "polling" ? "is-warn" : ""}`} />
            {liveTransportLabel}
          </div>
          <button type="button" className="hero-button hero-button--ghost hero-button--compact" onClick={() => setCommandPaletteOpen(true)}>
            Command palette
          </button>
        </div>
      </aside>

      <main className="shell-main">
        <header className="shell-topbar">
          <div className="shell-topbar__project">
            <span className="eyebrow">Current project</span>
            <div className="shell-topbar__project-row">
              <select
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
              <div>
                <strong>{activeProject?.name ?? "No active project"}</strong>
                <p>{activeProject?.description ?? "Create or restore a project to begin."}</p>
              </div>
            </div>
          </div>

          <div className="shell-topbar__actions">
            <button
              type="button"
              className="hero-button hero-button--ghost"
              onClick={() => setTheme((current) => (current === "dark" ? "light" : "dark"))}
            >
              {theme === "dark" ? "Light theme" : "Dark theme"}
            </button>
            <button type="button" className="hero-button" onClick={() => setCommandPaletteOpen(true)}>
              Search and jump
            </button>
          </div>
        </header>

        <div className="product-content">
          {activeView === "home" ? <HomePage onNavigate={setActiveView} /> : null}
          {activeView === "work" ? <WorkPage /> : null}
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
