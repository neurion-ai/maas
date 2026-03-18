import type { FormEvent } from "react";
import { useEffect, useMemo, useState } from "react";
import { StatCard } from "../components/StatCard";
import { fetchPortfolio, runOrchestratorPass } from "../lib/controlRoomApi";
import { useLivePulse } from "../lib/useLivePulse";
import type { PortfolioResponse, ProjectSummary } from "../types";
import { PortfolioPage } from "./PortfolioPage";

export interface ProjectFormState {
  name: string;
  description: string;
  projectType: string;
  mode: "auto" | "greenfield" | "brownfield";
  sourceRoot: string;
}

interface ProjectsPageProps {
  projects: ProjectSummary[];
  selectedProjectId: string | null;
  projectForm: ProjectFormState;
  projectSubmitting: boolean;
  projectNotice: string | null;
  onSelectProject: (projectId: string) => void;
  onProjectFormChange: (next: ProjectFormState) => void;
  onCreateProject: (event: FormEvent<HTMLFormElement>) => void;
  onArchiveProject: (projectId: string) => Promise<void>;
  onRestoreProject: (projectId: string) => Promise<void>;
}

function healthTone(health: string) {
  if (health === "critical") {
    return "danger";
  }
  if (health === "warn") {
    return "warn";
  }
  return "default";
}

