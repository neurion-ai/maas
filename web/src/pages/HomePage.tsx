import { useEffect, useMemo, useState } from "react";
import { StatCard } from "../components/StatCard";
import {
  fetchOverview,
  fetchPortfolio,
  refreshRepoPlan,
  rescanBrownfieldProject,
  runAlertOperatorAction,
  runFailureOperatorAction,
  runOrchestratorPass,
  runSupervisorPass
} from "../lib/controlRoomApi";
import { reviewTask } from "../lib/boardApi";
import { useLivePulse } from "../lib/useLivePulse";
import type { OverviewResponse, PortfolioResponse } from "../types";

type HomeViewTarget = "work" | "runs" | "incidents" | "projects";

interface Recommendation {
  id: string;
  tone: "default" | "warn" | "danger";
  label: string;
  summary: string;
  actionLabel: string;
  action: () => void | Promise<void>;
}

interface HomePageProps {
  onNavigate: (view: HomeViewTarget) => void;
}

function formatPriority(priority: number) {
  if (priority >= 90) {
    return "Critical";
  }
  if (priority >= 75) {
    return "High";
  }
  if (priority >= 50) {
    return "Medium";
  }
  return "Low";
}

function formatTime(value?: string | null) {
  if (!value) {
    return "Not yet";
  }
  return new Date(value).toLocaleString();
}

