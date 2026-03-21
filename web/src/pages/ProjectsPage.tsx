import type { DragEvent, FormEvent } from "react";
import { useEffect, useMemo, useState } from "react";
import { OperatorLoopPanel } from "../components/OperatorLoopPanel";
import {
  fetchEnvironmentDoctor,
  fetchOverview,
  fetchPortfolio,
  fetchProjectTemplates,
  pickLocalDirectory,
  runOrchestratorPass,
  runSupervisorPass,
  updateProjectReviewPolicy
} from "../lib/controlRoomApi";
import type { OperatorLoopItem, OperatorWorkflowState } from "../lib/operatorLoop";
import { setPendingRunFocus } from "../lib/runFocus";
import { setPendingTaskFocus } from "../lib/taskFocus";
import { useLivePulse } from "../lib/useLivePulse";
import type { EnvironmentDoctorResponse, OverviewResponse, PortfolioProject, PortfolioResponse, ProjectSummary, ProjectTemplate } from "../types";

export interface ProjectFormState {
  name: string;
  description: string;
  projectType: string;
  mode: "auto" | "greenfield" | "brownfield";
  sourceRoot: string;
  templateId: string;
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
  onCloneProject: (projectId: string, suggestedName?: string) => Promise<void>;
  onArchiveProject: (projectId: string) => Promise<void>;
  onRestoreProject: (projectId: string) => Promise<void>;
  onDeleteProject: (projectId: string) => Promise<void>;
  operatorWorkflow: OperatorWorkflowState | null;
  operatorWorkflowWarning?: string | null;
  onOpenOperatorItem: (item: OperatorLoopItem) => void;
  onNavigate?: (view: "command" | "work" | "issues" | "agents" | "runs" | "system" | "projects") => void;
}

interface NextStep {
  title: string;
  detail: string;
}

const DEFAULT_PROVIDER_CAPACITY = {
  queue_mode: "running" as const,
  max_running_jobs: 0,
  preferred_provider_id: null as string | null,
  queued_jobs: 0,
  running_jobs: 0,
  at_capacity: false,
  can_start_jobs: false,
  can_launch_jobs: false,
};

