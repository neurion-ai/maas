import type { DragEvent, FormEvent } from "react";
import { useEffect, useMemo, useState } from "react";
import {
  fetchOverview,
  fetchPortfolio,
  pickLocalDirectory,
  runOrchestratorPass,
  runSupervisorPass
} from "../lib/controlRoomApi";
import { useLivePulse } from "../lib/useLivePulse";
import type { OverviewResponse, PortfolioProject, PortfolioResponse, ProjectSummary } from "../types";

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
  onNavigate?: (view: "home" | "work" | "runs" | "incidents" | "projects") => void;
}

interface NextStep {
  title: string;
  detail: string;
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

function formatLabel(value: string | null | undefined) {
  if (!value) {
    return "Not set";
  }
  return value
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function pluralize(count: number, singular: string, plural = `${singular}s`) {
  return `${count} ${count === 1 ? singular : plural}`;
}

function onboardingTone(reviewStatus: string | undefined, driftDetected: boolean) {
  if (driftDetected) {
    return "warn";
  }
  if (reviewStatus && reviewStatus !== "approved" && reviewStatus !== "reviewed" && reviewStatus !== "not_applicable") {
    return "warn";
  }
  return "default";
}

function onboardingHeadline(
  mode: string,
  reviewStatus: string | undefined,
  driftDetected: boolean
) {
  if (mode !== "brownfield") {
    return "Greenfield workspace";
  }
  if (driftDetected) {
    return "Brownfield drift needs review";
  }
  if (reviewStatus && reviewStatus !== "approved" && reviewStatus !== "reviewed" && reviewStatus !== "not_applicable") {
    return "Brownfield onboarding review is still active";
  }
  return "Brownfield onboarding is approved";
}

function buildOnboardingSummary(
  selectedProject: ProjectSummary | null,
  overview: OverviewResponse | null
) {
  const mode = overview?.onboarding?.mode ?? selectedProject?.onboarding_mode ?? "greenfield";
  const reviewStatus = overview?.onboarding?.review_status;
  const driftSummary = overview?.onboarding?.drift_summary;
  const driftDetected = Boolean(driftSummary?.detected);
  const pendingGatedTasks = overview?.onboarding?.pending_gated_tasks ?? 0;

  if (mode !== "brownfield") {
    return {
      mode,
      reviewStatus,
      driftDetected,
      title: "Greenfield workspace",
      description: "No import review gate is active. Create or schedule work normally.",
      tone: "default" as const
    };
  }

  if (driftDetected) {
    return {
      mode,
      reviewStatus,
      driftDetected,
      title: "Brownfield drift needs review",
      description:
        driftSummary?.summary ??
        "The imported repository changed enough that MAAS wants a new onboarding review before widening automation.",
      tone: "warn" as const
    };
  }

  if (reviewStatus && reviewStatus !== "approved" && reviewStatus !== "reviewed" && reviewStatus !== "not_applicable") {
    return {
      mode,
      reviewStatus,
      driftDetected,
      title: "Brownfield onboarding review is still active",
      description:
        pendingGatedTasks > 0
          ? `${pluralize(pendingGatedTasks, "imported task")} are still gated behind review.`
          : "Imported work is still waiting on an operator review decision.",
      tone: "warn" as const
    };
  }

  return {
    mode,
    reviewStatus,
    driftDetected,
    title: "Brownfield onboarding is approved",
    description:
      pendingGatedTasks > 0
        ? `${pluralize(pendingGatedTasks, "task")} are still marked gated, so check the imported plan state.`
        : "Imported repo understanding is approved and the project can be supervised normally.",
    tone: "default" as const
  };
}

function buildNextSteps(
  selectedProject: ProjectSummary | null,
  portfolioProject: PortfolioProject | null,
  overview: OverviewResponse | null
) {
  if (!selectedProject) {
    return [];
  }

  const items: NextStep[] = [];
  const onboarding = overview?.onboarding;
  const onboardingMode = onboarding?.mode ?? selectedProject.onboarding_mode ?? "greenfield";
  const reviewStatus = onboarding?.review_status;
  const driftDetected = Boolean(onboarding?.drift_summary?.detected);

  if (
    onboardingMode === "brownfield" &&
    reviewStatus &&
    reviewStatus !== "approved" &&
    reviewStatus !== "reviewed" &&
    reviewStatus !== "not_applicable"
  ) {
    items.push({
      title: "Finish brownfield review first",
      detail:
        onboarding?.pending_gated_tasks && onboarding.pending_gated_tasks > 0
          ? `${pluralize(onboarding.pending_gated_tasks, "imported task")} remain gated until the onboarding review is approved.`
          : "Imported repo work is still under review before wider automation should continue."
    });
  }

  if (driftDetected) {
    items.push({
      title: "Revisit the imported repo plan",
      detail:
        onboarding?.drift_summary?.summary ??
        "New repository drift was detected, so the imported understanding and follow-up task graph likely need another pass."
    });
  }

  if ((portfolioProject?.dead_letter_entries ?? 0) > 0) {
    items.push({
      title: "Clear dead-letter work",
      detail: `${pluralize(portfolioProject?.dead_letter_entries ?? 0, "DLQ entry")} need operator recovery or replanning.`
    });
  }

  if ((portfolioProject?.open_quarantine_entries ?? 0) > 0) {
    items.push({
      title: "Review quarantined artifacts",
      detail: `${pluralize(portfolioProject?.open_quarantine_entries ?? 0, "quarantine entry")} are still open for this project.`
    });
  }

  if ((portfolioProject?.open_alerts ?? 0) > 0) {
    items.push({
      title: "Triage current alerts",
      detail: `${pluralize(portfolioProject?.open_alerts ?? 0, "open alert")} are active, alongside ${pluralize(
        portfolioProject?.blocked_tasks ?? 0,
        "blocked task"
      )}.`
    });
  }

  if ((portfolioProject?.provider_capacity.queued_jobs ?? 0) > 0) {
    items.push({
      title: "Drain queued provider jobs",
      detail: `${pluralize(portfolioProject?.provider_capacity.queued_jobs ?? 0, "queued provider job")} are waiting in ${
        portfolioProject?.provider_capacity.queue_mode ?? "running"
      } mode.`
    });
  }

  if (!items.length) {
    items.push({
      title: "Continue normal supervision",
      detail:
        overview != null
          ? `${pluralize(overview.summary.tasks_in_progress, "task")} in progress and ${pluralize(
              overview.summary.tasks_review,
              "task"
            )} in review. This project looks stable enough to keep moving through the normal control-room flow.`
          : "This project looks stable. Continue from Overview, Board, or Goals."
    });
  }

  return items.slice(0, 4);
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
  onRestoreProject,
  onNavigate
}: ProjectsPageProps) {
  const [portfolio, setPortfolio] = useState<PortfolioResponse | null>(null);
  const [selectedOverview, setSelectedOverview] = useState<OverviewResponse | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pendingActionKey, setPendingActionKey] = useState<string | null>(null);
  const [pickingSourceRoot, setPickingSourceRoot] = useState(false);
  const livePulse = useLivePulse();