export function HomePage({ onNavigate }: HomePageProps) {
  const [overview, setOverview] = useState<OverviewResponse | null>(null);
  const [portfolio, setPortfolio] = useState<PortfolioResponse | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pendingActionKey, setPendingActionKey] = useState<string | null>(null);
  const livePulse = useLivePulse();

  async function loadHome() {
    const [overviewPayload, portfolioPayload] = await Promise.all([fetchOverview(), fetchPortfolio()]);
    setOverview(overviewPayload);
    setPortfolio(portfolioPayload);
  }

  useEffect(() => {
    let mounted = true;

    async function load() {
      try {
        const [overviewPayload, portfolioPayload] = await Promise.all([fetchOverview(), fetchPortfolio()]);
        if (!mounted) {
          return;
        }
        setOverview(overviewPayload);
        setPortfolio(portfolioPayload);
      } catch {
        if (mounted) {
          setNotice("Home refresh failed; keeping the latest available operating picture.");
        }
      }
    }

    void load();
    return () => {
      mounted = false;
    };
  }, [livePulse]);

  async function handleSupervisorPass() {
    setPendingActionKey("supervisor");
    setNotice(null);
    try {
      const payload = await runSupervisorPass(3);
      await loadHome();
      setNotice(
        `Supervisor refreshed ${payload.ready_changes.length} tasks and assigned ${payload.assigned_count} new sessions.`
      );
    } catch {
      setNotice("Supervisor pass failed; keeping the current operating picture.");
    } finally {
      setPendingActionKey(null);
    }
  }

  async function handleOrchestratorPass() {
    setPendingActionKey("orchestrator");
    setNotice(null);
    try {
      const payload = await runOrchestratorPass(4, 2);
      await loadHome();
      setNotice(
        `Orchestrator touched ${payload.project_runs.length} projects, assigned ${payload.assigned_count} tasks, and processed ${payload.provider_jobs_processed} provider jobs.`
      );
    } catch {
      setNotice("Orchestrator pass failed; keeping the current operating picture.");
    } finally {
      setPendingActionKey(null);
    }
  }

  async function handleRefreshRepoPlan() {
    const projectId = overview?.project?.project_id;
    if (!projectId) {
      return;
    }
    setPendingActionKey("repo-plan");
    setNotice(null);
    try {
      const payload = await refreshRepoPlan(projectId);
      await loadHome();
      setNotice(
        `Repo-grounded plan refreshed: ${payload.preview?.generated_task_count ?? 0} proposed items, ${payload.created_task_ids?.length ?? 0} created, ${payload.updated_task_ids?.length ?? 0} updated.`
      );
    } catch {
      setNotice("Repo-grounded plan refresh failed; keeping the current backlog shape.");
    } finally {
      setPendingActionKey(null);
    }
  }

  async function handleRescanBrownfield() {
    const projectId = overview?.project?.project_id;
    if (!projectId) {
      return;
    }
    setPendingActionKey("brownfield-rescan");
    setNotice(null);
    try {
      const payload = await rescanBrownfieldProject(projectId);
      await loadHome();
      setNotice(
        payload.drift?.detected
          ? `Imported repo changed and review reopened: ${payload.drift?.summary ?? "material drift detected"}.`
          : "Brownfield rescan completed with no material drift."
      );
    } catch {
      setNotice("Brownfield rescan failed; keeping the current imported understanding.");
    } finally {
      setPendingActionKey(null);
    }
  }

  async function handleOnboardingReview(decision: "approve" | "reject") {
    const taskId = overview?.onboarding?.review_task_id;
    if (!taskId) {
      return;
    }
    setPendingActionKey(`onboarding:${decision}`);
    setNotice(null);
    try {
      await reviewTask(taskId, decision);
      await loadHome();
      setNotice(
        decision === "approve"
          ? "Imported work approved and released into normal execution."
          : "Imported work sent back for changes; gated tasks remain blocked."
      );
    } catch {
      setNotice("Onboarding review action failed; keep the imported work under review.");
    } finally {
      setPendingActionKey(null);
    }
  }

  const recommendations = useMemo<Recommendation[]>(() => {
    const next: Recommendation[] = [];

    if (!overview?.project) {
      next.push({
        id: "create-project",
        tone: "default",
        label: "Create or import a project",
        summary: "MAAS is running, but there is no active project selected yet.",
        actionLabel: "Open project setup",
        action: () => onNavigate("projects")
      });
      return next;
    }

    if (
      overview.onboarding?.mode === "brownfield" &&
      overview.onboarding.review_required &&
      overview.onboarding.review_task_status === "review"
    ) {
      next.push({
        id: "review-import",
        tone: "warn",
        label: "Review imported repo before release",
        summary: `${overview.onboarding.pending_gated_tasks} imported tasks are waiting behind onboarding approval.`,
        actionLabel: "Approve import",
        action: () => handleOnboardingReview("approve")
      });
    }

    if (overview.onboarding?.drift_summary?.detected) {
      next.push({
        id: "rescan-drift",
        tone: "warn",
        label: "Imported repo drift was detected",
        summary: overview.onboarding.drift_summary.summary ?? "Files, workflows, or repo areas changed since the last brownfield scan.",
        actionLabel: "Rescan import",
        action: () => handleRescanBrownfield()
      });
    }

    if (overview.onboarding?.repo_plan_state?.stale) {
      next.push({
        id: "refresh-repo-plan",
        tone: "default",
        label: "Refresh repo-grounded plan",
        summary: "The plan synthesis is stale relative to the imported repository map.",
        actionLabel: "Refresh plan",
        action: () => handleRefreshRepoPlan()
      });
    }

    const failureAction = overview.recent_failures.find((item) => item.operator_action)?.operator_action;
    if (failureAction) {
      next.push({
        id: "failure-action",
        tone: "danger",
        label: "Resolve the latest failure incident",
        summary: overview.recent_failures[0]?.summary ?? "A recent failure still needs operator attention.",
        actionLabel: failureAction.label,
        action: () => runFailureOperatorAction(failureAction).then(loadHome)
      });
    }

    const repeatedAction = overview.repeated_failures.find((item) => item.operator_action)?.operator_action;
    if (repeatedAction) {
      next.push({
        id: "repeated-failure",
        tone: "warn",
        label: "Clear repeated-failure pressure",
        summary: "One or more tasks are still tripping the repeated-failure threshold.",
        actionLabel: repeatedAction.label,
        action: () => runAlertOperatorAction(repeatedAction).then(loadHome)
      });
    }

    if ((portfolio?.summary.queued_provider_jobs ?? 0) > 0) {
      next.push({
        id: "provider-queue",
        tone: "default",
        label: "Queued provider jobs are waiting",
        summary: `${portfolio?.summary.queued_provider_jobs ?? 0} jobs are ready for execution in the provider queue.`,
        actionLabel: "Open runs",
        action: () => onNavigate("runs")
      });
    }

    if ((overview.summary.tasks_in_progress ?? 0) === 0 && (overview.summary.tasks_review ?? 0) === 0) {
      next.push({
        id: "kick-execution",
        tone: "default",
        label: "Run a supervised allocation pass",
        summary: "There is no active execution at the moment; MAAS can refresh readiness and assign new work.",
        actionLabel: "Run supervisor",
        action: () => handleSupervisorPass()
      });
    }

    if ((portfolio?.summary.projects_with_issues ?? 0) > 0) {
      next.push({
        id: "portfolio-issues",
        tone: "warn",
        label: "Portfolio health needs attention",
        summary: `${portfolio?.summary.projects_with_issues ?? 0} projects currently have open issues or blocked work.`,
        actionLabel: "Open projects",
        action: () => onNavigate("projects")
      });
    }

    return next.slice(0, 5);
  }, [onNavigate, overview, portfolio]);

  const onboardingChecklist = useMemo(() => {
    if (!overview?.onboarding) {
      return [];
    }
    const mode = overview.onboarding.mode;
    if (mode === "brownfield") {
      return [
        {
          label: "Scan imported repo",
          done: Boolean(overview.onboarding.last_scanned_at),
          detail: overview.onboarding.last_scanned_at
            ? `Last scanned ${formatTime(overview.onboarding.last_scanned_at)}`
            : "No import scan recorded yet."
        },
        {
          label: "Review workflows and runbooks",
          done: (overview.onboarding.discovery_summary.workflow_details?.length ?? 0) > 0,
          detail: `${overview.onboarding.discovery_summary.workflow_details?.length ?? 0} workflows and ${overview.onboarding.discovery_summary.runbook_commands?.length ?? 0} runbook commands discovered.`
        },
        {
          label: "Approve imported backlog",
          done: overview.onboarding.review_status === "approved",
          detail:
            overview.onboarding.review_status === "approved"
              ? `Approved by ${overview.onboarding.reviewed_by ?? "operator"} on ${formatTime(overview.onboarding.reviewed_at)}`
              : `${overview.onboarding.pending_gated_tasks} gated tasks are still waiting.`
        },
        {
          label: "Refresh repo-grounded plan",
          done: Boolean(overview.onboarding.repo_plan_state?.last_refreshed_at),
          detail: overview.onboarding.repo_plan_state?.last_refreshed_at
            ? `Last refreshed ${formatTime(overview.onboarding.repo_plan_state.last_refreshed_at)}`
            : "Repo-grounded plan has not been refreshed yet."
        }
      ];
    }

    return [
      {
        label: "Create project and seed initial backlog",
        done: (overview.summary.tasks_total ?? 0) > 0,
        detail: `${overview.summary.tasks_total} tasks currently exist in the workspace.`
      },
      {
        label: "Run first supervised pass",
        done: (overview.summary.tasks_in_progress ?? 0) > 0 || (overview.summary.tasks_review ?? 0) > 0,
        detail:
          (overview.summary.tasks_in_progress ?? 0) > 0 || (overview.summary.tasks_review ?? 0) > 0
            ? "MAAS has already started moving work through execution."
            : "No work is currently in progress."
      },
      {
        label: "Validate runtime readiness",
        done: (portfolio?.summary.queued_provider_jobs ?? 0) >= 0,
        detail: "Use the Runs surface to preflight providers and queue the first execution."
      }
    ];
  }, [overview, portfolio]);

  const projectName = overview?.project?.name ?? "No active project";
  const projectDescription = overview?.project?.description ?? "Create or import a project to start supervising work.";

  return (
    <section className="dashboard-page">
      <header className="dashboard-hero">
        <div className="dashboard-hero__content">
          <span className="eyebrow">Home</span>
          <h1>{projectName}</h1>
          <p>{projectDescription}</p>
          <div className="hero-meta">
            <span className="hero-meta__pill">
              {overview?.onboarding?.mode === "brownfield" ? "Brownfield import" : "Greenfield workspace"}
            </span>
            <span className="hero-meta__pill">
              {overview?.summary.tasks_in_progress ?? 0} in progress · {overview?.summary.tasks_review ?? 0} in review
            </span>
            <span className="hero-meta__pill">
              {portfolio?.summary.projects_with_issues ?? 0} projects with issues
            </span>
          </div>
        </div>
        <div className="dashboard-hero__actions">
          <button
            type="button"
            className="hero-button hero-button--primary"
            disabled={pendingActionKey === "supervisor"}
            onClick={() => void handleSupervisorPass()}
          >
            {pendingActionKey === "supervisor" ? "Running supervisor..." : "Run supervisor"}
          </button>
          <button
            type="button"
            className="hero-button"
            disabled={pendingActionKey === "orchestrator"}
            onClick={() => void handleOrchestratorPass()}
          >
            {pendingActionKey === "orchestrator" ? "Running orchestrator..." : "Run orchestrator"}
          </button>
          <button type="button" className="hero-button hero-button--ghost" onClick={() => onNavigate("work")}>
            Open workbench
          </button>
        </div>
      </header>

      {notice ? <div className="banner banner--info">{notice}</div> : null}

      <section className="stats-grid stats-grid--dense">
        <StatCard label="Tasks in motion" value={overview?.summary.tasks_in_progress ?? 0} />
        <StatCard label="Waiting review" value={overview?.summary.tasks_review ?? 0} tone="warn" />
        <StatCard label="Blocked work" value={overview?.summary.tasks_blocked ?? 0} tone="warn" />
        <StatCard label="Open alerts" value={overview?.summary.alerts_open ?? 0} tone="warn" />
        <StatCard label="Failures logged" value={overview?.summary.failures_total ?? 0} tone="warn" />
        <StatCard label="Running agents" value={overview?.summary.agents_running ?? 0} tone="good" />
        <StatCard label="Queued jobs" value={portfolio?.summary.queued_provider_jobs ?? 0} />
        <StatCard label="Active projects" value={portfolio?.summary.active_projects ?? 0} />
      </section>

      <section className="two-column-grid">
        <article className="surface-card">
          <div className="surface-card__header">
            <div>
              <span className="eyebrow">Recommended next</span>
              <h2>Start here</h2>
            </div>
            <button type="button" className="text-link" onClick={() => onNavigate("incidents")}>
              Open incidents
            </button>
          </div>
          <div className="action-stack">
            {recommendations.length ? (
              recommendations.map((item) => (
                <div key={item.id} className={`action-card action-card--${item.tone}`}>
                  <div>
                    <strong>{item.label}</strong>
                    <p>{item.summary}</p>
                  </div>
                  <button
                    type="button"
                    className="hero-button hero-button--compact"
                    onClick={() => void item.action()}
                  >
                    {item.actionLabel}
                  </button>
                </div>
              ))
            ) : (
              <div className="empty-state empty-state--compact">
                <strong>Nothing urgent is blocking the project.</strong>
                <p>Use Work to steer execution, Runs to supervise providers, or Projects to scan the broader portfolio.</p>
              </div>
            )}
          </div>
        </article>

        <article className="surface-card">
          <div className="surface-card__header">
            <div>
              <span className="eyebrow">First-run guide</span>
              <h2>What MAAS is doing</h2>
            </div>
            {overview?.onboarding?.mode === "brownfield" ? (
              <button
                type="button"
                className="text-link"
                disabled={pendingActionKey === "brownfield-rescan"}
                onClick={() => void handleRescanBrownfield()}
              >
                {pendingActionKey === "brownfield-rescan" ? "Rescanning..." : "Rescan import"}
              </button>
            ) : null}
          </div>
          <div className="checklist">
            {onboardingChecklist.map((item) => (
              <div key={item.label} className={`checklist__item ${item.done ? "is-done" : ""}`}>
                <div className="checklist__marker" />
                <div>
                  <strong>{item.label}</strong>
                  <p>{item.detail}</p>
                </div>
              </div>
            ))}
          </div>
          {overview?.onboarding?.mode === "brownfield" && overview.onboarding.review_task_status === "review" ? (
            <div className="surface-card__actions">
              <button
                type="button"
                className="hero-button hero-button--primary"
                disabled={pendingActionKey === "onboarding:approve"}
                onClick={() => void handleOnboardingReview("approve")}
              >
                {pendingActionKey === "onboarding:approve" ? "Approving..." : "Approve imported backlog"}
              </button>
              <button
                type="button"
                className="hero-button"
                disabled={pendingActionKey === "onboarding:reject"}
                onClick={() => void handleOnboardingReview("reject")}
              >
                {pendingActionKey === "onboarding:reject" ? "Rejecting..." : "Request changes"}
              </button>
              <button
                type="button"
                className="hero-button hero-button--ghost"
                disabled={pendingActionKey === "repo-plan"}
                onClick={() => void handleRefreshRepoPlan()}
              >
                {pendingActionKey === "repo-plan" ? "Refreshing..." : "Refresh repo plan"}
              </button>
            </div>
          ) : null}
        </article>
      </section>

      <section className="two-column-grid">
        <article className="surface-card">
          <div className="surface-card__header">
            <div>
              <span className="eyebrow">Execution focus</span>
              <h2>Active work</h2>
            </div>
            <button type="button" className="text-link" onClick={() => onNavigate("work")}>
              Open work surface
            </button>
          </div>
          <div className="list-stack">
            {(overview?.active_work ?? []).length ? (
              overview?.active_work.map((item) => (
                <div key={item.task_id} className="list-row">
                  <div>
                    <strong>{item.title}</strong>
                    <p>
                      {item.goal_title ?? "Unlinked goal"}
                      {item.agent_name ? ` · ${item.agent_name}` : ""}
                    </p>
                    <p>
                      {item.status}
                      {item.last_retry_reason ? ` · last retry ${item.last_retry_reason}` : ""}
                      {item.next_retry_at ? ` · next retry ${formatTime(item.next_retry_at)}` : ""}
                    </p>
                  </div>
                  <div className="list-row__meta">
                    <span className="status-pill">{formatPriority(item.priority)}</span>
                  </div>
                </div>
              ))
            ) : (
              <div className="empty-state empty-state--compact">
                <strong>No work is actively running right now.</strong>
                <p>Run a supervisor pass or open Work to inspect the ready queue.</p>
              </div>
            )}
          </div>
        </article>

        <article className="surface-card">
          <div className="surface-card__header">
            <div>
              <span className="eyebrow">Recent movement</span>
              <h2>Latest activity</h2>
            </div>
            <button type="button" className="text-link" onClick={() => onNavigate("runs")}>
              Open runs
            </button>
          </div>
          <div className="list-stack">
            {(overview?.recent_activity ?? []).length ? (
              overview?.recent_activity.slice(0, 6).map((item) => (
                <div key={item.activity_id ?? `${item.action}:${item.created_at}`} className="list-row">
                  <div>
                    <strong>{item.description}</strong>
                    <p>
                      {item.action}
                      {item.task_id ? ` · ${item.task_id}` : ""}
                      {item.agent_id ? ` · ${item.agent_id}` : ""}
                    </p>
                  </div>
                  <div className="list-row__meta">
                    <span className={`status-pill status-pill--${item.severity === "critical" ? "danger" : item.severity === "warning" ? "warn" : "default"}`}>
                      {item.severity}
                    </span>
                    <span>{formatTime(item.created_at)}</span>
                  </div>
                </div>
              ))
            ) : (
              <div className="empty-state empty-state--compact">
                <strong>No recent activity yet.</strong>
                <p>Once agents start running or policies trigger, the control room will show it here.</p>
              </div>
            )}
          </div>
        </article>
      </section>
    </section>
  );
}
