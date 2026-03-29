import { useEffect, useMemo, useState, type FormEvent } from "react";
import { OperatorLoopPanel } from "../components/OperatorLoopPanel";
import {
  fetchAlerts,
  fetchAgentRoster,
  fetchAutopilotStatus,
  fetchDeliveryOverview,
  fetchCodexIssueIndex,
  fetchCodexRetrievalSearch,
  fetchEnvironmentDoctor,
  fetchGoalPlanning,
  fetchIncidentTimeline,
  fetchOverview,
  fetchPortfolio,
  prepareTaskPrDraft,
  runOrchestratorPass,
  createGoal,
  synthesizeGoal,
  runControlOperatorAction,
  syncTaskGithubPr,
  updateProjectAutopilot,
  updateProjectProviderCapacity,
} from "../lib/controlRoomApi";
import { boardCounts, describeLaunchPosture, formatTimestamp, issueKeyMap } from "../lib/codexMvp";
import { consumePendingNotificationFocus } from "../lib/notificationFocus";
import { getSelectedProjectId, subscribeProjectScope } from "../lib/projectScope";
import { setPendingRunFocus } from "../lib/runFocus";
import { setPendingTaskFocus } from "../lib/taskFocus";
import { useLivePulse } from "../lib/useLivePulse";
import type {
  AlertItem,
  AutopilotStatusResponse,
  BoardTask,
  CodexRetrievalSearchResponse,
  ControlOperatorAction,
  DeliveryOverviewResponse,
  EnvironmentDoctorResponse,
  GoalPlanningResponse,
  OperatorInboxResponse,
  OverviewResponse,
  PortfolioProject,
  TimelineEvent,
} from "../types";
import type { OperatorLoopItem, OperatorWorkflowState } from "../lib/operatorLoop";

type ViewTarget = "work" | "issues" | "agents" | "runs" | "system" | "projects";

const RUN_CONTROL_MIN_PENDING_MS = 900;

function issueLabel(task: BoardTask, fallbackKeys: Map<string, string>) {
  return task.issue_key ?? fallbackKeys.get(task.task_id) ?? task.task_id;
}