export function ProjectsPage({
  projects,
  selectedProjectId,
  projectForm,
  projectSubmitting,
  projectNotice,
  onSelectProject,
  onProjectFormChange,
  onCreateProject,
  onArchiveProject,
  onRestoreProject
}: ProjectsPageProps) {
  const [portfolio, setPortfolio] = useState<PortfolioResponse | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pendingActionKey, setPendingActionKey] = useState<string | null>(null);
  const livePulse = useLivePulse();

  const activeProjects = projects.filter((project) => project.state !== "archived");
  const archivedProjects = projects.filter((project) => project.state === "archived");
  const selectedProject =
    activeProjects.find((project) => project.project_id === selectedProjectId) ?? activeProjects[0] ?? null;
  const selectedPortfolioProject =
    portfolio?.projects.find((project) => project.project_id === selectedProject?.project_id) ?? null;

  useEffect(() => {
    let mounted = true;

    async function loadPortfolio() {
      try {
        const payload = await fetchPortfolio();
        if (mounted) {
          setPortfolio(payload);
        }
      } catch {
        if (mounted) {
          setNotice("Project portfolio refresh failed; keeping the latest available portfolio state.");
        }
      }
    }

    void loadPortfolio();
    return () => {
      mounted = false;
    };
  }, [livePulse]);

  async function handleOrchestratorPass() {
    setPendingActionKey("orchestrator");
    setNotice(null);
    try {
      const payload = await runOrchestratorPass(4, 3);
      setPortfolio(await fetchPortfolio());
      setNotice(
        `Orchestrator touched ${payload.project_runs.length} projects, assigned ${payload.assigned_count} tasks, and processed ${payload.provider_jobs_processed} queued jobs.`
      );
    } catch {
      setNotice("Orchestrator pass failed; keeping the latest available portfolio state.");
    } finally {
      setPendingActionKey(null);
    }
  }

  const hotspotProjects = useMemo(() => {
    return [...(portfolio?.projects ?? [])]
      .sort((left, right) => {
        const leftScore =
          left.blocked_tasks + left.open_alerts * 2 + left.dead_letter_entries * 3 + left.provider_capacity.queued_jobs;
        const rightScore =
          right.blocked_tasks + right.open_alerts * 2 + right.dead_letter_entries * 3 + right.provider_capacity.queued_jobs;
        return rightScore - leftScore;
      })
      .slice(0, 5);
  }, [portfolio]);

  return (
    <section className="dashboard-page">
      <header className="dashboard-hero">
        <div className="dashboard-hero__content">
          <span className="eyebrow">Projects</span>
          <h1>Portfolio and lifecycle management</h1>
          <p>Move between repos, create new workspaces, archive old ones, and keep the portfolio healthy without dropping into policy forms first.</p>
          <div className="hero-meta">
            <span className="hero-meta__pill">{activeProjects.length} active projects</span>
            <span className="hero-meta__pill">{archivedProjects.length} archived</span>
            <span className="hero-meta__pill">{portfolio?.summary.projects_with_issues ?? 0} with issues</span>
          </div>
        </div>
        <div className="dashboard-hero__actions">
          <button
            type="button"
            className="hero-button hero-button--primary"
            disabled={pendingActionKey === "orchestrator"}
            onClick={() => void handleOrchestratorPass()}
          >
            {pendingActionKey === "orchestrator" ? "Running orchestrator..." : "Run orchestrator"}
          </button>
        </div>
      </header>

      {projectNotice ? <div className="banner banner--info">{projectNotice}</div> : null}
      {notice ? <div className="banner banner--info">{notice}</div> : null}

      <section className="stats-grid stats-grid--dense">
        <StatCard label="Active projects" value={portfolio?.summary.active_projects ?? activeProjects.length} />
        <StatCard label="Projects with issues" value={portfolio?.summary.projects_with_issues ?? 0} tone="warn" />
        <StatCard label="Blocked tasks" value={portfolio?.summary.blocked_tasks ?? 0} tone="warn" />
        <StatCard label="Queued jobs" value={portfolio?.summary.queued_provider_jobs ?? 0} />
        <StatCard label="Open escalations" value={portfolio?.summary.open_escalations ?? 0} tone="warn" />
        <StatCard label="Recovery pressure" value={portfolio?.summary.recovery_pressure ?? 0} tone="warn" />
      </section>

      <section className="two-column-grid">
        <article className="surface-card">
          <div className="surface-card__header">
            <div>
              <span className="eyebrow">Selected workspace</span>
              <h2>{selectedProject?.name ?? "No active project selected"}</h2>
            </div>
            {selectedProject ? <span className="status-chip">{selectedProject.onboarding_mode ?? "greenfield"}</span> : null}
          </div>
          {selectedProject ? (
            <div className="detail-stack">
              <p>{selectedProject.description || "No project description captured yet."}</p>
              <div className="detail-grid">
                <div>
                  <span>Type</span>
                  <strong>{selectedProject.project_type}</strong>
                </div>
                <div>
                  <span>Mode</span>
                  <strong>{selectedProject.onboarding_mode ?? "greenfield"}</strong>
                </div>
                <div>
                  <span>Tasks</span>
                  <strong>{selectedProject.task_count}</strong>
                </div>
                <div>
                  <span>Open alerts</span>
                  <strong>{selectedProject.open_alert_count}</strong>
                </div>
                <div>
                  <span>Source root</span>
                  <strong>{selectedProject.source_root ?? "workspace root"}</strong>
                </div>
                <div>
                  <span>Health</span>
                  <strong>{selectedPortfolioProject?.health ?? "stable"}</strong>
                </div>
              </div>
              <div className="surface-card__actions">
                <button
                  type="button"
                  className="hero-button hero-button--compact"
                  onClick={() => onSelectProject(selectedProject.project_id)}
                >
                  Active in control room
                </button>
                {activeProjects.length > 1 ? (
                  <button
                    type="button"
                    className="hero-button hero-button--ghost hero-button--compact"
                    disabled={projectSubmitting}
                    onClick={() => void onArchiveProject(selectedProject.project_id)}
                  >
                    Archive project
                  </button>
                ) : null}
              </div>
            </div>
          ) : (
            <div className="empty-state empty-state--compact">
              <strong>No active projects yet.</strong>
              <p>Create or import a workspace to start supervising work.</p>
            </div>
          )}
        </article>

        <article className="surface-card">
          <div className="surface-card__header">
            <div>
              <span className="eyebrow">Portfolio hot spots</span>
              <h2>Where attention is accumulating</h2>
            </div>
          </div>
          <div className="list-stack">
            {hotspotProjects.map((project) => (
              <div key={project.project_id} className="list-row">
                <div>
                  <strong>{project.name}</strong>
                  <p>
                    {project.project_type} · {project.onboarding_mode ?? "greenfield"} · {project.source_root ?? "workspace root"}
                  </p>
                  <p>
                    {project.blocked_tasks} blocked · {project.open_alerts} alerts · {project.dead_letter_entries} DLQ entries
                  </p>
                </div>
                <div className="list-row__meta">
                  <span className={`status-pill status-pill--${healthTone(project.health)}`}>{project.health}</span>
                  <span>{project.provider_capacity.queued_jobs} queued jobs</span>
                </div>
              </div>
            ))}
            {!hotspotProjects.length ? (
              <div className="empty-state empty-state--compact">
                <strong>No portfolio data yet.</strong>
                <p>Create a project to give MAAS something to supervise.</p>
              </div>
            ) : null}
          </div>
        </article>
      </section>

      <section className="two-column-grid">
        <article className="surface-card">
          <div className="surface-card__header">
            <div>
              <span className="eyebrow">Active projects</span>
              <h2>Switch the control room</h2>
            </div>
          </div>
          <div className="card-grid">
            {activeProjects.length ? (
              activeProjects.map((project) => (
                <div
                  key={project.project_id}
                  className={`project-tile ${selectedProjectId === project.project_id ? "is-selected" : ""}`}
                >
                  <div className="mini-card__header">
                    <strong>{project.name}</strong>
                    <span className="status-pill">{project.onboarding_mode ?? "greenfield"}</span>
                  </div>
                  <p>{project.description || "No description yet."}</p>
                  <p>{project.task_count} tasks · {project.open_alert_count} open alerts</p>
                  <div className="surface-card__actions">
                    <button
                      type="button"
                      className="hero-button hero-button--compact"
                      onClick={() => onSelectProject(project.project_id)}
                    >
                      {selectedProjectId === project.project_id ? "Selected" : "Switch project"}
                    </button>
                    {activeProjects.length > 1 ? (
                      <button
                        type="button"
                        className="hero-button hero-button--ghost hero-button--compact"
                        disabled={projectSubmitting}
                        onClick={() => void onArchiveProject(project.project_id)}
                      >
                        Archive
                      </button>
                    ) : null}
                  </div>
                </div>
              ))
            ) : (
              <div className="empty-state empty-state--compact">
                <strong>No active projects yet.</strong>
                <p>Create or import a project to start using MAAS.</p>
              </div>
            )}
          </div>
        </article>

        <article className="surface-card">
          <div className="surface-card__header">
            <div>
              <span className="eyebrow">Create or import</span>
              <h2>Add another workspace</h2>
            </div>
          </div>
          <p className="surface-card__copy">
            Add a greenfield workspace or point MAAS at an existing repository when you want a new project in the selector.
          </p>
          <form className="project-form project-form--stack" onSubmit={onCreateProject}>
            <label className="field-control">
              <span>Name</span>
              <input
                type="text"
                value={projectForm.name}
                placeholder="Payments platform"
                onChange={(event) => onProjectFormChange({ ...projectForm, name: event.target.value })}
                required
              />
            </label>
            <div className="field-grid field-grid--two">
              <label className="field-control">
                <span>Mode</span>
                <select
                  value={projectForm.mode}
                  onChange={(event) =>
                    onProjectFormChange({
                      ...projectForm,
                      mode: event.target.value as ProjectFormState["mode"]
                    })
                  }
                >
                  <option value="auto">Auto</option>
                  <option value="greenfield">Greenfield</option>
                  <option value="brownfield">Brownfield</option>
                </select>
              </label>
              <label className="field-control">
                <span>Project type</span>
                <input
                  type="text"
                  value={projectForm.projectType}
                  onChange={(event) => onProjectFormChange({ ...projectForm, projectType: event.target.value })}
                />
              </label>
            </div>
            <label className="field-control">
              <span>Description</span>
              <input
                type="text"
                value={projectForm.description}
                placeholder="What this project is trying to accomplish"
                onChange={(event) => onProjectFormChange({ ...projectForm, description: event.target.value })}
              />
            </label>
            <label className="field-control">
              <span>Source root</span>
              <input
                type="text"
                value={projectForm.sourceRoot}
                placeholder="/path/to/existing/repo"
                onChange={(event) => onProjectFormChange({ ...projectForm, sourceRoot: event.target.value })}
              />
            </label>
            <div className="surface-card__actions">
              <button type="submit" className="hero-button hero-button--primary" disabled={projectSubmitting}>
                {projectSubmitting ? "Working..." : "Create project"}
              </button>
            </div>
          </form>
        </article>
      </section>

      <section className="two-column-grid">
        <article className="surface-card">
          <div className="surface-card__header">
            <div>
              <span className="eyebrow">Archived projects</span>
              <h2>Restore when needed</h2>
            </div>
          </div>
          <div className="card-grid">
            {archivedProjects.length ? (
              archivedProjects.map((project) => (
                <div key={project.project_id} className="project-tile">
                  <div className="mini-card__header">
                    <strong>{project.name}</strong>
                    <span className="status-pill">archived</span>
                  </div>
                  <p>{project.description || "No description yet."}</p>
                  <p>{project.task_count} tasks · archived {project.archived_at ?? "recently"}</p>
                  <div className="surface-card__actions">
                    <button
                      type="button"
                      className="hero-button hero-button--compact"
                      disabled={projectSubmitting}
                      onClick={() => void onRestoreProject(project.project_id)}
                    >
                      Restore
                    </button>
                  </div>
                </div>
              ))
            ) : (
              <div className="empty-state empty-state--compact">
                <strong>No archived projects.</strong>
                <p>Archive older workspaces when you want to keep the selector focused.</p>
              </div>
            )}
          </div>
        </article>

        <article className="surface-card">
          <div className="surface-card__header">
            <div>
              <span className="eyebrow">Portfolio rhythm</span>
              <h2>What the orchestrator will touch</h2>
            </div>
          </div>
          <div className="detail-grid">
            <div>
              <span>Active projects</span>
              <strong>{portfolio?.summary.active_projects ?? activeProjects.length}</strong>
            </div>
            <div>
              <span>Queued jobs</span>
              <strong>{portfolio?.summary.queued_provider_jobs ?? 0}</strong>
            </div>
            <div>
              <span>Blocked tasks</span>
              <strong>{portfolio?.summary.blocked_tasks ?? 0}</strong>
            </div>
            <div>
              <span>Open escalations</span>
              <strong>{portfolio?.summary.open_escalations ?? 0}</strong>
            </div>
          </div>
          <p className="surface-card__copy">
            Use the orchestrator when you want MAAS to refresh project readiness, assign work, and drain queued runtime jobs across the portfolio.
          </p>
        </article>
      </section>

      <details className="advanced-pane">
        <summary>Advanced portfolio controls</summary>
        <div className="advanced-pane__content">
          <div className="embedded-page">
            <PortfolioPage />
          </div>
        </div>
      </details>
    </section>
  );
}
