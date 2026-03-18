import { useEffect, useMemo, useState } from "react";
import {
  fetchAgentRoster,
  fetchIncidentTimeline,
  fetchOverview,
  fetchPortfolio,
  fetchRecoveryPolicy,
  refreshRepoPlan,
  recoverAgent,
  rescanBrownfieldProject,
  resetTaskCircuitBreaker,
  resetTaskRetryState,
  restoreAndRequeueQuarantineEntry,
  restoreQuarantineEntry,
  runAlertOperatorAction,
  runOrchestratorPass,
  runSupervisorPass
} from "../lib/controlRoomApi";
import {
  recoverAndRequeueTask,
  reviewTask
} from "../lib/boardApi";
import { assignNextTask } from "../lib/controlRoomApi";
import { setPendingTaskFocus } from "../lib/taskFocus";
import { useLivePulse } from "../lib/useLivePulse";
import type {
  ActivityItem,
  AgentRosterEntry,
  AgentRosterResponse,
  AlertOperatorAction,
  OverviewResponse,
  PortfolioResponse,
  RecoveryPolicyResponse,
  TimelineResponse
} from "../types";

type HomeViewTarget = "work" | "runs" | "incidents" | "projects";
type CockpitMode = "ops" | "focus" | "review";

interface HomePageProps {
  onNavigate: (view: HomeViewTarget) => void;
  mode: CockpitMode;
}

interface AttentionItem {
  id: string;
  pendingKey?: string;
  tone: "critical" | "warn" | "default";
  label: string;
  summary: string;
  meta?: string;
  actionLabel?: string;
  action?: () => Promise<void>;
}

interface TickerItem {
  id: string;
  title: string;
  summary: string;
  createdAt: string;
  tone: "critical" | "warn" | "default";
  count?: number;
  taskId?: string | null;
  agentId?: string | null;
}

function formatTime(value?: string | null) {
  if (!value) {
    return "Not recorded";
  }
  return new Date(value).toLocaleString();
}

function formatHeartbeat(seconds?: number | null) {
  if (seconds == null) {
    return "No heartbeat";
  }
  if (seconds < 60) {
    return `${seconds}s`;
  }
  return `${Math.round(seconds / 60)}m`;
}

function formatStatusLabel(value?: string | null) {
  if (!value) {
    return "Unknown";
  }
  return value.replaceAll("_", " ");
}

function formatAgentRole(agent: AgentRosterEntry) {
  const display = agent.display_name.trim().toLowerCase();
  const role = agent.role.trim().toLowerCase();
  if (!role || role === display) {
    return null;
  }
  return agent.role;
}

function statusTone(status?: string | null) {
  if (!status) {
    return "default";
  }
  if (["error", "blocked", "critical", "failed"].includes(status)) {
    return "critical";
  }
  if (["review", "paused", "warning", "warn"].includes(status)) {
    return "warn";
  }
  return "default";
}

function buildTickerItems(timeline: TimelineResponse | null, activity: ActivityItem[] | undefined): TickerItem[] {
  const sourceEvents: TickerItem[] = [
    ...(timeline?.events ?? []).map((event) => ({
      id: `${event.source}:${event.event_id}`,
      title: event.title,
      summary: event.description,
      createdAt: event.created_at,
      tone: (
        event.severity === "critical"
          ? "critical"
          : event.severity === "warning"
            ? "warn"
            : "default"
      ) as TickerItem["tone"],
      taskId: event.task_id,
      agentId: event.agent_id
    })),
    ...(activity ?? []).map((item, index) => ({
      id: `activity:${item.activity_id ?? index}:${item.created_at}`,
      title: item.action.replaceAll("_", " "),
      summary: item.description,
      createdAt: item.created_at,
      tone: (
        item.severity === "critical"
          ? "critical"
          : item.severity === "warning"
            ? "warn"
            : "default"
      ) as TickerItem["tone"],
      taskId: item.task_id,
      agentId: item.agent_id
    }))
  ].sort((left, right) => right.createdAt.localeCompare(left.createdAt));

  const grouped: TickerItem[] = [];
  for (const item of sourceEvents) {
    const previous = grouped[grouped.length - 1];
    if (
      previous &&
      previous.title === item.title &&
      previous.taskId === item.taskId &&
      previous.agentId === item.agentId &&
      previous.summary === item.summary
    ) {
      previous.count = (previous.count ?? 1) + 1;
      if (item.createdAt > previous.createdAt) {
        previous.createdAt = item.createdAt;
      }
      continue;
    }
    grouped.push({ ...item, count: 1 });
  }
  return grouped.slice(0, 18);
}