export function CommandPage({
  onNavigate,
  operatorInbox,
  operatorWorkflow,
  onOpenOperatorItem,
  operatorWorkflowWarning,
}: {
  onNavigate: (view: ViewTarget) => void;
  operatorInbox: OperatorInboxResponse | null;
  operatorWorkflow: OperatorWorkflowState | null;
  onOpenOperatorItem: (item: OperatorLoopItem) => void;
  operatorWorkflowWarning?: string | null;
}) {
  const [overview, setOverview] = useState<OverviewResponse | null>(null);
  const [tasks, setTasks] = useState<BoardTask[]>([]);
  const [resolved, setResolved] = useState<BoardTask[]>([]);
  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [project, setProject] = useState<PortfolioProject | null>(null);
  const [autopilot, setAutopilot] = useState<AutopilotStatusResponse | null>(null);
  const [doctor, setDoctor] = useState<EnvironmentDoctorResponse | null>(null);
  const [goalPlanning, setGoalPlanning] = useState<GoalPlanningResponse | null>(null);
  const [delivery, setDelivery] = useState<DeliveryOverviewResponse | null>(null);
  const [runningAgents, setRunningAgents] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);
  const [pendingKey, setPendingKey] = useState<string | null>(null);
  const [recentFailureCount, setRecentFailureCount] = useState(0);
  const [searchQuery, setSearchQuery] = useState("");
  const [retrieval, setRetrieval] = useState<CodexRetrievalSearchResponse | null>(null);
  const [retrievalNotice, setRetrievalNotice] = useState<string | null>(null);
  const [goalTitle, setGoalTitle] = useState("");
  const [goalDescription, setGoalDescription] = useState("");
  const [goalNotice, setGoalNotice] = useState<string | null>(null);
  const [deliveryNotice, setDeliveryNotice] = useState<string | null>(null);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(() => getSelectedProjectId());
  const [focusedNotificationId, setFocusedNotificationId] = useState<string | null>(null);
  const livePulse = useLivePulse();

  useEffect(() => subscribeProjectScope(setSelectedProjectId), []);

  async function loadCommand(signal?: AbortSignal) {
    let usedFallback = false;
    const markFallback = () => {
      usedFallback = true;
    };
    const [
      issueIndexPayload,
      overviewPayload,
      alertsPayload,
      timelinePayload,
      rosterPayload,
      portfolioPayload,
      autopilotPayload,
      doctorPayload,
      goalPlanningPayload,
      deliveryPayload,
    ] = await Promise.all([
      fetchCodexIssueIndex(signal, markFallback),
      fetchOverview(selectedProjectId, signal, markFallback),
      fetchAlerts(signal, markFallback, selectedProjectId),
      fetchIncidentTimeline({ limit: 18 }, signal, markFallback, selectedProjectId),
      fetchAgentRoster(signal, markFallback, selectedProjectId),
      fetchPortfolio(signal, markFallback),
      fetchAutopilotStatus(signal, markFallback, selectedProjectId),
      fetchEnvironmentDoctor(signal, markFallback, selectedProjectId),
      fetchGoalPlanning(signal, markFallback, selectedProjectId),
      fetchDeliveryOverview(signal, markFallback, selectedProjectId),
    ]);
    setOverview(overviewPayload);
    setTasks([
      ...issueIndexPayload.queue.review.items,
      ...issueIndexPayload.queue.blocked_failures.items,
      ...issueIndexPayload.queue.blocked_dependencies.items,
    ]);
    setResolved(issueIndexPayload.resolved);
    setAlerts(alertsPayload.alerts);
    setRecentFailureCount(issueIndexPayload.summary.recent_failures);
    setTimeline(timelinePayload.events);
    setRunningAgents(rosterPayload.agents.filter((agent) => agent.status === "running").length);
    setAutopilot(autopilotPayload);
    setDoctor(doctorPayload);
    setGoalPlanning(goalPlanningPayload);
    setDelivery(deliveryPayload);
    setProject(
      portfolioPayload.projects.find((item) => item.project_id === selectedProjectId) ??
        portfolioPayload.projects[0] ??
        null
    );
    setNotice(usedFallback ? "Command refresh fell back to cached data for one or more panels." : null);
  }

  useEffect(() => {
    const controller = new AbortController();
    void loadCommand(controller.signal).catch(() => setNotice("Command refresh failed; showing the latest available state."));
    return () => controller.abort();
  }, [livePulse, selectedProjectId]);

  useEffect(() => {
    const trimmed = searchQuery.trim();
    if (trimmed.length < 2) {
      setRetrieval(null);
      setRetrievalNotice(null);
      return;
    }
    setRetrieval(null);
    setRetrievalNotice(null);
    const controller = new AbortController();
    const timeout = window.setTimeout(() => {
      void fetchCodexRetrievalSearch({ search: trimmed }, controller.signal, undefined, selectedProjectId)
        .then((payload) => {
          setRetrieval(payload);
          setRetrievalNotice(null);
        })
        .catch((error) => {
          if (!(error instanceof Error && error.name === "AbortError")) {
            setRetrieval(null);
            setRetrievalNotice("Search refresh failed. Retrieval results could not be loaded for this query.");
          }
        });
    }, 180);
    return () => {
      controller.abort();
      window.clearTimeout(timeout);
    };
  }, [searchQuery, selectedProjectId]);

  const keyMap = useMemo(() => issueKeyMap([{ key: "ready", title: "Ready", tasks }, { key: "done", title: "Done", tasks: resolved }]), [tasks, resolved]);
  const counts = useMemo(() => boardCounts([{ key: "ready", title: "Ready", tasks }, { key: "done", title: "Done", tasks: resolved }]), [tasks, resolved]);

  const queue = useMemo(() => [...tasks].sort((left, right) => right.priority - left.priority).slice(0, 6), [tasks]);
  const launchPosture = useMemo(() => describeLaunchPosture(project), [project]);
  const brownfieldTrust = overview?.onboarding?.repo_plan_state?.trust ?? overview?.onboarding?.repo_plan_trust ?? null;
  const workflowActions = useMemo(() => {
    const seen = new Set<string>();
    const actions = [...(operatorWorkflow?.autopilot.operatorActions ?? []), ...(operatorWorkflow?.inbox.operatorActions ?? [])];
    return actions.filter((action) => {
      const key = `${action.action}:${action.resource_type}:${action.resource_id}:${JSON.stringify(action.payload ?? {})}`;
      if (seen.has(key)) {
        return false;
      }
      seen.add(key);
      return true;
    });
  }, [operatorWorkflow]);
  const notificationAttention = useMemo(
    () => {
      const items = ((operatorInbox?.buckets.notification_failures ?? []) as Array<{
        resource_id?: string;
        title?: string;
        subtype?: string;
        summary?: string;
        recommended_action?: string;
        operator_actions?: ControlOperatorAction[];
        metadata?: Record<string, unknown>;
      }>).slice();
      items.sort((left, right) => {
        const leftFocused = left.resource_id === focusedNotificationId ? 1 : 0;
        const rightFocused = right.resource_id === focusedNotificationId ? 1 : 0;
        return rightFocused - leftFocused;
      });
      return items.slice(0, focusedNotificationId ? 4 : 3);
    },
    [focusedNotificationId, operatorInbox]
  );

  useEffect(() => {
    const nextFocusId = consumePendingNotificationFocus();
    if (nextFocusId) {
      setFocusedNotificationId(nextFocusId);
    }
  }, [operatorInbox?.generated_at, selectedProjectId]);

  async function holdPendingState(startedAt: number) {
    const remaining = RUN_CONTROL_MIN_PENDING_MS - (Date.now() - startedAt);
    if (remaining > 0) {
      await new Promise((resolve) => window.setTimeout(resolve, remaining));
    }
  }

  async function handleRun() {
    const startedAt = Date.now();
    setPendingKey("run");
    setNotice(null);
    try {
      const result = await runOrchestratorPass(6, 4, true);
      await loadCommand();
      await holdPendingState(startedAt);
      await loadCommand();
      const queued = result.provider_jobs_queued ?? 0;
      const started = (result.provider_jobs_processed ?? 0) + (result.provider_jobs_dispatched ?? 0);
      const launchProvider = result.project_runs.find((item) => item.launch_provider_id)?.launch_provider_id ?? null;
      if (started === 0 && queued === 0 && launchPosture.mode === "running" && tasks.some((task) => task.status === "assigned")) {
        setNotice(
          launchProvider
            ? `Cycle complete: assigned work is waiting on ${launchProvider.replaceAll("_", " ")} capacity or readiness, so no new run started yet.`
            : "Cycle complete: no launch-ready provider is available for the assigned work."
        );
      } else {
        setNotice(
          `Cycle complete: ${result.assigned_count} assignments, ${started} run${started === 1 ? "" : "s"} started, ${queued} queued${launchPosture.mode !== "running" ? " while launches were not fully open" : ""}.`
        );
      }
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Run failed.");
    } finally {
      setPendingKey(null);
    }
  }

  async function handlePause() {
    if (!project) {
      return;
    }
    const startedAt = Date.now();
    setPendingKey("pause");
    setNotice(null);
    try {
      await updateProjectProviderCapacity(project.project_id, {
        queue_mode: "paused",
        max_running_jobs: project.provider_capacity.max_running_jobs,
        preferred_provider_id: project.provider_capacity.preferred_provider_id ?? null,
      });
      await loadCommand();
      await holdPendingState(startedAt);
      await loadCommand();
      setNotice("Paused new Codex launches. Active runs will continue until they finish.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Pause failed.");
    } finally {
      setPendingKey(null);
    }
  }

  async function handleResume() {
    if (!project) {
      return;
    }
    const startedAt = Date.now();
    setPendingKey("resume");
    setNotice(null);
    try {
      await updateProjectProviderCapacity(project.project_id, {
        queue_mode: "running",
        max_running_jobs: project.provider_capacity.max_running_jobs,
        preferred_provider_id: project.provider_capacity.preferred_provider_id ?? null,
      });
      const result = await runOrchestratorPass(6, 4, true);
      await loadCommand();
      await holdPendingState(startedAt);
      await loadCommand();
      const started = (result.provider_jobs_processed ?? 0) + (result.provider_jobs_dispatched ?? 0);
      setNotice(`Resumed execution. ${started} run${started === 1 ? "" : "s"} started.`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Resume failed.");
    } finally {
      setPendingKey(null);
    }
  }

  async function handleDrain() {
    if (!project) {
      return;
    }
    const startedAt = Date.now();
    setPendingKey("drain");
    setNotice(null);
    try {
      await updateProjectProviderCapacity(project.project_id, {
        queue_mode: "draining",
        max_running_jobs: project.provider_capacity.max_running_jobs,
        preferred_provider_id: project.provider_capacity.preferred_provider_id ?? null,
      });
      await loadCommand();
      await holdPendingState(startedAt);
      await loadCommand();
      setNotice("Queue is draining. Running and queued work can finish, but new assigned issues will not launch.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Drain failed.");
    } finally {
      setPendingKey(null);
    }
  }

  async function handleAutopilotToggle(enabled: boolean) {
    if (!project || !autopilot) {
      return;
    }
    const startedAt = Date.now();
    setPendingKey(enabled ? "autopilot-enable" : "autopilot-disable");
    setNotice(null);
    try {
      await updateProjectAutopilot(project.project_id, {
        enabled,
        interval_seconds: autopilot.policy.interval_seconds,
        allocate_limit: autopilot.policy.allocate_limit,
        provider_job_limit: autopilot.policy.provider_job_limit,
        auto_launch_assigned_work: autopilot.policy.auto_launch_assigned_work,
        process_notifications: autopilot.policy.process_notifications,
        notification_batch_limit: autopilot.policy.notification_batch_limit,
        schedule_window_start_hour_utc: autopilot.policy.schedule_window_start_hour_utc ?? null,
        schedule_window_end_hour_utc: autopilot.policy.schedule_window_end_hour_utc ?? null,
        stop_when_doctor_blocked: autopilot.policy.stop_when_doctor_blocked ?? false,
        max_review_queue: autopilot.policy.max_review_queue ?? 0,
        max_blocked_queue: autopilot.policy.max_blocked_queue ?? 0,
        max_idle_cycles_before_alert: autopilot.policy.max_idle_cycles_before_alert ?? 0,
        max_stale_runs: autopilot.policy.max_stale_runs ?? 0,
        max_repeated_failure_incidents: autopilot.policy.max_repeated_failure_incidents ?? 0,
        max_notification_failures: autopilot.policy.max_notification_failures ?? 0,
      });
      await loadCommand();
      await holdPendingState(startedAt);
      await loadCommand();
      setNotice(enabled ? "Autopilot enabled for this project." : "Autopilot disabled for this project.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not update autopilot.");
    } finally {
      setPendingKey(null);
    }
  }

  async function handleControlAction(action: ControlOperatorAction) {
    const startedAt = Date.now();
    const actionKey = `control:${action.action}:${action.resource_id}`;
    setPendingKey(actionKey);
    setNotice(null);
    try {
      const result = await runControlOperatorAction(action);
      await loadCommand();
      await holdPendingState(startedAt);
      await loadCommand();
      if (
        action.action === "process_next_notification" &&
        result &&
        typeof result === "object" &&
        "processed" in result &&
        !result.processed
      ) {
        setNotice("No due notification delivery was available to process.");
      } else if (
        action.action === "process_notification" &&
        result &&
        typeof result === "object" &&
        "status" in result &&
        typeof result.status === "string"
      ) {
        setNotice(`Notification delivery processed with status ${result.status}.`);
      } else {
        setNotice(`${action.label} complete.`);
      }
    } catch (error) {
      setNotice(error instanceof Error ? error.message : `${action.label} failed.`);
    } finally {
      setPendingKey(null);
    }
  }

  async function handleCreateGoal(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedTitle = goalTitle.trim();
    if (!trimmedTitle) {
      setGoalNotice("Goal title is required.");
      return;
    }
    setPendingKey("goal-create");
    setGoalNotice(null);
    try {
      const payload = await createGoal({
        title: trimmedTitle,
        description: goalDescription.trim(),
        goal_type: "initiative",
        priority: 75,
      });
      await synthesizeGoal(payload.goal.goal_id, true);
      await loadCommand();
      setGoalTitle("");
      setGoalDescription("");
      setGoalNotice(`Created goal "${payload.goal.title}" and synthesized an initial issue plan.`);
    } catch (error) {
      setGoalNotice(error instanceof Error ? error.message : "Could not create a goal.");
    } finally {
      setPendingKey(null);
    }
  }

  async function handleSynthesizeGoal(goalId: string) {
    setPendingKey(`goal-sync:${goalId}`);
    setGoalNotice(null);
    try {
      const result = await synthesizeGoal(goalId, true);
      await loadCommand();
      setGoalNotice(
        `Refreshed goal plan: ${result.created_count} created, ${result.updated_count} updated, ${result.cancelled_count} cancelled.`
      );
    } catch (error) {
      setGoalNotice(error instanceof Error ? error.message : "Could not refresh the goal plan.");
    } finally {
      setPendingKey(null);
    }
  }

  async function handlePreparePrDraft(taskId: string) {
    setPendingKey(`delivery:draft:${taskId}`);
    setDeliveryNotice(null);
    try {
      const payload = await prepareTaskPrDraft(taskId);
      await loadCommand();
      setDeliveryNotice(`Prepared PR draft "${payload.title}". Suggested command: ${payload.gh_command}`);
    } catch (error) {
      setDeliveryNotice(error instanceof Error ? error.message : "Could not prepare the PR draft.");
    } finally {
      setPendingKey(null);
    }
  }

  async function handleSyncGithubPr(taskId: string) {
    setPendingKey(`delivery:sync:${taskId}`);
    setDeliveryNotice(null);
    try {
      const payload = await syncTaskGithubPr(taskId);
      await loadCommand();
      setDeliveryNotice(
        `${payload.mode === "created" ? "Created" : "Updated"} draft PR #${payload.github_pr.number}: ${payload.github_pr.url}`
      );
    } catch (error) {
      setDeliveryNotice(error instanceof Error ? error.message : "Could not sync the GitHub draft PR.");
    } finally {
      setPendingKey(null);
    }
  }

  return (
    <section className="codex-page">
      <header className="codex-page__header">
        <div>
          <span className="codex-kicker">Command</span>
          <h1>What needs judgment, what is moving, and what just landed</h1>
          <p>Use this page to decide what needs intervention now, not to micromanage every task.</p>
        </div>
        <div className="codex-page__actions">
          <button type="button" className="codex-button codex-button--primary" disabled={pendingKey !== null} onClick={() => void handleRun()}>
            {pendingKey === "run" ? "Running..." : "Run next cycle"}
          </button>
          {launchPosture.mode === "running" ? (
            <>
              <button type="button" className="codex-button" disabled={pendingKey !== null || !project} onClick={() => void handleDrain()}>
                {pendingKey === "drain" ? "Draining..." : "Drain queue"}
              </button>
              <button type="button" className="codex-button" disabled={pendingKey !== null || !project} onClick={() => void handlePause()}>
                {pendingKey === "pause" ? "Pausing..." : "Pause launches"}
              </button>
            </>
          ) : launchPosture.mode === "draining" ? (
            <>
              <button type="button" className="codex-button" disabled={pendingKey !== null || !project} onClick={() => void handleResume()}>
                {pendingKey === "resume" ? "Resuming..." : "Resume launches"}
              </button>
              <button type="button" className="codex-button" disabled={pendingKey !== null || !project} onClick={() => void handlePause()}>
                {pendingKey === "pause" ? "Pausing..." : "Pause launches"}
              </button>
            </>
          ) : (
            <button type="button" className="codex-button" disabled={pendingKey !== null || !project} onClick={() => void handleResume()}>
              {pendingKey === "resume" ? "Resuming..." : "Resume launches"}
            </button>
          )}
        </div>
      </header>

      <div className="codex-metric-grid">
        <article className="codex-panel codex-stat">
          <strong>{tasks.length}</strong>
          <span>Open issues</span>
          <p>{counts.in_progress} active · {counts.blocked} blocked</p>
        </article>
        <article className="codex-panel codex-stat">
          <strong>{runningAgents}</strong>
          <span>Active agents</span>
          <p>{overview?.summary.tasks_in_progress ?? 0} tasks currently running</p>
        </article>
        <article className="codex-panel codex-stat">
          <strong>{launchPosture.label}</strong>
          <span>Launch posture</span>
          <p>{launchPosture.summary}</p>
        </article>
        <article className="codex-panel codex-stat">
          <strong>{resolved.length}</strong>
          <span>Resolved</span>
          <p>Finished work remains searchable in Issues.</p>
        </article>
        <article className="codex-panel codex-stat">
          <strong>{queue.length}</strong>
          <span>Needs judgment</span>
          <p>{alerts.filter((alert) => alert.status === "open").length} open alerts · {recentFailureCount} recent failures</p>
        </article>
      </div>

      <OperatorLoopPanel
        workflow={operatorWorkflow}
        title="Shared inbox and execution posture"
        description="Command owns the loop posture. Use Issues for review or recovery decisions and Runs for live-session intervention."
        onSelectItem={onOpenOperatorItem}
        warning={operatorWorkflowWarning}
        footer={
          <div className="codex-detail-actions">
            {autopilot?.policy.enabled ? (
              <button
                type="button"
                className="codex-button"
                disabled={pendingKey !== null || !project}
                onClick={() => void handleAutopilotToggle(false)}
              >
                {pendingKey === "autopilot-disable" ? "Disabling..." : "Disable autopilot"}
              </button>
            ) : (
              <button
                type="button"
                className="codex-button codex-button--primary"
                disabled={pendingKey !== null || !project}
                onClick={() => void handleAutopilotToggle(true)}
              >
                {pendingKey === "autopilot-enable" ? "Enabling..." : "Enable autopilot"}
              </button>
            )}
            <button type="button" className="codex-button" onClick={() => onNavigate("issues")}>
              Open Issues
            </button>
            <button type="button" className="codex-button" onClick={() => onNavigate("runs")}>
              Open Runs
            </button>
          </div>
        }
      />
      {workflowActions.length ? (
        <div className="codex-detail-actions">
          {workflowActions.slice(0, 4).map((action) => (
            <button
              key={`workflow:${action.action}:${action.resource_type}:${action.resource_id}:${action.label}`}
              type="button"
              className="codex-button codex-button--primary"
              disabled={pendingKey !== null}
              onClick={() => void handleControlAction(action)}
            >
              {pendingKey === `control:${action.action}:${action.resource_id}` ? "Running..." : action.label}
            </button>
          ))}
        </div>
      ) : null}

      {notice ? <div className="codex-banner">{notice}</div> : null}
      {overview?.onboarding?.mode === "brownfield" && brownfieldTrust && brownfieldTrust.state !== "fresh" ? (
        <div className="codex-banner codex-banner--warn">
          <strong>{brownfieldTrust.summary}</strong>
          <div>{brownfieldTrust.detail}</div>
          <div>
            {brownfieldTrust.state.replaceAll("_", " ")} · drift {brownfieldTrust.drift_severity}
            {" · "}
            Recommended action: {brownfieldTrust.recommended_action}
          </div>
        </div>
      ) : null}

      <div className="codex-three-column">
        <section className="codex-panel">
          <div className="codex-panel__header">
            <div>
              <span className="codex-kicker">Doctor</span>
              <h2>Safe start and no-progress diagnosis</h2>
            </div>
            <span
              className={`codex-chip ${
                doctor?.summary.status === "blocked"
                  ? "codex-chip--tone-danger"
                  : doctor?.summary.status === "ready"
                    ? "codex-chip--active"
                    : "codex-chip--tone-warn"
              }`}
            >
              {doctor?.summary.label ?? "Loading"}
            </span>
          </div>
          <p>{doctor?.summary.summary ?? "Refreshing environment doctor checks."}</p>
          <div className="codex-inline-facts">
            <span className="codex-chip">{doctor?.progress.status?.replaceAll("_", " ") ?? "idle"}</span>
            <span className="codex-chip">{doctor?.progress.facts.review_tasks ?? 0} review</span>
            <span className="codex-chip">{doctor?.progress.facts.blocked_tasks ?? 0} blocked</span>
            <span className="codex-chip">{doctor?.preferred_provider_id ?? "provider?"}</span>
          </div>
          <p className="codex-muted-copy">{doctor?.progress.detail ?? "The doctor will explain why progress is moving or stalled."}</p>
          {doctor?.progress.operator_actions?.length ? (
            <div className="codex-detail-actions">
              {doctor.progress.operator_actions.slice(0, 3).map((action) => (
                <button
                  key={`${action.action}:${action.resource_id}:${action.label}`}
                  type="button"
                  className="codex-button codex-button--primary"
                  disabled={pendingKey !== null}
                  onClick={() => void handleControlAction(action)}
                >
                  {pendingKey === `control:${action.action}:${action.resource_id}` ? "Running..." : action.label}
                </button>
              ))}
            </div>
          ) : null}
          <div className="codex-check-list">
            {(doctor?.checks ?? []).slice(0, 4).map((check) => (
              <div key={check.code} className="codex-check-list__item">
                <span className={`codex-check-list__state is-${check.status}`}>{check.status}</span>
                <div>
                  <strong>{check.label}</strong>
                  <p>{check.summary}</p>
                </div>
              </div>
            ))}
          </div>
          {(doctor?.progress.reasons?.length ?? 0) > 0 ? (
            <div className="codex-history-list">
              {(doctor?.progress.reasons ?? []).slice(0, 4).map((reason) => (
                <div key={reason.code} className="codex-history-item">
                  <div className="codex-history-item__meta">
                    <strong>{reason.summary}</strong>
                    <span>{reason.severity}</span>
                  </div>
                  <span>{reason.detail}</span>
                  {reason.operator_actions?.length ? (
                    <div className="codex-detail-actions">
                      {reason.operator_actions.slice(0, 2).map((action) => (
                        <button
                          key={`${reason.code}:${action.action}:${action.resource_id}`}
                          type="button"
                          className="codex-button"
                          disabled={pendingKey !== null}
                          onClick={() => void handleControlAction(action)}
                        >
                          {pendingKey === `control:${action.action}:${action.resource_id}` ? "Running..." : action.label}
                        </button>
                      ))}
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          ) : null}
          {(autopilot?.governance_gate?.signals?.length ?? 0) > 0 ? (
            <div className="codex-list-block">
              <strong>Autopilot governance</strong>
              <div className="codex-history-list">
                {(autopilot?.governance_gate?.signals ?? []).slice(0, 5).map((signal) => (
                  <div key={signal.code} className="codex-history-item">
                    <div className="codex-history-item__meta">
                      <strong>{signal.label}</strong>
                      <span>
                        {signal.count ?? 0}
                        {signal.threshold ? ` / ${signal.threshold}` : ""}
                        {signal.blocking ? " · blocking" : ""}
                      </span>
                    </div>
                    <span>{signal.summary}</span>
                    <span>{signal.detail}</span>
                    {signal.operator_actions?.length ? (
                      <div className="codex-detail-actions">
                        {signal.operator_actions.slice(0, 2).map((action) => (
                          <button
                            key={`${signal.code}:${action.action}:${action.resource_id}`}
                            type="button"
                            className="codex-button"
                            disabled={pendingKey !== null}
                            onClick={() => void handleControlAction(action)}
                          >
                            {pendingKey === `control:${action.action}:${action.resource_id}` ? "Running..." : action.label}
                          </button>
                        ))}
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
            </div>
          ) : null}
          {notificationAttention.length ? (
            <div className="codex-list-block">
              <strong>Notification delivery recovery</strong>
              <div className="codex-history-list">
                {notificationAttention.map((item) => (
                  <div
                    key={`${item.resource_id ?? item.title}:${item.subtype ?? "notification"}`}
                    className="codex-history-item"
                  >
                    <div className="codex-history-item__meta">
                      <strong>{item.title ?? "Notification delivery needs attention"}</strong>
                      <span>{String(item.metadata?.delivery_state ?? item.subtype ?? "failed").replaceAll("_", " ")}</span>
                    </div>
                    <span>{item.summary ?? "Notification delivery is delayed or exhausted and needs operator review."}</span>
                    {item.recommended_action ? <span>{item.recommended_action}</span> : null}
                    {item.operator_actions?.length ? (
                      <div className="codex-detail-actions">
                        {item.operator_actions.slice(0, 2).map((action) => (
                          <button
                            key={`${item.resource_id ?? item.title}:${action.action}:${action.resource_id}`}
                            type="button"
                            className="codex-button"
                            disabled={pendingKey !== null}
                            onClick={() => void handleControlAction(action)}
                          >
                            {pendingKey === `control:${action.action}:${action.resource_id}` ? "Running..." : action.label}
                          </button>
                        ))}
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
            </div>
          ) : null}
          {(doctor?.recommended_actions?.length ?? 0) > 0 ? (
            <div className="codex-list-block">
              <strong>Recommended next actions</strong>
              <ul>
                {doctor?.recommended_actions.map((item) => <li key={item}>{item}</li>)}
              </ul>
            </div>
          ) : null}
        </section>

        <section className="codex-panel">
          <div className="codex-panel__header">
            <div>
              <span className="codex-kicker">Goals</span>
              <h2>Intake and issue synthesis</h2>
            </div>
            <span className="codex-chip">{goalPlanning?.summary.total_goals ?? 0} goals</span>
          </div>
          <form className="codex-inline-form" onSubmit={(event) => void handleCreateGoal(event)}>
            <label className="field-control">
              <span>Goal title</span>
              <input value={goalTitle} onChange={(event) => setGoalTitle(event.target.value)} placeholder="Define the next objective" />
            </label>
            <label className="field-control">
              <span>Why it matters</span>
              <textarea value={goalDescription} onChange={(event) => setGoalDescription(event.target.value)} placeholder="Optional context that should influence planning" rows={3} />
            </label>
            <button type="submit" className="codex-button codex-button--primary" disabled={pendingKey !== null}>
              {pendingKey === "goal-create" ? "Creating..." : "Create goal + synthesize plan"}
            </button>
          </form>
          {goalNotice ? <div className="codex-banner">{goalNotice}</div> : null}
          <div className="codex-stack-list">
            {(goalPlanning?.items ?? []).slice(0, 4).map((goal) => (
              <div key={goal.goal_id} className="codex-stack-item codex-stack-item--static">
                <div className="codex-stack-item__header">
                  <strong>{goal.title}</strong>
                  <span>{goal.next_step}</span>
                </div>
                <span>{goal.goal_type} · {goal.open_issue_count} open issues · {goal.synthesized_tasks} synthesized</span>
                <p>{goal.description || "No goal description recorded yet."}</p>
                {goal.plan?.summary.task_count ? (
                  <div className="codex-list-block">
                    <strong>
                      Critical path: {goal.plan.summary.critical_path_remaining} remaining
                      {goal.plan.summary.current_focus_issue_key || goal.plan.summary.current_focus_title
                        ? ` · focus ${goal.plan.summary.current_focus_issue_key ?? goal.plan.summary.current_focus_title}`
                        : ""}
                    </strong>
                    <div className="codex-run-list codex-run-list--compact">
                      {goal.plan.tasks.slice(0, 5).map((item) => (
                        <button
                          key={item.task_id}
                          type="button"
                          className="codex-output-item codex-output-item--interactive"
                          onClick={() => {
                            setPendingTaskFocus(item.task_id);
                            onNavigate("issues");
                          }}
                        >
                          <strong>
                            {item.issue_key ?? item.task_id} · {item.title}
                          </strong>
                          <span>
                            Step {item.step_index}/{item.step_count}
                            {item.stage_label ? ` · ${item.stage_label}` : ""}
                            {item.is_current_focus ? " · current focus" : ""}
                            {item.is_on_critical_path ? ` · critical path #${item.critical_path_rank}` : ""}
                          </span>
                          <span>{item.why_it_exists}</span>
                        </button>
                      ))}
                    </div>
                  </div>
                ) : null}
                <div className="codex-detail-actions">
                  <button
                    type="button"
                    className="codex-button"
                    disabled={pendingKey !== null}
                    onClick={() => void handleSynthesizeGoal(goal.goal_id)}
                  >
                    {pendingKey === `goal-sync:${goal.goal_id}` ? "Refreshing..." : "Refresh issue plan"}
                  </button>
                </div>
              </div>
            ))}
            {!goalPlanning?.items.length ? (
              <div className="codex-empty-copy">No goals yet. Create one objective and let MAAS derive the initial issue plan.</div>
            ) : null}
          </div>
        </section>

        <section className="codex-panel">
          <div className="codex-panel__header">
            <div>
              <span className="codex-kicker">Delivery</span>
              <h2>Turn completed work into deliverables</h2>
            </div>
            <span className="codex-chip">
              {delivery?.summary.ready_count ?? 0} ready · {delivery?.summary.candidate_count ?? 0} candidates
            </span>
          </div>
          <p className="codex-muted-copy">
            {delivery?.git.is_git_repo
              ? `Repo branch ${delivery.git.branch ?? "unknown"} is ${delivery.git.dirty ? "dirty" : "clean"} for delivery preparation.`
              : "No Git repository detected yet, so PR delivery is limited."}
          </p>
          {deliveryNotice ? <div className="codex-banner">{deliveryNotice}</div> : null}
          <div className="codex-stack-list">
            {(delivery?.items ?? []).slice(0, 4).map((item) => (
              <div key={item.task_id} className="codex-stack-item codex-stack-item--static">
                <div className="codex-stack-item__header">
                  <strong>{item.issue_key ?? item.task_id}</strong>
                  <span>{item.delivery_kind} · {item.delivery_gate.status}</span>
                </div>
                <span>{item.title}</span>
                <p>{item.goal_title ?? "No linked goal"} · {item.artifact_count} artifacts</p>
                <p className="codex-muted-copy">{item.delivery_gate.summary}</p>
                {item.github_pr ? (
                  <p className="codex-muted-copy">
                    PR #{item.github_pr.number} · {item.github_pr.is_draft ? "draft" : "ready"} · {item.github_pr.url}
                  </p>
                ) : null}
                <div className="codex-detail-actions">
                  <button
                    type="button"
                    className="codex-button"
                    disabled={pendingKey !== null}
                    onClick={() => void handlePreparePrDraft(item.task_id)}
                  >
                    {pendingKey === `delivery:draft:${item.task_id}` ? "Preparing..." : "Prepare PR draft"}
                  </button>
                  <button
                    type="button"
                    className="codex-button"
                    disabled={pendingKey !== null || item.delivery_gate.status === "blocked"}
                    onClick={() => void handleSyncGithubPr(item.task_id)}
                  >
                    {pendingKey === `delivery:sync:${item.task_id}`
                      ? "Syncing..."
                      : item.github_pr
                        ? "Sync draft PR"
                        : "Create draft PR"}
                  </button>
                  <button
                    type="button"
                    className="codex-button"
                    onClick={() => {
                      setPendingTaskFocus(item.task_id);
                      onNavigate("issues");
                    }}
                  >
                    Open issue
                  </button>
                </div>
              </div>
            ))}
            {!delivery?.items.length ? (
              <div className="codex-empty-copy">No reviewable or delivered work is ready to package yet.</div>
            ) : null}
          </div>
        </section>
      </div>

      <section className="codex-panel">
        <div className="codex-panel__header">
          <div>
            <span className="codex-kicker">Retrieval</span>
            <h2>Search prior work, runs, artifacts, and machine history</h2>
          </div>
        </div>
        <div className="codex-search-panel">
          <label className="field-control field-control--search">
            <span>Search memory</span>
            <input
              type="search"
              value={searchQuery}
              placeholder="Search issues, runs, artifacts, and recent activity"
              onChange={(event) => setSearchQuery(event.target.value)}
            />
          </label>
          <div className="hero-meta">
            <span className="hero-meta__pill">{retrieval?.summary.issue_hits ?? 0} issues</span>
            <span className="hero-meta__pill">{retrieval?.summary.run_hits ?? 0} runs</span>
            <span className="hero-meta__pill">{retrieval?.summary.artifact_hits ?? 0} artifacts</span>
            <span className="hero-meta__pill">{retrieval?.summary.event_hits ?? 0} events</span>
            <span className="hero-meta__pill">{retrieval?.summary.memory_hits ?? 0} memory</span>
          </div>
        </div>
        {retrievalNotice ? <p className="field-hint">{retrievalNotice}</p> : null}
        {searchQuery.trim().length < 2 ? (
          <div className="codex-empty-copy">Type at least two characters to search the wider project memory.</div>
        ) : (
          <div className="codex-three-column codex-three-column--dense">
            <section className="codex-panel codex-panel--nested">
              <div className="codex-panel__header">
                <div>
                  <span className="codex-kicker">Issues</span>
                  <h3>Matching work</h3>
                </div>
              </div>
              <div className="codex-stack-list">
                {(retrieval?.issues ?? []).map((item) => (
                  <button
                    key={item.task_id}
                    type="button"
                    className="codex-stack-item"
                    onClick={() => {
                      setPendingTaskFocus(item.task_id);
                      onNavigate("work");
                    }}
                  >
                    <div className="codex-stack-item__header">
                      <strong>{item.issue_key ?? item.task_id}</strong>
                      <span>{item.status}</span>
                    </div>
                    <span>{item.title}</span>
                    <p>{item.match_context}</p>
                  </button>
                ))}
                {!retrieval?.issues.length ? <div className="codex-empty-copy">No issue matches.</div> : null}
              </div>
            </section>

            <section className="codex-panel codex-panel--nested">
              <div className="codex-panel__header">
                <div>
                  <span className="codex-kicker">Runs + artifacts</span>
                  <h3>Execution evidence</h3>
                </div>
              </div>
              <div className="codex-stack-list">
                {(retrieval?.runs ?? []).map((item) => (
                  <button
                    key={item.session_id}
                    type="button"
                    className="codex-stack-item"
                    onClick={() => {
                      setPendingRunFocus(item.session_id);
                      onNavigate("runs");
                    }}
                  >
                    <div className="codex-stack-item__header">
                      <strong>{item.issue_key ?? item.session_id}</strong>
                      <span>{item.status}</span>
                    </div>
                    <span>{item.task_title ?? item.provider_type}</span>
                    <p>{item.match_context}</p>
                  </button>
                ))}
                {(retrieval?.artifacts ?? []).map((item) => (
                  <button
                    key={item.artifact_id}
                    type="button"
                    className="codex-stack-item"
                    onClick={() => {
                      if (item.task_id) {
                        setPendingTaskFocus(item.task_id);
                        onNavigate("work");
                      } else if (item.session_id) {
                        setPendingRunFocus(item.session_id);
                        onNavigate("runs");
                      }
                    }}
                  >
                    <div className="codex-stack-item__header">
                      <strong>{item.issue_key ?? item.artifact_type}</strong>
                      <span>{item.artifact_state}</span>
                    </div>
                    <span>{item.title}</span>
                    <p>{item.artifact_path}</p>
                  </button>
                ))}
                {!retrieval?.runs.length && !retrieval?.artifacts.length ? (
                  <div className="codex-empty-copy">No run or artifact matches.</div>
                ) : null}
              </div>
            </section>

            <section className="codex-panel codex-panel--nested">
              <div className="codex-panel__header">
                <div>
                  <span className="codex-kicker">Recent events</span>
                  <h3>Machine history</h3>
                </div>
              </div>
              <div className="codex-history-list">
                {(retrieval?.events ?? []).map((item) => (
                  <button
                    key={item.event_id}
                    type="button"
                    className="codex-history-item codex-history-item--button"
                    onClick={() => {
                      if (item.task_id) {
                        setPendingTaskFocus(item.task_id);
                        onNavigate("issues");
                        return;
                      }
                      if (item.session_id) {
                        setPendingRunFocus(item.session_id);
                        onNavigate("runs");
                        return;
                      }
                      onNavigate("system");
                    }}
                  >
                    <div className="codex-history-item__meta">
                      <strong>{item.title}</strong>
                      <span>{formatTimestamp(item.created_at)}</span>
                    </div>
                    <span>{item.description}</span>
                  </button>
                ))}
                {!retrieval?.events.length ? <div className="codex-empty-copy">No event matches.</div> : null}
              </div>
            </section>

            <section className="codex-panel codex-panel--nested">
              <div className="codex-panel__header">
                <div>
                  <span className="codex-kicker">Memory</span>
                  <h3>Promoted guidance</h3>
                </div>
              </div>
              <div className="codex-stack-list">
                {(retrieval?.memory ?? []).map((item) => (
                  <button
                    key={item.artifact_id}
                    type="button"
                    className="codex-stack-item"
                    onClick={() => {
                      if (item.task_id) {
                        setPendingTaskFocus(item.task_id);
                        onNavigate("work");
                        return;
                      }
                      if (item.session_id) {
                        setPendingRunFocus(item.session_id);
                        onNavigate("runs");
                      }
                    }}
                  >
                    <div className="codex-stack-item__header">
                      <strong>{item.title || item.artifact_id}</strong>
                      <span>{item.promoted_at ? formatTimestamp(item.promoted_at) : "memory"}</span>
                    </div>
                    <span>{item.summary || item.path || "Promoted project memory"}</span>
                    <p>{item.match_summary || item.preview?.content || item.tags?.join(" · ") || "Reusable context for future Codex runs."}</p>
                    <p>
                      {(item.tags?.length ?? 0) ? item.tags?.join(" · ") : "No tags"}
                      {item.usefulness ? ` · usefulness ${item.usefulness}` : ""}
                      {item.usefulness_summary ? ` · ${item.usefulness_summary}` : ""}
                    </p>
                  </button>
                ))}
                {!retrieval?.memory.length ? <div className="codex-empty-copy">No memory matches.</div> : null}
              </div>
            </section>
          </div>
        )}
      </section>

      <div className="codex-three-column">
        <section className="codex-panel">
          <div className="codex-panel__header">
            <div>
              <span className="codex-kicker">Decision queue</span>
              <h2>Operator-facing issues</h2>
            </div>
          </div>
          <div className="codex-stack-list">
            {queue.map((task) => (
              <button
                key={task.task_id}
                type="button"
                className="codex-stack-item"
                onClick={() => {
                  setPendingTaskFocus(task.task_id);
                  onNavigate("issues");
                }}
              >
                <div className="codex-stack-item__header">
                  <strong>{issueLabel(task, keyMap)}</strong>
                  <span>{task.status === "review" ? "Review now" : "Open issue"}</span>
                </div>
                <span>{task.title}</span>
                <p>{task.description ?? task.scheduler_summary ?? "No summary recorded."}</p>
              </button>
            ))}
            {!queue.length ? <div className="codex-empty-copy">Nothing currently requires operator judgment.</div> : null}
          </div>
        </section>

        <section className="codex-panel">
          <div className="codex-panel__header">
            <div>
              <span className="codex-kicker">Landed</span>
              <h2>Recently resolved work</h2>
            </div>
          </div>
          <div className="codex-stack-list">
            {resolved.slice(0, 8).map((task) => (
              <button
                key={task.task_id}
                type="button"
                className="codex-stack-item"
                onClick={() => {
                  setPendingTaskFocus(task.task_id);
                  onNavigate("issues");
                }}
              >
                <div className="codex-stack-item__header">
                  <strong>{issueLabel(task, keyMap)}</strong>
                  <span>{formatTimestamp(task.latest_verification_at ?? null)}</span>
                </div>
                <span>{task.title}</span>
                <p>{task.goal?.title ?? "Resolved work"}</p>
              </button>
            ))}
          </div>
        </section>

        <section className="codex-panel">
          <div className="codex-panel__header">
            <div>
              <span className="codex-kicker">History</span>
              <h2>Recent machine activity</h2>
            </div>
          </div>
          <div className="codex-history-list">
            {timeline.slice(0, 12).map((event) => (
              <div key={`${event.source}:${event.event_id}`} className="codex-history-item">
                <div className="codex-history-item__meta">
                  <strong>{event.title}</strong>
                  <span>{formatTimestamp(event.created_at)}</span>
                </div>
                <span>{event.description}</span>
              </div>
            ))}
          </div>
        </section>
      </div>
    </section>
  );
}