  const activeProjects = projects.filter((project) => project.state !== "archived");
  const archivedProjects = projects.filter((project) => project.state === "archived");
  const selectedProject =
    activeProjects.find((project) => project.project_id === selectedProjectId) ?? activeProjects[0] ?? null;
  const selectedPortfolioProject =
    portfolio?.projects.find((project) => project.project_id === selectedProject?.project_id) ?? null;
  const otherActiveProjects = activeProjects.filter((project) => project.project_id !== selectedProject?.project_id);

  useEffect(() => {
    let mounted = true;

    async function loadPageState() {
      const portfolioPayload = await fetchPortfolio();
      const overviewPayload = selectedProject ? await fetchOverview() : null;
      if (!mounted) {
        return;
      }
      setPortfolio(portfolioPayload);
      setSelectedOverview(overviewPayload);
    }

    void loadPageState();
    return () => {
      mounted = false;
    };
  }, [livePulse, selectedProject?.project_id]);

  async function handleOrchestratorPass() {
    setPendingActionKey("orchestrator");
    setNotice(null);
    try {
      const payload = await runOrchestratorPass(4, 3);
      setPortfolio(await fetchPortfolio());
      if (selectedProject) {
        setSelectedOverview(await fetchOverview());
      }
      setNotice(
        `Orchestrator touched ${payload.project_runs.length} projects, assigned ${payload.assigned_count} tasks, and processed ${payload.provider_jobs_processed} queued jobs.`
      );
    } catch {
      setNotice("Orchestrator pass failed; keeping the latest available portfolio state.");
    } finally {
      setPendingActionKey(null);
    }
  }