const DEFAULT_REVIEW_POLICY = {
  auto_approve_low_risk: false,
  max_priority_for_auto_approve: 0,
  require_verification_pass: true,
};

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
      detail: `${pluralize(portfolioProject?.provider_capacity?.queued_jobs ?? 0, "queued provider job")} are waiting in ${
        portfolioProject?.provider_capacity?.queue_mode ?? "running"
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
  onCloneProject,
  onArchiveProject,
  onRestoreProject,
  onDeleteProject,
  operatorWorkflow,
  operatorWorkflowWarning,
  onOpenOperatorItem,
  onNavigate
}: ProjectsPageProps) {
  const [portfolio, setPortfolio] = useState<PortfolioResponse | null>(null);
  const [selectedOverview, setSelectedOverview] = useState<OverviewResponse | null>(null);
  const [selectedDoctor, setSelectedDoctor] = useState<EnvironmentDoctorResponse | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pendingActionKey, setPendingActionKey] = useState<string | null>(null);
  const [pickingSourceRoot, setPickingSourceRoot] = useState(false);
  const [setupMode, setSetupMode] = useState<"new" | "import" | null>(null);
  const [templates, setTemplates] = useState<ProjectTemplate[]>([]);
  const livePulse = useLivePulse();

  const activeProjects = projects.filter((project) => project.state !== "archived");
  const archivedProjects = projects.filter((project) => project.state === "archived");
  const selectedProject =
    activeProjects.find((project) => project.project_id === selectedProjectId) ?? activeProjects[0] ?? null;
  const selectedPortfolioProject =
    portfolio?.projects.find((project) => project.project_id === selectedProject?.project_id) ?? null;
  const selectedProviderCapacity = selectedPortfolioProject?.provider_capacity ?? DEFAULT_PROVIDER_CAPACITY;
  const selectedReviewPolicy = selectedPortfolioProject?.review_policy ?? DEFAULT_REVIEW_POLICY;
  const otherActiveProjects = activeProjects.filter((project) => project.project_id !== selectedProject?.project_id);
  const portfolioById = useMemo(
    () => new Map((portfolio?.projects ?? []).map((project) => [project.project_id, project])),
    [portfolio?.projects]
  );

  useEffect(() => {
    let mounted = true;

    async function loadPageState() {
      try {
        let usedFallback = false;
        const markFallback = () => {
          usedFallback = true;
        };
        const [portfolioPayload, templatePayload] = await Promise.all([
          fetchPortfolio(undefined, markFallback),
          fetchProjectTemplates(undefined, markFallback),
        ]);
        const [overviewPayload, doctorPayload] = selectedProject
          ? await Promise.all([
              fetchOverview(selectedProject.project_id, undefined, markFallback),
              fetchEnvironmentDoctor(undefined, markFallback, selectedProject.project_id),
            ])
          : [null, null];
        if (!mounted) {
          return;
        }
        setPortfolio(portfolioPayload);
        setTemplates(templatePayload.templates);
        setSelectedOverview(overviewPayload);
        setSelectedDoctor(doctorPayload);
        setNotice(usedFallback ? "Projects refresh used cached data for one or more panels." : null);
      } catch {
        if (!mounted) {
          return;
        }
        setNotice("Projects refresh failed; showing the latest available project state.");
      }
    }

    void loadPageState();
    return () => {
      mounted = false;
    };
  }, [livePulse, selectedProject?.project_id]);

  useEffect(() => {
    if (!projectSubmitting && !projectForm.name && !projectForm.sourceRoot && !projectForm.description) {
      setSetupMode(null);
    }
  }, [projectForm, projectSubmitting]);

  const visibleTemplates = useMemo(() => {
    if (setupMode === "import") {
      return templates.filter((template) => template.mode === "brownfield");
    }
    if (setupMode === "new") {
      return templates.filter((template) => template.mode !== "brownfield");
    }
    return templates;
  }, [setupMode, templates]);

  const selectedTemplate = useMemo(
    () => visibleTemplates.find((template) => template.id === projectForm.templateId) ?? null,
    [projectForm.templateId, visibleTemplates]
  );

  async function handleOrchestratorPass() {
    setPendingActionKey("orchestrator");
    setNotice(null);
    try {
      const payload = await runOrchestratorPass(4, 3, true);
      setPortfolio(await fetchPortfolio());
      if (selectedProject) {
        const [overviewPayload, doctorPayload] = await Promise.all([
          fetchOverview(selectedProject.project_id),
          fetchEnvironmentDoctor(undefined, undefined, selectedProject.project_id),
        ]);
        setSelectedOverview(overviewPayload);
        setSelectedDoctor(doctorPayload);
      }
      const launched = (payload.provider_jobs_processed ?? 0) + (payload.provider_jobs_dispatched ?? 0);
      setNotice(
        `Orchestrator touched ${payload.project_runs.length} projects, assigned ${payload.assigned_count} tasks, and launched ${launched} provider run${launched === 1 ? "" : "s"}.`
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

  function archiveDisabledReason(projectId: string) {
    const portfolioProject = portfolioById.get(projectId);
    if (activeProjects.length <= 1) {
      return "Create another active project before archiving the last one.";
    }
    if ((portfolioProject?.active_sessions ?? 0) > 0 || (portfolioProject?.provider_capacity.running_jobs ?? 0) > 0) {
      return "Wait for active runs to finish before archiving this project.";
    }
    return null;
  }

  function deleteDisabledReason(projectId: string) {
    const portfolioProject = portfolioById.get(projectId);
    if ((portfolioProject?.active_sessions ?? 0) > 0) {
      return "Wait for active sessions to finish before deleting this project.";
    }
    if ((portfolioProject?.provider_capacity.queued_jobs ?? 0) > 0 || (portfolioProject?.provider_capacity.running_jobs ?? 0) > 0) {
      return "Queued or running provider jobs must finish before this project can be deleted.";
    }
    return null;
  }

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

      <OperatorLoopPanel
        workflow={operatorWorkflow}
        compact
        maxItems={3}
        title="Workspace posture, not incident routing"
        description="Projects owns onboarding, workspace lifecycle, and policy posture. Review and recovery still route through Command, Issues, and Runs."
        onSelectItem={onOpenOperatorItem}
        warning={operatorWorkflowWarning}
        footer={
          <div className="surface-card__actions">
            {onNavigate ? (
              <button
                type="button"
                className="hero-button hero-button--primary hero-button--compact"
                onClick={() => onNavigate("command")}
              >
                Open command
              </button>
            ) : null}
            {onNavigate ? (
              <button
                type="button"
                className="hero-button hero-button--ghost hero-button--compact"
                onClick={() => onNavigate("issues")}
              >
                Open issues
              </button>
            ) : null}
            {onNavigate ? (
              <button
                type="button"
                className="hero-button hero-button--ghost hero-button--compact"
                onClick={() => onNavigate("runs")}
              >
                Open runs
              </button>
            ) : null}
          </div>
        }
      />

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
                  <strong>{selectedProviderCapacity.queued_jobs}</strong>
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
              {selectedDoctor ? (
                <div className="list-row">
                  <div>
                    <span className="eyebrow">Environment doctor</span>
                    <strong>{selectedDoctor.summary.summary}</strong>
                    <p>{selectedDoctor.progress.detail}</p>
                  </div>
                  <div className="list-row__meta">
                    <span className={`status-pill status-pill--${selectedDoctor.summary.status === "blocked" ? "danger" : selectedDoctor.summary.status === "ready" ? "default" : "warn"}`}>
                      {selectedDoctor.summary.label}
                    </span>
                  </div>
                </div>
              ) : null}
              <div className="surface-card__actions">
                {onNavigate ? (
                  <button
                    type="button"
                    className="hero-button hero-button--primary hero-button--compact"
                    onClick={() => onNavigate("command")}
                  >
                    Open command
                  </button>
                ) : null}
                {onNavigate ? (
                  <button
                    type="button"
                    className="hero-button hero-button--ghost hero-button--compact"
                    onClick={() => onNavigate("work")}
                  >
                    Open work
                  </button>
                ) : null}
                <button
                  type="button"
                  className="hero-button hero-button--ghost hero-button--compact"
                  onClick={() => onSelectProject(selectedProject.project_id)}
                >
                  Keep selected
                </button>
                <button
                  type="button"
                  className="hero-button hero-button--ghost hero-button--compact"
                  disabled={projectSubmitting}
                  onClick={() => {
                    const nextName = window.prompt("Clone project as", `${selectedProject.name} copy`);
                    if (nextName == null) {
                      return;
                    }
                    void onCloneProject(selectedProject.project_id, nextName);
                  }}
                >
                  Clone for fresh run
                </button>
                <button
                  type="button"
                  className="hero-button hero-button--ghost hero-button--compact"
                  disabled={projectSubmitting || archiveDisabledReason(selectedProject.project_id) != null}
                  onClick={() => void onArchiveProject(selectedProject.project_id)}
                  title={archiveDisabledReason(selectedProject.project_id) ?? undefined}
                >
                  Archive project
                </button>
                <button
                  type="button"
                  className="hero-button hero-button--ghost hero-button--compact"
                  disabled={projectSubmitting || deleteDisabledReason(selectedProject.project_id) != null}
                  title={deleteDisabledReason(selectedProject.project_id) ?? undefined}
                  onClick={() => {
                    if (!window.confirm(`Delete ${selectedProject.name}? This removes its MAAS state${selectedProject.source_root ? " and any generated workspace path if MAAS created it" : ""}.`)) {
                      return;
                    }
                    void onDeleteProject(selectedProject.project_id);
                  }}
                >
                  Delete project
                </button>
              </div>
              {archiveDisabledReason(selectedProject.project_id) ? (
                <p className="field-hint">{archiveDisabledReason(selectedProject.project_id)}</p>
              ) : null}
              {deleteDisabledReason(selectedProject.project_id) ? (
                <p className="field-hint">{deleteDisabledReason(selectedProject.project_id)}</p>
              ) : null}
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
                {onNavigate ? (
                  <button
                    type="button"
                    className="hero-button hero-button--ghost hero-button--compact"
                    onClick={() => onNavigate("command")}
                  >
                    Open command
                  </button>
                ) : null}
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
                        setSelectedOverview(await fetchOverview(selectedProject.project_id));
                        setNotice("Supervisor pass completed. The import review task is ready for inspection.");
                        onNavigate?.("command");
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
                    onClick={() => onNavigate("work")}
                  >
                    Open work
                  </button>
                ) : null}
                <button
                  type="button"
                  className="hero-button hero-button--ghost hero-button--compact"
                  disabled={pendingActionKey === "orchestrator"}
                  onClick={() => void handleOrchestratorPass()}
                >
                  {pendingActionKey === "orchestrator" ? "Running..." : "Run"}
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

      {selectedProject && selectedPortfolioProject ? (
        <section className="single-column-grid">
          <article className="surface-card">
            <div className="surface-card__header">
              <div>
                <span className="eyebrow">Review policy</span>
                <h2>Reduce manual review load</h2>
              </div>
            </div>
            <div className="detail-grid">
              <div>
                <span>Auto-approve low-risk work</span>
                <strong>{selectedReviewPolicy.auto_approve_low_risk ? "Enabled" : "Disabled"}</strong>
              </div>
              <div>
                <span>Priority ceiling</span>
                <strong>{selectedReviewPolicy.max_priority_for_auto_approve}</strong>
              </div>
              <div>
                <span>Verification required</span>
                <strong>{selectedReviewPolicy.require_verification_pass ? "Required" : "Optional"}</strong>
              </div>
            </div>
            <p className="project-form__hint">
              Low-risk issues with passing verification can skip the manual review queue when this policy is enabled.
            </p>
            <div className="surface-card__actions">
              <button
                type="button"
                className="hero-button hero-button--compact"
                disabled={pendingActionKey === "review-policy:toggle"}
                onClick={async () => {
                  setPendingActionKey("review-policy:toggle");
                  setNotice(null);
                  try {
                    await updateProjectReviewPolicy(selectedProject.project_id, {
                      auto_approve_low_risk: !selectedReviewPolicy.auto_approve_low_risk,
                      max_priority_for_auto_approve: selectedReviewPolicy.max_priority_for_auto_approve,
                      require_verification_pass: selectedReviewPolicy.require_verification_pass,
                    });
                    setPortfolio(await fetchPortfolio());
                    setNotice(
                      !selectedReviewPolicy.auto_approve_low_risk
                        ? "Enabled low-risk auto-approval."
                        : "Disabled low-risk auto-approval."
                    );
                  } catch {
                    setNotice("Could not update the review policy.");
                  } finally {
                    setPendingActionKey(null);
                  }
                }}
              >
                {selectedReviewPolicy.auto_approve_low_risk ? "Disable auto-approve" : "Enable auto-approve"}
              </button>
              <button
                type="button"
                className="hero-button hero-button--ghost hero-button--compact"
                disabled={pendingActionKey === "review-policy:tighten"}
                onClick={async () => {
                  setPendingActionKey("review-policy:tighten");
                  setNotice(null);
                  try {
                    await updateProjectReviewPolicy(selectedProject.project_id, {
                      auto_approve_low_risk: selectedReviewPolicy.auto_approve_low_risk,
                      max_priority_for_auto_approve: Math.max(0, selectedReviewPolicy.max_priority_for_auto_approve - 10),
                      require_verification_pass: true,
                    });
                    setPortfolio(await fetchPortfolio());
                    setNotice("Tightened the auto-approve priority ceiling.");
                  } catch {
                    setNotice("Could not update the review policy.");
                  } finally {
                    setPendingActionKey(null);
                  }
                }}
              >
                Tighten policy
              </button>
              <button
                type="button"
                className="hero-button hero-button--ghost hero-button--compact"
                disabled={pendingActionKey === "review-policy:loosen"}
                onClick={async () => {
                  setPendingActionKey("review-policy:loosen");
                  setNotice(null);
                  try {
                    await updateProjectReviewPolicy(selectedProject.project_id, {
                      auto_approve_low_risk: selectedReviewPolicy.auto_approve_low_risk,
                      max_priority_for_auto_approve: selectedReviewPolicy.max_priority_for_auto_approve + 10,
                      require_verification_pass: selectedReviewPolicy.require_verification_pass,
                    });
                    setPortfolio(await fetchPortfolio());
                    setNotice("Expanded the auto-approve priority ceiling.");
                  } catch {
                    setNotice("Could not update the review policy.");
                  } finally {
                    setPendingActionKey(null);
                  }
                }}
              >
                Expand policy
              </button>
            </div>
          </article>
        </section>
      ) : null}

      {portfolio ? (
        <section className="single-column-grid">
          <article className="surface-card">
            <div className="surface-card__header">
              <div>
                <span className="eyebrow">Cross-project supervision</span>
                <h2>What needs attention across all active projects</h2>
              </div>
            </div>
            <div className="detail-grid">
              <div>
                <span>Review queue</span>
                <strong>{portfolio.summary.review_queue}</strong>
              </div>
              <div>
                <span>Blocked failures</span>
                <strong>{portfolio.summary.blocked_failures}</strong>
              </div>
              <div>
                <span>Suspect runs</span>
                <strong>{portfolio.summary.suspect_runs}</strong>
              </div>
              <div>
                <span>Stale agents</span>
                <strong>{portfolio.summary.stale_agents}</strong>
              </div>
            </div>
            <div className="two-column-grid">
              <div className="list-stack">
                <div className="list-row">
                  <div>
                    <strong>Review queue</strong>
                    <p>Cross-project issues waiting on operator judgment.</p>
                  </div>
                </div>
                {(portfolio.command_center.review_queue ?? []).slice(0, 5).map((item) => (
                  <button
                    key={item.task_id}
                    type="button"
                    className="list-row list-row--button"
                    onClick={() => {
                      onSelectProject(item.project_id);
                      setPendingTaskFocus(item.task_id);
                      onNavigate?.("issues");
                    }}
                  >
                    <div>
                      <strong>{item.title}</strong>
                      <p>
                        {item.project_name} · {item.agent_name ?? "Unassigned"} · {item.goal_title ?? "No goal"}
                      </p>
                    </div>
                    <div className="list-row__meta">
                      <span className="status-pill status-pill--warn">{item.priority}</span>
                    </div>
                  </button>
                ))}
                {!portfolio.command_center.review_queue?.length ? (
                  <div className="empty-state empty-state--compact">
                    <strong>No review backlog.</strong>
                    <p>Nothing across the portfolio is waiting on operator approval.</p>
                  </div>
                ) : null}
              </div>

              <div className="list-stack">
                <div className="list-row">
                  <div>
                    <strong>Blocked failures and suspect runs</strong>
                    <p>Use this to jump straight to the project that is drifting or failing.</p>
                  </div>
                </div>
                {(portfolio.command_center.blocked_failures ?? []).slice(0, 3).map((item) => (
                  <button
                    key={item.task_id}
                    type="button"
                    className="list-row list-row--button"
                    onClick={() => {
                      onSelectProject(item.project_id);
                      setPendingTaskFocus(item.task_id);
                      onNavigate?.("issues");
                    }}
                  >
                    <div>
                      <strong>{item.title}</strong>
                      <p>
                        {item.project_name} · {item.failure_count ?? 0} failures · {item.agent_name ?? "No owner"}
                      </p>
                    </div>
                    <div className="list-row__meta">
                      <span className="status-pill status-pill--danger">Blocked</span>
                    </div>
                  </button>
                ))}
                {(portfolio.command_center.suspect_runs ?? []).slice(0, 3).map((item) => (
                  <button
                    key={item.session_id}
                    type="button"
                    className="list-row list-row--button"
                    onClick={() => {
                      onSelectProject(item.project_id);
                      setPendingRunFocus(item.session_id);
                      onNavigate?.("runs");
                    }}
                  >
                    <div>
                      <strong>{item.task_title ?? item.session_id}</strong>
                      <p>
                        {item.project_name} · {item.agent_name ?? item.provider_type} · {item.status}
                      </p>
                    </div>
                    <div className="list-row__meta">
                      <span className="status-pill status-pill--warn">Run</span>
                    </div>
                  </button>
                ))}
                {!portfolio.command_center.blocked_failures?.length && !portfolio.command_center.suspect_runs?.length ? (
                  <div className="empty-state empty-state--compact">
                    <strong>No portfolio-wide failures.</strong>
                    <p>Blocked failures and suspect runs will appear here across active projects.</p>
                  </div>
                ) : null}
              </div>
            </div>
          </article>
        </section>
      ) : null}

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
                        disabled={projectSubmitting || archiveDisabledReason(project.project_id) != null}
                        onClick={() => void onArchiveProject(project.project_id)}
                        title={archiveDisabledReason(project.project_id) ?? undefined}
                      >
                        Archive
                      </button>
                    ) : null}
                    <button
                      type="button"
                      className="hero-button hero-button--ghost hero-button--compact"
                      disabled={projectSubmitting || deleteDisabledReason(project.project_id) != null}
                      title={deleteDisabledReason(project.project_id) ?? undefined}
                      onClick={() => {
                        if (!window.confirm(`Delete ${project.name}? This removes its MAAS state${project.source_root ? " and any generated workspace path if MAAS created it" : ""}.`)) {
                          return;
                        }
                        void onDeleteProject(project.project_id);
                      }}
                    >
                      Delete
                    </button>
                  </div>
                  {archiveDisabledReason(project.project_id) ? (
                    <p className="field-hint">{archiveDisabledReason(project.project_id)}</p>
                  ) : null}
                  {deleteDisabledReason(project.project_id) ? (
                    <p className="field-hint">{deleteDisabledReason(project.project_id)}</p>
                  ) : null}
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
              <h2>Start another workspace</h2>
            </div>
          </div>
          {setupMode == null ? (
            <div className="project-setup-chooser">
              <p className="surface-card__copy">Choose the job you want MAAS to do, then fill only the fields that matter.</p>
              <div className="surface-card__actions">
                <button
                  type="button"
                  className="hero-button hero-button--primary hero-button--compact"
                  onClick={() => {
                    setSetupMode("import");
                    onProjectFormChange({ ...projectForm, mode: "brownfield", templateId: "import-codex" });
                  }}
                >
                  Import repo
                </button>
                <button
                  type="button"
                  className="hero-button hero-button--ghost hero-button--compact"
                  onClick={() => {
                    setSetupMode("new");
                    onProjectFormChange({ ...projectForm, mode: "greenfield", sourceRoot: "", templateId: "scratch-codex" });
                  }}
                >
                  Fresh test workspace
                </button>
              </div>
            </div>
          ) : (
            <form className="project-form project-form--stack" onSubmit={onCreateProject}>
              <div className="surface-card__actions">
                <span className="status-chip">{setupMode === "import" ? "Brownfield import" : "Greenfield workspace"}</span>
                <button
                  type="button"
                  className="hero-button hero-button--ghost hero-button--compact"
                  onClick={() => {
                    setSetupMode(null);
                    onProjectFormChange({
                      ...projectForm,
                      mode: "greenfield",
                      sourceRoot: "",
                      templateId: "",
                    });
                  }}
                >
                  Hide setup
                </button>
              </div>
              {visibleTemplates.length ? (
                <label className="field-control">
                  <span>Template</span>
                  <select
                    value={projectForm.templateId}
                    onChange={(event) => {
                      const nextTemplate = visibleTemplates.find((template) => template.id === event.target.value) ?? null;
                      onProjectFormChange({
                        ...projectForm,
                        templateId: event.target.value,
                        mode: nextTemplate?.mode ?? projectForm.mode,
                        projectType: nextTemplate?.project_type ?? projectForm.projectType,
                      });
                    }}
                  >
                    <option value="">No template</option>
                    {visibleTemplates.map((template) => (
                      <option key={template.id} value={template.id}>
                        {template.name}
                      </option>
                    ))}
                  </select>
                  {selectedTemplate ? <span className="field-hint">{selectedTemplate.description}</span> : null}
                </label>
              ) : null}
              <label className="field-control">
                <span>Name</span>
                <input
                  type="text"
                  value={projectForm.name}
                  placeholder={setupMode === "import" ? "Imported repo name" : "Payments platform"}
                  onChange={(event) => onProjectFormChange({ ...projectForm, name: event.target.value })}
                  required
                />
              </label>
              {setupMode === "import" ? (
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
                    required
                  />
                </label>
              ) : (
                <p className="project-form__hint">
                  {(selectedTemplate?.create_source_root ?? true)
                    ? (
                      <>
                        Leave the source root blank and MAAS will create a fresh workspace folder under{" "}
                        <code>workspaces/&lt;project-name&gt;</code> in this repo root.
                      </>
                    )
                    : "This template expects an existing repo path instead of provisioning a fresh workspace."}
                </p>
              )}
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
                {setupMode === "import"
                  ? "Point MAAS at a local repo and it will open with a brownfield review flow before wider automation."
                  : "Create a clean workspace and let MAAS seed the first greenfield plan. Use Delete project later if you want to wipe the MAAS state and generated workspace."}
              </p>
              <div className="surface-card__actions">
                <button
                  type="submit"
                  className="hero-button hero-button--primary project-form__submit"
                  disabled={projectSubmitting}
                >
                  {projectSubmitting ? "Working..." : setupMode === "import" ? "Import repo" : "Create workspace"}
                </button>
              </div>
            </form>
          )}
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
                    <button
                      type="button"
                      className="hero-button hero-button--ghost hero-button--compact"
                      disabled={projectSubmitting || deleteDisabledReason(project.project_id) != null}
                      title={deleteDisabledReason(project.project_id) ?? undefined}
                      onClick={() => {
                        if (!window.confirm(`Delete ${project.name}? This removes its MAAS state${project.source_root ? " and any generated workspace path if MAAS created it" : ""}.`)) {
                          return;
                        }
                        void onDeleteProject(project.project_id);
                      }}
                    >
                      Delete
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
