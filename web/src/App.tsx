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
import { LivePulseProvider, useLivePulse, useLiveStatus } from "./lib/useLivePulse";
import { CommandPage } from "./pages/CommandPage";
import { CodexAgentsPage } from "./pages/CodexAgentsPage";
import { CodexIssuesPage } from "./pages/CodexIssuesPage";
import { CodexSystemPage } from "./pages/CodexSystemPage";
import { CodexWorkPage } from "./pages/CodexWorkPage";
import { ProjectsPage, type ProjectFormState } from "./pages/ProjectsPage";
import type { ProjectSummary } from "./types";

type View = "command" | "work" | "issues" | "agents" | "system" | "projects";
type ThemeMode = "light" | "dark";

const THEME_STORAGE_KEY = "maas:theme";

const VIEWS: Array<{ id: View; label: string; summary: string }> = [
  {
    id: "command",
    label: "Command",
    summary: "What needs judgment, what is moving, and what just landed."
  },
  {
    id: "work",
    label: "Work",
    summary: "The same issues in list or board form with a real right-side issue detail view."
  },
  {
    id: "issues",
    label: "Issues",
    summary: "Operator-facing decisions, blocked work, and resolved history."
  },
  {
    id: "agents",
    label: "Agents",
    summary: "Which agent owns what, what is healthy, and what changed recently."
  },
  {
    id: "system",
    label: "System",
    summary: "Logs, metrics, queue posture, and runtime health."
  },
  {
    id: "projects",
    label: "Projects",
    summary: "Project intake, lifecycle, and workspace switching."
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
  return (VIEWS.find((view) => view.id === hash)?.id ?? "command") as View;
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
  const livePulse = useLivePulse();

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
    void loadProjects(selectedProjectId).catch(() => {
      setProjectNotice((current) => current ?? "Project summaries are stale; refresh failed.");
    });
  }, [livePulse]);

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
      setActiveView("command");
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
    <div className="codex-shell">
      <aside className="codex-sidebar">
        <div className="codex-sidebar__brand">
          <span className="codex-sidebar__logo">M</span>
          <div>
            <strong>MAAS</strong>
            <span>Codex MVP</span>
          </div>
        </div>

        <button type="button" className="codex-sidebar__command" onClick={() => setCommandPaletteOpen(true)}>
          Command palette
        </button>

        <nav className="codex-sidebar__nav" aria-label="Primary views">
          {VIEWS.map((view) => (
            <button
              key={view.id}
              type="button"
              className={`codex-sidebar__nav-item ${activeView === view.id ? "is-active" : ""}`}
              title={view.summary}
              onClick={() => setActiveView(view.id)}
            >
              <span>{view.label}</span>
              {view.id === "work" ? <span>{activeProject?.task_count ?? 0}</span> : null}
            </button>
          ))}
        </nav>

        <div className="codex-sidebar__section">
          <span className="codex-sidebar__label">Projects</span>
          <div className="codex-sidebar__projects">
            {activeProjects.map((project) => (
              <button
                key={project.project_id}
                type="button"
                className={`codex-sidebar__project ${selectedProjectId === project.project_id ? "is-active" : ""}`}
                onClick={() => {
                  persistSelectedProjectId(project.project_id);
                  setSelectedProjectId(project.project_id);
                }}
              >
                <span>{project.name}</span>
                <span>{project.task_count}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="codex-sidebar__footer">
          <button
            type="button"
            className="codex-sidebar__text-button"
            onClick={() => setTheme((current) => (current === "dark" ? "light" : "dark"))}
          >
            {theme === "dark" ? "Light theme" : "Dark theme"}
          </button>
        </div>
      </aside>

      <main className="codex-shell__main">
        <header className="codex-topbar">
          <div className="codex-topbar__copy">
            <span className="codex-kicker">Workspace</span>
            <strong>{activeProject?.name ?? "No active project"}</strong>
            <span>{activeProject?.description ?? "Create or restore a project to begin."}</span>
          </div>
          <div className="codex-topbar__controls">
            <label className="codex-topbar__project-picker">
              <span>Project</span>
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
            </label>
            <div className="codex-topbar__chips">
              <span className="codex-chip">
                <span className={`status-dot status-dot--${liveTransportTone}`} />
                {liveTransportLabel}
              </span>
              <span className="codex-chip">{activeProject?.task_count ?? 0} tasks</span>
              <span className="codex-chip">{activeProject?.agent_count ?? 0} agents</span>
              <span className="codex-chip">{activeProject?.open_alert_count ?? 0} alerts</span>
            </div>
          </div>
        </header>

        <div className="codex-shell__content">
          {activeView === "command" ? <CommandPage key={`command:${activeProject?.project_id ?? "none"}`} onNavigate={setActiveView} /> : null}
          {activeView === "work" ? <CodexWorkPage key={`work:${activeProject?.project_id ?? "none"}`} /> : null}
          {activeView === "issues" ? <CodexIssuesPage key={`issues:${activeProject?.project_id ?? "none"}`} /> : null}
          {activeView === "agents" ? <CodexAgentsPage key={`agents:${activeProject?.project_id ?? "none"}`} onNavigate={setActiveView} /> : null}
          {activeView === "system" ? <CodexSystemPage key={`system:${activeProject?.project_id ?? "none"}`} onNavigate={setActiveView} /> : null}
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