  const onboardingSummary = useMemo(
    () => buildOnboardingSummary(selectedProject, selectedOverview),
    [selectedOverview, selectedProject]
  );

  const nextSteps = useMemo(
    () => buildNextSteps(selectedProject, selectedPortfolioProject, selectedOverview),
    [selectedOverview, selectedPortfolioProject, selectedProject]
  );

  function coerceDroppedPath(dataTransfer: DataTransfer) {
    const uriList = dataTransfer.getData("text/uri-list").trim();
    if (uriList.startsWith("file://")) {
      try {
        return decodeURIComponent(uriList.replace(/^file:\/\//, ""));
      } catch {
        return uriList.replace(/^file:\/\//, "");
      }
    }
    const plainText = dataTransfer.getData("text/plain").trim();
    if (plainText.startsWith("file://")) {
      try {
        return decodeURIComponent(plainText.replace(/^file:\/\//, ""));
      } catch {
        return plainText.replace(/^file:\/\//, "");
      }
    }
    if (plainText.startsWith("/")) {
      return plainText;
    }
    return null;
  }

  async function handleBrowseSourceRoot() {
    setPickingSourceRoot(true);
    setNotice(null);
    try {
      const payload = await pickLocalDirectory();
      if (!payload.cancelled && payload.path) {
        onProjectFormChange({ ...projectForm, sourceRoot: payload.path });
        setNotice(`Selected ${payload.path}.`);
      }
    } catch {
      setNotice("Folder picker failed. You can still paste a local repo path into Source root.");
    } finally {
      setPickingSourceRoot(false);
    }
  }

  function handleSourceRootDrop(event: DragEvent<HTMLInputElement>) {
    event.preventDefault();
    const droppedPath = coerceDroppedPath(event.dataTransfer);
    if (droppedPath) {
      onProjectFormChange({ ...projectForm, sourceRoot: droppedPath });
      setNotice(`Selected ${droppedPath}.`);
      return;
    }
    setNotice("That drop did not include a usable local path. Use Browse… for a native folder picker.");
  }

  return (
    <section className="dashboard-page">
      <header className="dashboard-hero">
        <div className="dashboard-hero__content">
          <span className="eyebrow">Projects</span>
          <h1>Keep the active project clear</h1>
          <p>Selected workspace first, next operator moves second, and import or create tucked into a smaller side panel.</p>
          <div className="hero-meta">
            <span className="hero-meta__pill">{activeProjects.length} active</span>
            <span className="hero-meta__pill">{archivedProjects.length} archived</span>
            <span className="hero-meta__pill">{portfolio?.summary.projects_with_issues ?? 0} needing attention</span>
          </div>
        </div>
      </header>

      {projectNotice ? <div className="banner banner--info">{projectNotice}</div> : null}
      {notice ? <div className="banner banner--info">{notice}</div> : null}

      <section className="two-column-grid">
        <article className="surface-card">
          <div className="surface-card__header">
            <div>
              <span className="eyebrow">Selected project</span>
              <h2>{selectedProject?.name ?? "No active project selected"}</h2>
            </div>
            {selectedProject ? (
              <span className={`status-pill status-pill--${healthTone(selectedPortfolioProject?.health ?? "healthy")}`}>
                {selectedPortfolioProject?.health ?? "healthy"}
              </span>
            ) : null}
          </div>
          {selectedProject ? (
            <div className="detail-stack">
              <p>{selectedProject.description || "No project description captured yet."}</p>
              <div className="hero-meta">
                <span className="hero-meta__pill">{selectedProject.project_type}</span>
                <span className="hero-meta__pill">{formatLabel(onboardingSummary.mode)}</span>
                {onboardingSummary.mode === "brownfield" ? (
                  <span className={`hero-meta__pill status-pill--${onboardingSummary.tone}`}>
                    {formatLabel(selectedOverview?.onboarding?.review_status ?? "review_pending")}
                  </span>
                ) : null}
              </div>
              <div className="detail-grid">
                <div>
                  <span>Source root</span>
                  <strong>{selectedProject.source_root ?? "workspace root"}</strong>
                </div>
                <div>
                  <span>Tasks</span>
                  <strong>{selectedProject.task_count}</strong>
                </div>
                <div>
                  <span>Blocked</span>
                  <strong>{selectedPortfolioProject?.blocked_tasks ?? 0}</strong>
                </div>
                <div>
                  <span>Open alerts</span>
                  <strong>{selectedPortfolioProject?.open_alerts ?? selectedProject.open_alert_count}</strong>
                </div>
                <div>
                  <span>Queued jobs</span>
                  <strong>{selectedPortfolioProject?.provider_capacity.queued_jobs ?? 0}</strong>
                </div>
                <div>
                  <span>Recovery pressure</span>
                  <strong>
                    {(selectedPortfolioProject?.dead_letter_entries ?? 0) +
                      (selectedPortfolioProject?.open_quarantine_entries ?? 0) +
                      (selectedPortfolioProject?.repeated_failure_tasks ?? 0)}
                  </strong>
                </div>
              </div>
              <div className="surface-card__actions">
                {onNavigate ? (
                  <button
                    type="button"
                    className="hero-button hero-button--primary hero-button--compact"
                    onClick={() => onNavigate("home")}
                  >
                    Open cockpit
                  </button>
                ) : null}
                {onNavigate ? (
                  <button
                    type="button"
                    className="hero-button hero-button--ghost hero-button--compact"
                    onClick={() => onNavigate("work")}
                  >
                    Open board
                  </button>
                ) : null}
                <button
                  type="button"
                  className="hero-button hero-button--ghost hero-button--compact"
                  onClick={() => onSelectProject(selectedProject.project_id)}
                >
                  Keep selected
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
              <span className="eyebrow">Next steps</span>
              <h2>What to do next in this project</h2>
            </div>
          </div>
          {selectedProject ? (
            <div className="detail-stack">
              <div className="list-row">
                <div>
                  <span className="eyebrow">Onboarding state</span>
                  <strong>{onboardingHeadline(onboardingSummary.mode, selectedOverview?.onboarding?.review_status, onboardingSummary.driftDetected)}</strong>
                  <p>{onboardingSummary.description}</p>
                </div>
                <div className="list-row__meta">
                  <span className={`status-pill status-pill--${onboardingTone(selectedOverview?.onboarding?.review_status, onboardingSummary.driftDetected)}`}>
                    {onboardingSummary.mode === "brownfield"
                      ? formatLabel(selectedOverview?.onboarding?.review_status ?? "review_pending")
                      : "Ready"}
                  </span>
                </div>
              </div>
              {onboardingSummary.mode === "brownfield" ? (
                <div className="detail-grid">
                  <div>
                    <span>Pending gated tasks</span>
                    <strong>{selectedOverview?.onboarding?.pending_gated_tasks ?? 0}</strong>
                  </div>
                  <div>
                    <span>Review task</span>
                    <strong>
                      {selectedOverview?.onboarding?.review_task_status
                        ? formatLabel(selectedOverview.onboarding?.review_task_status)
                        : "Not linked"}
                    </strong>
                  </div>
                  <div>
                    <span>Last scanned</span>
                    <strong>{selectedOverview?.onboarding?.last_scanned_at ?? "Not scanned yet"}</strong>
                  </div>
                  <div>
                    <span>Reviewed at</span>
                    <strong>{selectedOverview?.onboarding?.reviewed_at ?? "Waiting on review"}</strong>
                  </div>
                </div>
              ) : null}
              <div className="list-stack">
                {nextSteps.map((step) => (
                  <div key={step.title} className="list-row">
                    <div>
                      <strong>{step.title}</strong>
                      <p>{step.detail}</p>
                    </div>
                  </div>
                ))}
              </div>
              <div className="detail-grid">
                <div>
                  <span>Portfolio issues</span>
                  <strong>{portfolio?.summary.projects_with_issues ?? 0}</strong>
                </div>
                <div>
                  <span>Open escalations</span>
                  <strong>{portfolio?.summary.open_escalations ?? 0}</strong>
                </div>
                <div>
                  <span>Queued provider jobs</span>
                  <strong>{portfolio?.summary.queued_provider_jobs ?? 0}</strong>
                </div>
                <div>
                  <span>Recovery pressure</span>
                  <strong>{portfolio?.summary.recovery_pressure ?? 0}</strong>
                </div>
              </div>
              <div className="surface-card__actions">
                {selectedOverview?.onboarding?.review_task_status === "planned" ? (
                  <button
                    type="button"
                    className="hero-button hero-button--primary hero-button--compact"
                    disabled={pendingActionKey === "supervisor"}
                    onClick={async () => {
                      setPendingActionKey("supervisor");
                      setNotice(null);
                      try {
                        await runSupervisorPass(3);
                        setSelectedOverview(await fetchOverview());
                        setNotice("Supervisor pass completed. The import review task is ready for inspection.");
                        onNavigate?.("home");
                      } catch {
                        setNotice("Supervisor pass failed; keep the import under review.");
                      } finally {
                        setPendingActionKey(null);
                      }
                    }}
                  >
                    {pendingActionKey === "supervisor" ? "Running..." : "Prepare import review"}
                  </button>
                ) : null}
                {onNavigate ? (
                  <button
                    type="button"
                    className="hero-button hero-button--ghost hero-button--compact"
                    onClick={() => onNavigate("home")}
                  >
                    Open cockpit
                  </button>
                ) : null}
                {onNavigate ? (
                  <button
                    type="button"
                    className="hero-button hero-button--ghost hero-button--compact"
                    onClick={() => onNavigate("work")}
                  >
                    Open board
                  </button>
                ) : null}
                <button
                  type="button"
                  className="hero-button hero-button--ghost hero-button--compact"
                  disabled={pendingActionKey === "orchestrator"}
                  onClick={() => void handleOrchestratorPass()}
                >
                  {pendingActionKey === "orchestrator" ? "Running orchestrator..." : "Run orchestrator"}
                </button>
              </div>
            </div>
          ) : (
            <div className="empty-state empty-state--compact">
              <strong>No project selected.</strong>
              <p>Select an active workspace to see onboarding state and recommended next moves.</p>
            </div>
          )}
        </article>
      </section>

      <section className="two-column-grid">
        <article className="surface-card">
          <div className="surface-card__header">
            <div>
              <span className="eyebrow">Switch project</span>
              <h2>Other active workspaces</h2>
            </div>
          </div>
          <div className="list-stack">
            {selectedProject ? (
              <div className="list-row">
                <div>
                  <strong>{selectedProject.name}</strong>
                  <p>
                    Current selection · {formatLabel(selectedProject.onboarding_mode ?? "greenfield")} ·{" "}
                    {selectedPortfolioProject?.blocked_tasks ?? 0} blocked
                  </p>
                </div>
                <div className="list-row__meta">
                  <span className={`status-pill status-pill--${healthTone(selectedPortfolioProject?.health ?? "healthy")}`}>
                    {selectedPortfolioProject?.health ?? "healthy"}
                  </span>
                </div>
              </div>
            ) : null}
            {otherActiveProjects.map((project) => {
              const projectPortfolio = portfolio?.projects.find((item) => item.project_id === project.project_id);
              return (
                <div key={project.project_id} className="list-row">
                  <div>
                    <strong>{project.name}</strong>
                    <p>
                      {formatLabel(project.onboarding_mode ?? "greenfield")} · {project.task_count} tasks ·{" "}
                      {projectPortfolio?.open_alerts ?? project.open_alert_count} alerts
                    </p>
                  </div>
                  <div className="list-row__meta">
                    <span className={`status-pill status-pill--${healthTone(projectPortfolio?.health ?? "healthy")}`}>
                      {projectPortfolio?.health ?? "healthy"}
                    </span>
                    <button
                      type="button"
                      className="hero-button hero-button--compact"
                      onClick={() => onSelectProject(project.project_id)}
                    >
                      Switch
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
              );
            })}
            {!selectedProject && !otherActiveProjects.length ? (
              <div className="empty-state empty-state--compact">
                <strong>No active projects yet.</strong>
                <p>Create or import a project to start using MAAS.</p>
              </div>
            ) : null}
          </div>
        </article>

        <article className="surface-card">
          <div className="surface-card__header">
            <div>
              <span className="eyebrow">Create / import</span>
              <h2>Add another workspace</h2>
            </div>
          </div>
          <p className="surface-card__copy">
            Keep this compact: name it, choose the mode, and optionally point MAAS at an existing repo.
          </p>
          <form className="project-form project-form--stack" onSubmit={onCreateProject}>
            <div className="field-grid field-grid--two">
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
            </div>
            <label className="field-control">
              <span className="field-control__label-row">
                <span>Source root</span>
                <button
                  type="button"
                  className="inline-link-button"
                  disabled={pickingSourceRoot}
                  onClick={() => void handleBrowseSourceRoot()}
                >
                  {pickingSourceRoot ? "Opening…" : "Browse…"}
                </button>
              </span>
              <input
                type="text"
                value={projectForm.sourceRoot}
                placeholder="/path/to/existing/repo"
                onDragOver={(event) => event.preventDefault()}
                onDrop={handleSourceRootDrop}
                onChange={(event) => onProjectFormChange({ ...projectForm, sourceRoot: event.target.value })}
              />
            </label>
            <details className="advanced-pane">
              <summary>Optional metadata</summary>
              <div className="advanced-pane__content">
                <div className="field-grid field-grid--two">
                  <label className="field-control">
                    <span>Project type</span>
                    <input
                      type="text"
                      value={projectForm.projectType}
                      onChange={(event) => onProjectFormChange({ ...projectForm, projectType: event.target.value })}
                    />
                  </label>
                  <label className="field-control">
                    <span>Description</span>
                    <input
                      type="text"
                      value={projectForm.description}
                      placeholder="What this project is trying to accomplish"
                      onChange={(event) => onProjectFormChange({ ...projectForm, description: event.target.value })}
                    />
                  </label>
                </div>
              </div>
            </details>
            <p className="project-form__hint">
              Empty source root means a new workspace. A local repo path means import that codebase and show brownfield review state here first.
            </p>
            <div className="surface-card__actions">
              <button
                type="submit"
                className="hero-button hero-button--primary project-form__submit"
                disabled={projectSubmitting}
              >
                {projectSubmitting
                  ? "Working..."
                  : projectForm.sourceRoot.trim()
                    ? "Import repo"
                    : "Create workspace"}
              </button>
            </div>
          </form>
        </article>
      </section>

      <details className="advanced-pane">
        <summary>Archived projects ({archivedProjects.length})</summary>
        <div className="advanced-pane__content">
          <div className="list-stack">
            {archivedProjects.length ? (
              archivedProjects.map((project) => (
                <div key={project.project_id} className="list-row">
                  <div>
                    <strong>{project.name}</strong>
                    <p>
                      Archived {project.archived_at ?? "recently"} · {project.task_count} tasks ·{" "}
                      {formatLabel(project.onboarding_mode ?? "greenfield")}
                    </p>
                  </div>
                  <div className="list-row__meta">
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
                <p>Archive older workspaces when you want the selector to stay focused.</p>
              </div>
            )}
          </div>
        </div>
      </details>
    </section>
  );
}
