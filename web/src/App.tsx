import { type FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { CommandPalette, type CommandPaletteAction } from "./components/CommandPalette";
import {
  archiveProject,
  cloneProject,
  createProject,
  deleteProject,
  fetchCodexIssueIndex,
  fetchCodexSystemDiagnostics,
  fetchNotifications,
  fetchProjects,
  restoreProject,
} from "./lib/controlRoomApi";
import { getSelectedProjectId, setSelectedProjectId as persistSelectedProjectId } from "./lib/projectScope";
import { setPendingRunFocus } from "./lib/runFocus";
import { setPendingTaskFocus } from "./lib/taskFocus";
import { LivePulseProvider, useLiveStatus, useThrottledLivePulse } from "./lib/useLivePulse";
import { CommandPage } from "./pages/CommandPage";
import { CodexAgentsPage } from "./pages/CodexAgentsPage";
import { CodexIssuesPage } from "./pages/CodexIssuesPage";
import { CodexRunsPage } from "./pages/CodexRunsPage";
import { CodexSystemPage } from "./pages/CodexSystemPage";
import { CodexWorkPage } from "./pages/CodexWorkPage";
import { ProjectsPage, type ProjectFormState } from "./pages/ProjectsPage";
import { SettingsPage } from "./pages/SettingsPage";
import type { NotificationItem, ProjectSummary } from "./types";

type View = "command" | "work" | "issues" | "agents" | "runs" | "system" | "projects" | "settings";
type ThemeMode = "light" | "dark";
type AttentionTone = "warn" | "danger" | "default";
type AttentionItem =
  | {
      id: string;
      kind: "issue";
      tone: AttentionTone;
      title: string;
      detail: string;
      taskId: string;
      targetView: Exclude<View, "settings">;
    }
  | {
      id: string;
      kind: "run";
      tone: AttentionTone;
      title: string;
      detail: string;
      sessionId: string;
      projectId?: string | null;
    }
  | {
      id: string;
      kind: "notification";
      tone: AttentionTone;
      title: string;
      detail: string;
      notificationId: string;
      projectId?: string | null;
      resourceType?: string | null;
      resourceId?: string | null;
    };

const THEME_STORAGE_KEY = "maas:theme";
const DESKTOP_NOTIFICATIONS_STORAGE_KEY = "maas:desktop-notifications";

const PRIMARY_VIEWS: Array<{ id: Exclude<View, "settings">; label: string; summary: string }> = [
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
    id: "runs",
    label: "Runs",
    summary: "Live Codex execution, run traces, stale-run diagnostics, and safe stop/replay actions."
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

const ALL_VIEWS: Array<{ id: View; label: string; summary: string }> = [
  ...PRIMARY_VIEWS,
  {
    id: "settings",
    label: "Settings",
    summary: "Application preferences and global display controls."
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
  return (ALL_VIEWS.find((view) => view.id === hash)?.id ?? "command") as View;
}

function getInitialTheme(): ThemeMode {
  const savedTheme = window.localStorage.getItem(THEME_STORAGE_KEY);
  if (savedTheme === "light" || savedTheme === "dark") {
    return savedTheme;
  }
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function getInitialDesktopNotificationsEnabled() {
  return window.localStorage.getItem(DESKTOP_NOTIFICATIONS_STORAGE_KEY) === "enabled";
}

function AppShell() {
  const [activeView, setActiveView] = useState<View>(getInitialView);
  const [theme, setTheme] = useState<ThemeMode>(getInitialTheme);
  const [desktopNotificationsEnabled, setDesktopNotificationsEnabled] = useState(getInitialDesktopNotificationsEnabled);
  const [notificationPermission, setNotificationPermission] = useState<NotificationPermission>(
    typeof window !== "undefined" && "Notification" in window ? window.Notification.permission : "default"
  );
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [attentionOpen, setAttentionOpen] = useState(false);
  const [attentionItems, setAttentionItems] = useState<AttentionItem[]>([]);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(getSelectedProjectId);
  const [projectForm, setProjectForm] = useState<ProjectFormState>(DEFAULT_PROJECT_FORM);
  const [projectNotice, setProjectNotice] = useState<string | null>(null);
  const [settingsNotice, setSettingsNotice] = useState<string | null>(null);
  const [projectSubmitting, setProjectSubmitting] = useState(false);
  const { connected, transport } = useLiveStatus();
  const livePulse = useThrottledLivePulse(1500);

  const activeProjects = projects.filter((project) => project.state !== "archived");
  const activeProject =
    activeProjects.find((project) => project.project_id === selectedProjectId) ?? activeProjects[0] ?? null;
  const announcedAttentionIds = useRef<Set<string>>(new Set());
  const attentionInitialized = useRef(false);

  useEffect(() => {
    if (!activeProjects.length && activeView !== "projects" && activeView !== "settings") {
      setActiveView("projects");
    }
  }, [activeProjects.length, activeView]);

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
    setAttentionItems([]);
    setAttentionOpen(false);
    announcedAttentionIds.current = new Set();
    attentionInitialized.current = false;
  }, [selectedProjectId]);

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
    window.localStorage.setItem(
      DESKTOP_NOTIFICATIONS_STORAGE_KEY,
      desktopNotificationsEnabled ? "enabled" : "disabled"
    );
  }, [desktopNotificationsEnabled]);

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

  useEffect(() => {
    const controller = new AbortController();
    async function loadAttention() {
      const [issueIndex, diagnostics, notificationsPayload] = await Promise.all([
        fetchCodexIssueIndex(controller.signal),
        fetchCodexSystemDiagnostics(controller.signal),
        fetchNotifications({ status: "failed", limit: 6 }, controller.signal),
      ]);
      const nextItems: AttentionItem[] = [
        ...issueIndex.queue.review.items.slice(0, 4).map((task) => ({
          id: `issue-review:${task.task_id}`,
          kind: "issue" as const,
          tone: "warn" as const,
          title: task.issue_key ?? task.title,
          detail: task.title,
          taskId: task.task_id,
          targetView: "issues" as const,
        })),
        ...issueIndex.queue.blocked_failures.items.slice(0, 4).map((task) => ({
          id: `issue-blocked:${task.task_id}`,
          kind: "issue" as const,
          tone: "danger" as const,
          title: task.issue_key ?? task.title,
          detail: task.title,
          taskId: task.task_id,
          targetView: "issues" as const,
        })),
        ...diagnostics.suspect_runs.slice(0, 4).map((run) => ({
          id: `run:${run.session_id}`,
          kind: "run" as const,
          tone: "warn" as const,
          title: run.issue_key ?? run.session_id,
          detail: run.diagnostic_summary ?? run.status_message ?? "Suspect run needs inspection.",
          sessionId: run.session_id,
          projectId: run.project_id ?? null,
        })),
        ...notificationsPayload.notifications.slice(0, 4).map((item: NotificationItem) => ({
          id: `notification:${item.notification_id}`,
          kind: "notification" as const,
          tone: item.status === "failed" ? ("danger" as const) : ("default" as const),
          title: item.title,
          detail: item.body,
          notificationId: item.notification_id,
          projectId: item.project_id ?? null,
          resourceType: item.resource_type ?? null,
          resourceId: item.resource_id ?? null,
        })),
      ];
      setAttentionItems(nextItems);

      if (!desktopNotificationsEnabled || notificationPermission !== "granted" || !("Notification" in window)) {
        announcedAttentionIds.current = new Set(nextItems.map((item) => item.id));
        attentionInitialized.current = true;
        return;
      }

      const unseen = nextItems.filter((item) => !announcedAttentionIds.current.has(item.id));
      if (attentionInitialized.current) {
        unseen.slice(0, 2).forEach((item) => {
          new window.Notification(item.title, {
            body: item.detail,
          });
        });
      }
      announcedAttentionIds.current = new Set(nextItems.map((item) => item.id));
      attentionInitialized.current = true;
    }

    void loadAttention().catch(() => {
      setAttentionItems([]);
    });
    return () => controller.abort();
  }, [livePulse, desktopNotificationsEnabled, notificationPermission, selectedProjectId]);

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
        source_root: projectForm.sourceRoot.trim() || undefined,
        create_source_root: projectForm.mode === "greenfield" && !projectForm.sourceRoot.trim(),
      });
      await loadProjects(payload.project.project_id);
      setProjectForm(DEFAULT_PROJECT_FORM);
      setActiveView("command");
      setProjectNotice(
        `Created ${payload.project.name} in ${payload.mode} mode${payload.metadata.generated_source_root ? ` with a fresh workspace at ${payload.metadata.source_root}` : ` from ${payload.metadata.source_root}`}.`
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

  async function handleCloneProject(projectId: string, suggestedName?: string) {
    setProjectSubmitting(true);
    setProjectNotice(null);
    try {
      const payload = await cloneProject(projectId, suggestedName);
      await loadProjects(payload.project.project_id);
      setProjectNotice(`Cloned ${payload.metadata.cloned_from_project_id ? "project" : "workspace"} into ${payload.project.name}.`);
      setActiveView("projects");
    } catch (error) {
      setProjectNotice(error instanceof Error ? error.message : "Could not clone project.");
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

  async function handleDeleteProject(projectId: string) {
    setProjectSubmitting(true);
    setProjectNotice(null);
    try {
      await deleteProject(projectId);
      await loadProjects(projectId === selectedProjectId ? null : selectedProjectId);
      setProjectNotice("Deleted project.");
    } catch (error) {
      setProjectNotice(error instanceof Error ? error.message : "Could not delete project.");
    } finally {
      setProjectSubmitting(false);
    }
  }

  async function handleRequestDesktopNotifications() {
    if (!("Notification" in window)) {
      setSettingsNotice("Browser notifications are not supported here.");
      return;
    }
    const permission = await window.Notification.requestPermission();
    setNotificationPermission(permission);
    if (permission === "granted") {
      setDesktopNotificationsEnabled(true);
      setSettingsNotice("Desktop notifications enabled for new review and failure pressure.");
      return;
    }
    setDesktopNotificationsEnabled(false);
    setSettingsNotice("Desktop notifications were not granted.");
  }

  function handleAttentionItem(item: AttentionItem) {
    if (item.kind === "issue") {
      setPendingTaskFocus(item.taskId);
      setActiveView(item.targetView);
      setAttentionOpen(false);
      return;
    }
    if (item.kind === "run") {
      if (item.projectId) {
        persistSelectedProjectId(item.projectId);
        setSelectedProjectId(item.projectId);
      }
      setPendingRunFocus(item.sessionId);
      setActiveView("runs");
      setAttentionOpen(false);
      return;
    }
    if (item.projectId) {
      persistSelectedProjectId(item.projectId);
      setSelectedProjectId(item.projectId);
    }
    if (item.resourceType === "task" && item.resourceId) {
      setPendingTaskFocus(item.resourceId);
      setActiveView("issues");
      setAttentionOpen(false);
      return;
    }
    if (item.resourceType === "session" && item.resourceId) {
      setPendingRunFocus(item.resourceId);
      setActiveView("runs");
      setAttentionOpen(false);
      return;
    }
    setActiveView("system");
    setAttentionOpen(false);
  }

  const commandActions = useMemo<CommandPaletteAction[]>(() => {
    const navigationActions: CommandPaletteAction[] = ALL_VIEWS.map((view) => ({
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

        <div className="codex-sidebar__scroll">
          <nav className="codex-sidebar__nav" aria-label="Primary views">
            {PRIMARY_VIEWS.map((view) => (
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
        </div>

        <div className="codex-sidebar__footer">
          <button
            type="button"
            className={`codex-sidebar__nav-item ${activeView === "settings" ? "is-active" : ""}`}
            title="Application preferences and display controls."
            onClick={() => setActiveView("settings")}
          >
            <span>Settings</span>
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
              <button
                type="button"
                className={`codex-chip codex-chip--button ${attentionOpen ? "is-active" : ""}`}
                onClick={() => setAttentionOpen((current) => !current)}
              >
                Attention {attentionItems.length}
              </button>
            </div>
          </div>
        </header>

        {attentionOpen ? (
          <div className="codex-attention-popover codex-panel">
            <div className="codex-panel__header">
              <div>
                <span className="codex-kicker">Attention inbox</span>
                <h2>What just needs operator eyes</h2>
              </div>
            </div>
            <div className="codex-stack-list">
              {attentionItems.length ? (
                attentionItems.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    className={`codex-stack-item codex-stack-item--attention tone-${item.tone}`}
                    onClick={() => handleAttentionItem(item)}
                  >
                    <div className="codex-stack-item__header">
                      <strong>{item.title}</strong>
                      <span>{item.kind}</span>
                    </div>
                    <p>{item.detail}</p>
                  </button>
                ))
              ) : (
                <div className="codex-empty-copy">Nothing new requires attention right now.</div>
              )}
            </div>
          </div>
        ) : null}

        <div className="codex-shell__content">
          {activeView === "command" ? <CommandPage key={`command:${activeProject?.project_id ?? "none"}`} onNavigate={setActiveView} /> : null}
          {activeView === "work" ? <CodexWorkPage key={`work:${activeProject?.project_id ?? "none"}`} onNavigate={setActiveView} /> : null}
          {activeView === "issues" ? <CodexIssuesPage key={`issues:${activeProject?.project_id ?? "none"}`} onNavigate={setActiveView} /> : null}
          {activeView === "agents" ? <CodexAgentsPage key={`agents:${activeProject?.project_id ?? "none"}`} onNavigate={setActiveView} /> : null}
          {activeView === "runs" ? <CodexRunsPage key={`runs:${activeProject?.project_id ?? "none"}`} onNavigate={setActiveView} /> : null}
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
              onCloneProject={handleCloneProject}
              onArchiveProject={handleArchiveProject}
              onRestoreProject={handleRestoreProject}
              onDeleteProject={handleDeleteProject}
              onNavigate={setActiveView}
            />
          ) : null}
          {activeView === "settings" ? (
            <SettingsPage
              theme={theme}
              onThemeChange={setTheme}
              desktopNotificationsEnabled={desktopNotificationsEnabled}
              notificationPermission={notificationPermission}
              notice={settingsNotice}
              onToggleDesktopNotifications={() => {
                setSettingsNotice(null);
                if (!desktopNotificationsEnabled && notificationPermission !== "granted") {
                  void handleRequestDesktopNotifications();
                  return;
                }
                setDesktopNotificationsEnabled((current) => !current);
                setSettingsNotice(
                  desktopNotificationsEnabled
                    ? "Desktop notifications disabled."
                    : "Desktop notifications enabled for new review and failure pressure."
                );
              }}
              onRequestDesktopNotifications={() => void handleRequestDesktopNotifications()}
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