function buildAgentContext(
  agent: AgentRosterEntry,
  tickerItems: TickerItem[]
): { subtitle: string; detail: string; tone: "critical" | "warn" | "default" } {
  const lastEvent = tickerItems.find((item) => item.agentId === agent.agent_id);

  if (agent.status === "error") {
    return {
      subtitle: "Needs recovery",
      detail: lastEvent?.summary ?? "Agent reported an error state.",
      tone: "critical"
    };
  }

  if (agent.status === "idle") {
    return {
      subtitle: "Idle",
      detail: lastEvent?.summary ?? "Waiting for the next assignment.",
      tone: "default"
    };
  }

  return {
    subtitle: agent.current_task_title ?? "Working",
    detail: lastEvent?.summary ?? "No recent activity recorded.",
    tone: statusTone(agent.status)
  };
}

function buildAgentRiskLabel(agent: AgentRosterEntry, tone: "critical" | "warn" | "default") {
  if (agent.status === "error") {
    return "Needs recovery";
  }
  if (tone === "critical") {
    return "Blocked";
  }
  if (agent.status === "idle") {
    return "Idle capacity";
  }
  if (tone === "warn") {
    return "Watch";
  }
  return "Healthy";
}

export function HomePage({ onNavigate, mode }: HomePageProps) {
  const [overview, setOverview] = useState<OverviewResponse | null>(null);
  const [portfolio, setPortfolio] = useState<PortfolioResponse | null>(null);
  const [roster, setRoster] = useState<AgentRosterResponse | null>(null);
  const [recovery, setRecovery] = useState<RecoveryPolicyResponse | null>(null);
  const [timeline, setTimeline] = useState<TimelineResponse | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pendingActionKey, setPendingActionKey] = useState<string | null>(null);
  const livePulse = useLivePulse();

  async function loadControlRoom() {
    const [overviewPayload, portfolioPayload, rosterPayload, recoveryPayload, timelinePayload] =
      await Promise.all([
        fetchOverview(),
        fetchPortfolio(),
        fetchAgentRoster(),
        fetchRecoveryPolicy(),
        fetchIncidentTimeline({ limit: 24 })
      ]);

    setOverview(overviewPayload);
    setPortfolio(portfolioPayload);
    setRoster(rosterPayload);
    setRecovery(recoveryPayload);
    setTimeline(timelinePayload);
  }

  useEffect(() => {
    let mounted = true;
    async function load() {
      try {
        const [overviewPayload, portfolioPayload, rosterPayload, recoveryPayload, timelinePayload] =
          await Promise.all([
            fetchOverview(),
            fetchPortfolio(),
            fetchAgentRoster(),
            fetchRecoveryPolicy(),
            fetchIncidentTimeline({ limit: 24 })
          ]);
        if (!mounted) {
          return;
        }
        setOverview(overviewPayload);
        setPortfolio(portfolioPayload);
        setRoster(rosterPayload);
        setRecovery(recoveryPayload);
        setTimeline(timelinePayload);
      } catch {
        if (mounted) {
          setNotice("Control room refresh failed; showing the latest available operator state.");
        }
      }
    }

    void load();
    return () => {
      mounted = false;
    };
  }, [livePulse]);

  const tickerItems = useMemo(() => buildTickerItems(timeline, overview?.recent_activity), [overview, timeline]);
  const selectedPortfolioProject =
    portfolio?.projects.find((project) => project.project_id === overview?.project?.project_id) ?? null;

  async function runAction(actionKey: string, successMessage: string, action: () => Promise<unknown>, fallback: string) {
    setPendingActionKey(actionKey);
    setNotice(null);
    try {
      await action();
      await loadControlRoom();
      setNotice(successMessage);
    } catch {
      setNotice(fallback);
    } finally {
      setPendingActionKey(null);
    }
  }

  const attentionItems = useMemo<AttentionItem[]>(() => {
    const items: AttentionItem[] = [];

    const projectId = overview?.project?.project_id;
    const onboarding = overview?.onboarding;
    const importReviewPending =
      onboarding?.mode === "brownfield" &&
      !!onboarding.review_status &&
      !["approved", "reviewed", "not_applicable"].includes(onboarding.review_status);

    if (!importReviewPending && onboarding?.mode === "brownfield" && onboarding.review_task_id && onboarding.review_task_status === "planned") {
      items.push({
        id: "brownfield-prepare-review",
        pendingKey: "brownfield-review:prepare",
        tone: "warn",
        label: "Imported repo review is not surfaced yet",
        summary: `${onboarding.pending_gated_tasks} imported tasks are waiting behind onboarding review.`,
        meta: onboarding.last_scanned_at ? formatTime(onboarding.last_scanned_at) : undefined,
        actionLabel: "Prepare review",
        action: () =>
          runAction(
            "brownfield-review:prepare",
            "Supervisor pass completed; the import review task is ready for inspection.",
            () => runSupervisorPass(3),
            "Supervisor pass failed; keep the import under review."
          )
      });
    }

    if (!importReviewPending && onboarding?.mode === "brownfield" && onboarding.review_task_id && onboarding.review_task_status === "review") {
      items.push({
        id: "brownfield-review",
        pendingKey: "brownfield-review:approve",
        tone: "warn",
        label: "Review imported repo before release",
        summary: `${onboarding.pending_gated_tasks} imported tasks are still gated behind onboarding approval.`,
        meta: onboarding.last_scanned_at ? formatTime(onboarding.last_scanned_at) : undefined,
        actionLabel: "Approve import",
        action: () =>
          runAction(
            "brownfield-review:approve",
            "Brownfield onboarding approved; imported work is now eligible for scheduling.",
            () => reviewTask(onboarding.review_task_id!, "approve"),
            "Brownfield onboarding approval failed; keep the import under review."
          )
      });
    }

    if (!importReviewPending && onboarding?.mode === "brownfield" && projectId && onboarding.drift_summary?.detected) {
      items.push({
        id: "brownfield-rescan",
        pendingKey: "brownfield-rescan",
        tone: "warn",
        label: "Imported repo drift was detected",
        summary: onboarding.drift_summary.summary ?? "Files, workflows, or repo areas changed since the last brownfield scan.",
        meta: onboarding.drift_summary.scanned_at ? formatTime(onboarding.drift_summary.scanned_at) : undefined,
        actionLabel: "Rescan import",
        action: () =>
          runAction(
            "brownfield-rescan",
            "Brownfield rescan completed; inspect the updated import state.",
            () => rescanBrownfieldProject(projectId),
            "Brownfield rescan failed; keep the current imported understanding."
          )
      });
    }

    if (!importReviewPending && onboarding?.mode === "brownfield" && projectId && onboarding.repo_plan_state?.stale) {
      items.push({
        id: "repo-plan-refresh",
        pendingKey: "repo-plan-refresh",
        tone: "default",
        label: "Refresh repo-grounded plan",
        summary: "The synthesized brownfield plan is stale relative to the latest imported repository map.",
        meta: onboarding.repo_plan_state.last_refreshed_at
          ? formatTime(onboarding.repo_plan_state.last_refreshed_at)
          : undefined,
        actionLabel: "Refresh plan",
        action: () =>
          runAction(
            "repo-plan-refresh",
            "Repo-grounded plan refreshed.",
            () => refreshRepoPlan(projectId),
            "Refreshing the repo-grounded plan failed; keeping the current brownfield plan state."
          )
      });
    }

    for (const alert of recovery?.open_failure_alerts ?? []) {
      items.push({
        id: `failure-alert:${alert.alert_id}`,
        pendingKey: `alert:${alert.alert_id}`,
        tone: "critical",
        label: alert.title,
        summary: alert.description,
        meta: formatTime(alert.created_at),
        actionLabel: alert.operator_action?.label,
        action: alert.operator_action
          ? () =>
              runAction(
                `alert:${alert.alert_id}`,
                `Resolved ${alert.title}.`,
                () => runAlertOperatorAction(alert.operator_action as AlertOperatorAction),
                `Alert action failed for ${alert.title}.`
              )
          : undefined
      });
    }

    for (const task of recovery?.recoverable_blocked_tasks ?? []) {
      items.push({
        id: `blocked:${task.task_id}`,
        pendingKey: `recover-and-requeue:${task.task_id}`,
        tone: "warn",
        label: task.title,
        summary: task.review_state ? `Blocked · ${task.review_state}` : "Recoverable blocked task",
        meta: task.agent_name ?? task.goal_title ?? undefined,
        actionLabel: "Recover + requeue",
        action: () =>
          runAction(
            `recover-and-requeue:${task.task_id}`,
            `Recovered and requeued ${task.title}.`,
            () => recoverAndRequeueTask(task.task_id),
            `Recover-and-requeue failed for ${task.title}.`
          )
      });
    }

    for (const deadLetter of recovery?.dead_letter_entries ?? []) {
      items.push({
        id: `dlq:${deadLetter.dlq_id}`,
        pendingKey: `reset-retry:${deadLetter.task_id}`,
        tone: "critical",
        label: deadLetter.title,
        summary: `Dead letter · ${deadLetter.reason}`,
        meta: deadLetter.detail?.failure_type ?? undefined,
        actionLabel: "Reset retry",
        action: () =>
          runAction(
            `reset-retry:${deadLetter.task_id}`,
            `Reset retry state for ${deadLetter.title}.`,
            () => resetTaskRetryState(deadLetter.task_id),
            `Retry reset failed for ${deadLetter.title}.`
          )
      });
    }

    for (const task of recovery?.circuit_breaker_tasks ?? []) {
      items.push({
        id: `circuit:${task.task_id}`,
        pendingKey: `reset-breaker:${task.task_id}`,
        tone: "critical",
        label: task.title,
        summary: task.circuit_breaker_detail?.trigger?.replaceAll("_", " ") ?? "Circuit breaker opened",
        meta: task.goal_title ?? undefined,
        actionLabel: "Reset breaker",
        action: () =>
          runAction(
            `reset-breaker:${task.task_id}`,
            `Reset circuit breaker for ${task.title}.`,
            () => resetTaskCircuitBreaker(task.task_id),
            `Circuit-breaker reset failed for ${task.title}.`
          )
      });
    }

    for (const quarantine of recovery?.open_quarantine_entries ?? []) {
      const recoverable =
        quarantine.task_status === "blocked" &&
        ["session_failed", "stale_session"].includes(quarantine.task_review_state ?? "");
      items.push({
        id: `quarantine:${quarantine.queue_id}`,
        pendingKey: `${recoverable ? "restore-requeue" : "restore"}:${quarantine.queue_id}`,
        tone: "warn",
        label: quarantine.task_title ?? quarantine.queue_id,
        summary: quarantine.summary ?? quarantine.reason ?? "Quarantined artifacts need review.",
        meta: `${quarantine.artifact_count} artifacts`,
        actionLabel: recoverable ? "Restore + requeue" : "Restore artifacts",
        action: () =>
          runAction(
            `${recoverable ? "restore-requeue" : "restore"}:${quarantine.queue_id}`,
            recoverable
              ? `Restored artifacts and requeued ${quarantine.task_title ?? quarantine.queue_id}.`
              : `Restored artifacts for ${quarantine.task_title ?? quarantine.queue_id}.`,
            () =>
              recoverable
                ? restoreAndRequeueQuarantineEntry(quarantine.queue_id)
                : restoreQuarantineEntry(quarantine.queue_id),
            `Quarantine action failed for ${quarantine.task_title ?? quarantine.queue_id}.`
          )
      });
    }

    for (const staleAgent of recovery?.open_stale_agent_alerts ?? []) {
      items.push({
        id: `stale-agent:${staleAgent.alert_id}`,
        pendingKey: `stale-agent:${staleAgent.alert_id}`,
        tone: "warn",
        label: staleAgent.title,
        summary: staleAgent.description,
        meta: staleAgent.project_name ?? undefined,
        actionLabel: staleAgent.operator_action?.label,
        action: staleAgent.operator_action
          ? () =>
              runAction(
                `stale-agent:${staleAgent.alert_id}`,
                `Ran ${staleAgent.operator_action?.label?.toLowerCase() ?? "recovery"} for ${staleAgent.title}.`,
                () => runAlertOperatorAction(staleAgent.operator_action as AlertOperatorAction),
                `Stale-agent action failed for ${staleAgent.title}.`
              )
          : undefined
      });
    }

    for (const repeated of recovery?.repeated_failure_incidents ?? []) {
      if (!repeated.operator_action) {
        continue;
      }
      items.push({
        id: `repeated:${repeated.task_id}`,
        pendingKey: `repeated:${repeated.task_id}`,
        tone: "warn",
        label: repeated.task_title ?? repeated.task_id,
        summary: `${repeated.failure_count} repeated failures`,
        meta: repeated.latest_failure_at ? formatTime(repeated.latest_failure_at) : undefined,
        actionLabel: repeated.operator_action.label,
        action: () =>
          runAction(
            `repeated:${repeated.task_id}`,
            `Resolved repeated-failure incident for ${repeated.task_title ?? repeated.task_id}.`,
            () => runAlertOperatorAction(repeated.operator_action!),
            `Repeated-failure resolution failed for ${repeated.task_title ?? repeated.task_id}.`
          )
      });
    }

    return items.slice(0, 10);
  }, [overview, recovery]);

  const pendingImportReview =
    overview?.onboarding?.mode === "brownfield" &&
    !!overview?.onboarding?.review_status &&
    !["approved", "reviewed", "not_applicable"].includes(overview.onboarding.review_status);
  const reviewTaskId = overview?.onboarding?.review_task_id ?? null;
  const onboardingWorkflowLabels =
    overview?.onboarding?.discovery_summary.workflow_details?.map((detail) => detail.label).filter(Boolean) ??
    overview?.onboarding?.discovery_summary.workflow_labels ??
    [];
  const onboardingCodeAreas =
    overview?.onboarding?.discovery_summary.codebase_map?.map((area) => area.name).filter(Boolean) ??
    overview?.onboarding?.discovery_summary.repo_areas ??
    [];
  const blockedTaskCount = overview?.summary.tasks_blocked ?? 0;
  const pendingGatedTasks = overview?.onboarding?.pending_gated_tasks ?? 0;
  const hasRuntimeRisk =
    (recovery?.summary.open_failure_alerts ?? 0) > 0 || (recovery?.summary.open_dead_letter_entries ?? 0) > 0;
  const queuedProviderJobs = portfolio?.summary.queued_provider_jobs ?? 0;
  const currentProjectId = overview?.project?.project_id ?? null;
  const criticalAttentionCount = attentionItems.filter((item) => item.tone === "critical").length;
  const queueMode = selectedPortfolioProject?.provider_capacity.queue_mode ?? "running";

  function openTaskInBoard(taskId: string | null) {
    if (taskId) {
      setPendingTaskFocus(taskId);
    }
    onNavigate("work");
  }

  const projectHealth = pendingImportReview
    ? "Needs import review"
    : blockedTaskCount > 0
      ? "Blocked"
      : hasRuntimeRisk
        ? "At risk"
        : "Stable";

  const projectHealthDetail = pendingImportReview
    ? `${pendingGatedTasks} imported tasks gated`
    : blockedTaskCount > 0
      ? `${blockedTaskCount} blocked tasks`
      : hasRuntimeRisk
        ? "Failures or dead-letter work need attention"
        : "No active blockers";

  const runPrimaryLoop = () =>
    runAction(
      "run",
      queuedProviderJobs > 0 ? "Run completed; queue and board refreshed." : "Run completed; board refreshed.",
      () => (queuedProviderJobs > 0 ? runOrchestratorPass(4, 2) : runSupervisorPass(3)),
      queuedProviderJobs > 0 ? "Run failed while processing queued work." : "Run failed while refreshing the board."
    );

  const recommendation = pendingImportReview
    ? {
        title: "Review imported repo before releasing work",
        detail:
          reviewTaskId && overview?.onboarding?.review_task_status === "review"
            ? "Open the review task on Board, inspect MAAS's imported understanding, then approve it."
            : "Prepare the import review first so the gated brownfield tasks have one clear decision path.",
        primaryLabel:
          reviewTaskId && overview?.onboarding?.review_task_status === "review" ? "Open review on Board" : "Prepare review",
        primaryAction:
          reviewTaskId && overview?.onboarding?.review_task_status === "review"
            ? () => openTaskInBoard(reviewTaskId)
            : () =>
                runAction(
                  "brownfield-review:prepare",
                  "Import review is ready on the board.",
                  () => runSupervisorPass(3),
                  "Supervisor pass failed; the import review is still pending."
                ),
        secondaryLabel: "Open Projects",
        secondaryAction: () => onNavigate("projects")
      }
    : attentionItems.length > 0
      ? {
          title: "Triage the incident queue",
          detail: `${attentionItems.length} operator item${attentionItems.length === 1 ? "" : "s"} are waiting, including ${criticalAttentionCount} critical.`,
          primaryLabel: "Open incidents",
          primaryAction: () => onNavigate("incidents"),
          secondaryLabel: "Open Board",
          secondaryAction: () => onNavigate("work")
        }
      : {
          title: queuedProviderJobs > 0 ? "Drain queued work" : "Continue supervised execution",
          detail:
            queuedProviderJobs > 0
              ? `${queuedProviderJobs} queued provider job${queuedProviderJobs === 1 ? "" : "s"} are ready to process in ${queueMode} mode.`
              : `${overview?.summary.tasks_in_progress ?? 0} run${overview?.summary.tasks_in_progress === 1 ? "" : "s"} active and no urgent incident requires you.`,
          primaryLabel: queuedProviderJobs > 0 ? "Run work loop" : "Open Board",
          primaryAction: queuedProviderJobs > 0 ? runPrimaryLoop : () => onNavigate("work"),
          secondaryLabel: "Open Execution",
          secondaryAction: () => onNavigate("runs")
        };

  const systemSignals = [
    {
      label: "Recoverable now",
      value: recovery?.summary.recoverable_blocked_tasks ?? 0,
      detail: "tasks ready for recover or requeue",
      tone: "warn" as const
    },
    {
      label: "Dead letters",
      value: recovery?.summary.open_dead_letter_entries ?? 0,
      detail: "contained failures still unresolved",
      tone: "critical" as const
    },
    {
      label: "Circuit breakers",
      value: recovery?.summary.open_circuit_breakers ?? 0,
      detail: "tasks frozen by repeat failure pressure",
      tone: "critical" as const
    },
    {
      label: "Queued jobs",
      value: queuedProviderJobs,
      detail: `${queueMode} mode`,
      tone: "default" as const
    }
  ];

  const cockpitActions = [
    { id: "board", label: "Open Board", run: () => onNavigate("work") },
    { id: "runs", label: "Open Execution", run: () => onNavigate("runs") },
    { id: "incidents", label: "Open Incidents", run: () => onNavigate("incidents") },
    { id: "projects", label: "Open Projects", run: () => onNavigate("projects") }
  ];

  return (
    <section className={`control-room control-room--${mode}`}>
      <header className="control-room__masthead surface-card surface-card--dense">
        <div className="control-room__masthead-row">
          <div className="control-room__masthead-copy">
            <div className="control-room__eyebrow">Board</div>
            <h1>{overview?.project?.name ?? "No active project"}</h1>
            <p>{overview?.project?.description ?? "Create or restore a project to start supervising agents."}</p>
          </div>
          <div className="control-room__header-actions">
            {!pendingImportReview ? (
              <button
                type="button"
                className="hero-button hero-button--primary hero-button--compact"
                disabled={pendingActionKey === "run"}
                onClick={() => void runPrimaryLoop()}
              >
                {pendingActionKey === "run" ? "Running..." : "Run"}
              </button>
            ) : null}
          </div>
        </div>
        <div className="control-room__status-strip">
          <div className="status-panel status-panel--health">
            <span
              className={`status-dot status-dot--${
                projectHealth === "Stable" ? "good" : projectHealth === "At risk" ? "critical" : "warn"
              }`}
            />
            <div className="status-panel__copy">
              <strong>{projectHealth}</strong>
              <span>{projectHealthDetail}</span>
            </div>
          </div>
          <div className="status-panel">
            <strong>{overview?.summary.tasks_in_progress ?? 0}</strong>
            <span>active runs</span>
          </div>
          <div className="status-panel">
            <strong>{overview?.summary.tasks_review ?? 0}</strong>
            <span>waiting review</span>
          </div>
          <div className="status-panel">
            <strong>{recovery?.summary.open_failure_alerts ?? 0}</strong>
            <span>failure alerts</span>
          </div>
          <div className="status-panel">
            <strong>{queuedProviderJobs}</strong>
            <span>queued jobs</span>
          </div>
          <div className="status-panel">
            <strong>{blockedTaskCount}</strong>
            <span>blocked tasks</span>
          </div>
        </div>
      </header>

      {notice ? <div className="banner banner--info">{notice}</div> : null}

      {pendingImportReview ? (
        <article className="surface-card surface-card--dense onboarding-takeover">
          <div className="surface-card__header surface-card__header--tight">
            <div>
              <span className="eyebrow">Import review</span>
              <h2>Imported repo needs review before automation continues</h2>
              <p>
                MAAS found {onboardingWorkflowLabels.length || 0} workflow
                {onboardingWorkflowLabels.length === 1 ? "" : "s"}, {onboardingCodeAreas.length || 0} repo area
                {onboardingCodeAreas.length === 1 ? "" : "s"}, and {pendingGatedTasks} gated task
                {pendingGatedTasks === 1 ? "" : "s"}.
              </p>
            </div>
            <span className="status-pill status-pill--warn">
              {formatStatusLabel(overview?.onboarding?.review_task_status ?? overview?.onboarding?.review_status ?? "review_pending")}
            </span>
          </div>
          <div className="onboarding-takeover__grid">
            <div className="onboarding-takeover__summary">
              <div className="onboarding-takeover__chips">
                {onboardingWorkflowLabels.slice(0, 4).map((label) => (
                  <span key={label} className="status-chip">
                    {label}
                  </span>
                ))}
                {onboardingCodeAreas.slice(0, 4).map((area) => (
                  <span key={area} className="status-chip status-chip--muted">
                    {area}
                  </span>
                ))}
              </div>
              <p className="muted-copy">
                {overview?.onboarding?.review_task_status === "planned"
                  ? "First surface the review task, then inspect MAAS's imported understanding and approve it if it looks right."
                  : "Focus the review task, confirm the imported understanding, then approve the import to release the gated tasks."}
              </p>
            </div>
            <div className="onboarding-takeover__actions">
              {overview?.onboarding?.review_task_status === "planned" ? (
                <button
                  type="button"
                  className="hero-button hero-button--primary hero-button--compact"
                  disabled={pendingActionKey === "brownfield-review:prepare"}
                  onClick={() =>
                    void runAction(
                      "brownfield-review:prepare",
                      "Import review is ready on the board.",
                      () => runSupervisorPass(3),
                      "Supervisor pass failed; the import review is still pending."
                    )
                  }
                >
                  {pendingActionKey === "brownfield-review:prepare" ? "Preparing..." : "Prepare review"}
                </button>
              ) : null}
              {reviewTaskId ? (
                <button
                  type="button"
                  className="hero-button hero-button--ghost hero-button--compact"
                  onClick={() => openTaskInBoard(reviewTaskId)}
                >
                  Open review on Board
                </button>
              ) : null}
              {overview?.onboarding?.review_task_status === "review" && reviewTaskId ? (
                <button
                  type="button"
                  className="hero-button hero-button--primary hero-button--compact"
                  disabled={pendingActionKey === "brownfield-review:approve"}
                  onClick={() =>
                    void runAction(
                      "brownfield-review:approve",
                      "Imported repo approved; gated work can now be scheduled.",
                      () => reviewTask(reviewTaskId, "approve"),
                      "Import approval failed; keep the review under operator control."
                    )
                  }
                >
                  {pendingActionKey === "brownfield-review:approve" ? "Approving..." : "Approve import"}
                </button>
              ) : null}
              {currentProjectId ? (
                <button
                  type="button"
                  className="hero-button hero-button--ghost hero-button--compact"
                  disabled={pendingActionKey === "brownfield-rescan"}
                  onClick={() =>
                    void runAction(
                      "brownfield-rescan",
                      "Brownfield rescan completed.",
                      () => rescanBrownfieldProject(currentProjectId),
                      "Brownfield rescan failed."
                    )
                  }
                >
                  {pendingActionKey === "brownfield-rescan" ? "Rescanning..." : "Rescan import"}
                </button>
              ) : null}
              {currentProjectId && overview?.onboarding?.repo_plan_state?.stale ? (
                <button
                  type="button"
                  className="hero-button hero-button--ghost hero-button--compact"
                  disabled={pendingActionKey === "repo-plan-refresh"}
                  onClick={() =>
                    void runAction(
                      "repo-plan-refresh",
                      "Repo-grounded plan refreshed.",
                      () => refreshRepoPlan(currentProjectId),
                      "Refreshing the repo-grounded plan failed."
                    )
                  }
                >
                  {pendingActionKey === "repo-plan-refresh" ? "Refreshing..." : "Refresh plan"}
                </button>
              ) : null}
            </div>
          </div>
        </article>
      ) : null}

      <article className="surface-card surface-card--dense agent-roster-card">
        <div className="surface-card__header surface-card__header--tight">
          <div>
            <span className="eyebrow">Agents</span>
            <h2>Live agent roster</h2>
            <p className="surface-card__copy">See who is idle, stalled, or already progressing without opening the Board.</p>
          </div>
          <button type="button" className="text-link" onClick={() => onNavigate("runs")}>
            Execution
          </button>
        </div>
        <div className="agent-roster">
          {(roster?.agents ?? []).map((agent) => {
            const context = buildAgentContext(agent, tickerItems);
            const actionKey = `agent:${agent.agent_id}`;
            const riskLabel = buildAgentRiskLabel(agent, context.tone);
            return (
              <div key={agent.agent_id} className={`agent-roster__row agent-roster__row--${context.tone}`}>
                <div className="agent-roster__identity">
                  <strong>{agent.display_name}</strong>
                  <span>{formatAgentRole(agent) ?? "Agent"}</span>
                </div>
                <div className="agent-roster__context">
                  <strong>{context.subtitle}</strong>
                  <span>{context.detail}</span>
                </div>
                <div className="agent-roster__signals">
                  <span className={`status-pill status-pill--${statusTone(agent.status)}`}>{formatStatusLabel(agent.status)}</span>
                  <span className="agent-roster__heartbeat">heartbeat {formatHeartbeat(agent.heartbeat_age_seconds)}</span>
                </div>
                <div className="agent-roster__risk">
                  <strong>{riskLabel}</strong>
                </div>
                <div className="agent-roster__actions">
                  {agent.status === "idle" ? (
                    <button
                      type="button"
                      className="task-action task-action--secondary"
                      disabled={pendingActionKey === actionKey}
                      onClick={() =>
                        void runAction(
                          actionKey,
                          `Requested next task for ${agent.display_name}.`,
                          () => assignNextTask(agent.agent_id),
                          `Could not assign the next task to ${agent.display_name}.`
                        )
                      }
                    >
                      {pendingActionKey === actionKey ? "Working..." : "Assign next"}
                    </button>
                  ) : agent.status === "error" ? (
                    <button
                      type="button"
                      className="task-action task-action--approve"
                      disabled={pendingActionKey === actionKey}
                      onClick={() =>
                        void runAction(
                          actionKey,
                          `Recovered ${agent.display_name}.`,
                          () => recoverAgent(agent.agent_id),
                          `Recovery failed for ${agent.display_name}.`
                        )
                      }
                    >
                      {pendingActionKey === actionKey ? "Working..." : "Recover"}
                    </button>
                  ) : agent.current_task_id ? (
                    <button
                      type="button"
                      className="task-action task-action--ghost"
                      onClick={() => openTaskInBoard(agent.current_task_id ?? null)}
                    >
                      Open board
                    </button>
                  ) : (
                    <span className="muted-copy">No action</span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </article>

      <section className="control-room__grid control-room__grid--supervision">

        <div className="control-room__center">
          <article className="surface-card surface-card--dense">
            <div className="surface-card__header surface-card__header--tight">
              <div>
                <span className="eyebrow">Next move</span>
                <h2>{recommendation.title}</h2>
                <p className="surface-card__copy">{recommendation.detail}</p>
              </div>
              <span className="status-chip">{attentionItems.length} queued decisions</span>
            </div>
            <div className="surface-card__actions">
              <button
                type="button"
                className="hero-button hero-button--primary hero-button--compact"
                disabled={pendingActionKey === "run" || pendingActionKey === "brownfield-review:prepare"}
                onClick={() => void recommendation.primaryAction()}
              >
                {pendingActionKey === "run" || pendingActionKey === "brownfield-review:prepare"
                  ? "Working..."
                  : recommendation.primaryLabel}
              </button>
              <button
                type="button"
                className="hero-button hero-button--ghost hero-button--compact"
                onClick={recommendation.secondaryAction}
              >
                {recommendation.secondaryLabel}
              </button>
              {cockpitActions.slice(0, 2).map((action) => (
                <button
                  key={action.id}
                  type="button"
                  className="hero-button hero-button--ghost hero-button--compact"
                  onClick={action.run}
                >
                  {action.label}
                </button>
              ))}
            </div>
          </article>

          <article className="surface-card surface-card--dense">
            <div className="surface-card__header surface-card__header--tight">
              <div>
                <span className="eyebrow">Attention</span>
                <h2>What needs you now</h2>
              </div>
              <button type="button" className="text-link" onClick={() => onNavigate("incidents")}>
                Incidents
              </button>
            </div>
            <div className="attention-list">
              {attentionItems.length ? (
                attentionItems.map((item) => (
                  <div key={item.id} className={`attention-item attention-item--${item.tone}`}>
                    <div>
                      <strong>{item.label}</strong>
                      <p>{item.summary}</p>
                      {item.meta ? <span>{item.meta}</span> : null}
                    </div>
                    {item.action && item.actionLabel ? (
                      <button
                        type="button"
                        className="task-action task-action--approve"
                        disabled={pendingActionKey === (item.pendingKey ?? item.id)}
                        onClick={() => void item.action?.()}
                      >
                        {pendingActionKey === (item.pendingKey ?? item.id) ? "Working..." : item.actionLabel}
                      </button>
                    ) : (
                      <button type="button" className="task-action task-action--ghost" onClick={() => onNavigate("incidents")}>
                        Inspect
                      </button>
                    )}
                  </div>
                ))
              ) : (
                <div className="empty-state empty-state--compact">
                  <strong>No urgent operator actions.</strong>
                  <p>Keep an eye on the live feed and system pressure; nothing is escalated right now.</p>
                </div>
              )}
            </div>
          </article>

          <article className="surface-card surface-card--dense">
            <div className="surface-card__header surface-card__header--tight">
              <div>
                <span className="eyebrow">Live feed</span>
                <h2>Meaningful system events</h2>
              </div>
              <button type="button" className="text-link" onClick={() => onNavigate("runs")}>
                Runs
              </button>
            </div>
            <div className="ticker-list">
              {tickerItems.length ? (
                tickerItems.map((item) => (
                  <div key={item.id} className={`ticker-item ticker-item--${item.tone}`}>
                    <div>
                      <strong>{item.title}</strong>
                      <p>{item.summary}</p>
                    </div>
                    <div className="ticker-item__meta">
                      {item.count && item.count > 1 ? <span>×{item.count}</span> : null}
                      <span>{formatTime(item.createdAt)}</span>
                    </div>
                  </div>
                ))
              ) : (
                <div className="empty-state empty-state--compact">
                  <strong>No recent events.</strong>
                  <p>The feed will populate as agents, providers, and recovery actions change system state.</p>
                </div>
              )}
            </div>
          </article>
        </div>

        <aside className="control-room__ops">
          <article className="surface-card surface-card--dense">
            <div className="surface-card__header surface-card__header--tight">
              <div>
                <span className="eyebrow">System pressure</span>
                <h2>What is building up</h2>
              </div>
            </div>
            <div className="signal-stack">
              {systemSignals.map((signal) => (
                <div key={signal.label} className={`signal-row signal-row--${signal.tone}`}>
                  <div>
                    <strong>{signal.label}</strong>
                    <p>{signal.detail}</p>
                  </div>
                  <span className="status-chip">{signal.value}</span>
                </div>
              ))}
            </div>
          </article>

          <article className="surface-card surface-card--dense">
            <div className="surface-card__header surface-card__header--tight">
              <div>
                <span className="eyebrow">Quick routes</span>
                <h2>Open the right surface</h2>
              </div>
            </div>
            <div className="control-room__action-grid">
              {cockpitActions.map((action) => (
                <button
                  key={action.id}
                  type="button"
                  className="hero-button hero-button--ghost hero-button--compact"
                  onClick={action.run}
                >
                  {action.label}
                </button>
              ))}
            </div>
          </article>

          <article className="surface-card surface-card--dense">
            <div className="surface-card__header surface-card__header--tight">
              <div>
                <span className="eyebrow">Import state</span>
                <h2>{pendingImportReview ? "Brownfield review is active" : "Project is clear to run"}</h2>
              </div>
            </div>
            <div className="signal-stack">
              <div className="signal-row">
                <div>
                  <strong>Workflows</strong>
                  <p>{onboardingWorkflowLabels.length ? onboardingWorkflowLabels.join(", ") : "No imported workflows detected"}</p>
                </div>
              </div>
              <div className="signal-row">
                <div>
                  <strong>Repo areas</strong>
                  <p>{onboardingCodeAreas.length ? onboardingCodeAreas.join(", ") : "No imported repo areas recorded"}</p>
                </div>
              </div>
            </div>
          </article>
        </aside>
      </section>
    </section>
  );
}
