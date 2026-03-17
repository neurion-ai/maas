import { useEffect, useState } from "react";
import { fetchOverview, runAlertOperatorAction, runFailureOperatorAction, runSupervisorPass } from "../lib/controlRoomApi";
import { reviewTask } from "../lib/boardApi";
import { useLivePulse } from "../lib/useLivePulse";
import type { OverviewResponse, SupervisorRunResponse } from "../types";
import { StatCard } from "../components/StatCard";

export function OverviewPage() {
  const [overview, setOverview] = useState<OverviewResponse | null>(null);
  const [supervisorResult, setSupervisorResult] = useState<SupervisorRunResponse | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [isRunningSupervisor, setIsRunningSupervisor] = useState(false);
  const [pendingFailureAction, setPendingFailureAction] = useState<string | null>(null);
  const [pendingRepeatedFailureAction, setPendingRepeatedFailureAction] = useState<string | null>(null);
  const [pendingOnboardingReview, setPendingOnboardingReview] = useState<string | null>(null);
  const livePulse = useLivePulse();

  useEffect(() => {
    let mounted = true;

    async function loadOverview() {
      const payload = await fetchOverview();
      if (mounted) {
        setOverview(payload);
      }
    }

    void loadOverview();

    return () => {
      mounted = false;
    };
  }, [livePulse]);

  async function handleRunSupervisor() {
    setIsRunningSupervisor(true);
    setNotice(null);
    try {
      const result = await runSupervisorPass(2);
      setSupervisorResult(result);
      setNotice(
        `Supervisor refreshed ${result.ready_changes.length} tasks, assigned ${result.assigned_count}, and found ${result.stale_sessions.length} stale sessions.`
      );
      setOverview(await fetchOverview());
    } catch {
      setNotice("Supervisor run failed; keeping the most recent overview snapshot.");
    } finally {
      setIsRunningSupervisor(false);
    }
  }

  async function handleOverviewFailureAction(
    failureId: string,
    actionKind: "primary" | "secondary" = "primary",
  ) {
    const failure = overview?.recent_failures.find((item) => item.failure_id === failureId);
    const operatorAction =
      actionKind === "secondary" ? failure?.secondary_operator_action : failure?.operator_action;
    if (!operatorAction) {
      return;
    }

    setPendingFailureAction(`${failureId}:${operatorAction.action}`);
    setNotice(null);
    try {
      await runFailureOperatorAction(operatorAction);
      setOverview(await fetchOverview());
      if (operatorAction.action === "restore_and_requeue_quarantine_entry") {
        setNotice(`Restored quarantined artifacts and returned task ${operatorAction.related_task_id} to the queue.`);
      } else if (operatorAction.action === "dismiss_quarantine_entry") {
        setNotice(`Dismissed quarantine incident for failure ${failureId}; artifacts remain isolated.`);
      } else if (operatorAction.action === "reopen_quarantine_entry") {
        setNotice(`Reopened dismissed quarantine entry for failure ${failureId}.`);
      } else if (operatorAction.action === "restore_failure_artifacts") {
        setNotice(`Restored quarantined artifacts for failure ${failureId}.`);
      } else {
        setNotice(`Recovered and requeued task ${operatorAction.resource_id}.`);
      }
    } catch {
      setNotice("Failure action failed; keep the incident under operator review.");
    } finally {
      setPendingFailureAction(null);
    }
  }

  async function handleOverviewRepeatedFailureAction(taskId: string) {
    const repeatedFailure = overview?.repeated_failures.find((item) => item.task_id === taskId);
    if (!repeatedFailure?.operator_action) {
      return;
    }

    setPendingRepeatedFailureAction(`${taskId}:${repeatedFailure.operator_action.action}`);
    setNotice(null);
    try {
      await runAlertOperatorAction(repeatedFailure.operator_action);
      setOverview(await fetchOverview());
      setNotice(`Resolved the repeated-failure incident for ${taskId}.`);
    } catch {
      setNotice("Repeated-failure resolution failed; keep the task under operator review.");
    } finally {
      setPendingRepeatedFailureAction(null);
    }
  }

  async function handleOnboardingReview(decision: "approve" | "reject") {
    const reviewTaskId = overview?.onboarding?.review_task_id;
    if (!reviewTaskId) {
      return;
    }

    setPendingOnboardingReview(decision);
    setNotice(null);
    try {
      await reviewTask(reviewTaskId, decision);
      setOverview(await fetchOverview());
      setNotice(
        decision === "approve"
          ? "Brownfield onboarding approved; imported work is now eligible for scheduling."
          : "Brownfield onboarding sent back with changes requested; imported work remains gated."
      );
    } catch {
      setNotice("Brownfield onboarding review action failed; keep the imported work under operator review.");
    } finally {
      setPendingOnboardingReview(null);
    }
  }

  return (
    <section className="control-page">
      <header className="page-hero">
        <div>
          <span className="eyebrow">Overview</span>
          <h1>{overview?.project?.name ?? "MAAS Control Room"}</h1>
          <p>{overview?.project?.description ?? "High-level system status, active work, and recent movement."}</p>
        </div>
        <div className="page-hero__actions">
          <button
            type="button"
            className="task-action task-action--secondary"
            disabled={isRunningSupervisor}
            onClick={() => void handleRunSupervisor()}
          >
            {isRunningSupervisor ? "Running supervisor..." : "Run supervisor pass"}
          </button>
          {notice ? <p className="page-hero__notice">{notice}</p> : null}
        </div>
      </header>

      <section className="stats-grid">
        <StatCard label="Tasks total" value={overview?.summary.tasks_total ?? 0} />
        <StatCard label="In progress" value={overview?.summary.tasks_in_progress ?? 0} tone="good" />
        <StatCard label="Review queue" value={overview?.summary.tasks_review ?? 0} />
        <StatCard label="Blocked" value={overview?.summary.tasks_blocked ?? 0} tone="warn" />
        <StatCard label="Open escalations" value={overview?.summary.escalations_open ?? 0} tone="warn" />
        <StatCard label="Failures logged" value={overview?.summary.failures_total ?? 0} tone="warn" />
        <StatCard label="Repeated failures" value={overview?.summary.repeated_failure_tasks ?? 0} tone="warn" />
      </section>

      <section className="overview-grid">
        {overview?.onboarding?.mode === "brownfield" ? (
          <article className="data-panel">
            <header className="data-panel__header">
              <h2>Brownfield onboarding</h2>
              <p>Imported repo understanding must be explicitly reviewed before the seeded work is released.</p>
            </header>
              <div className="data-list">
                <div className="data-list__item">
                <div>
                  <strong>Status</strong>
                  <p>{overview.onboarding.review_status.replaceAll("_", " ")}</p>
                </div>
                <div className="data-list__meta">
                  <span>{overview.onboarding.discovery_summary.primary_language ?? "unknown stack"}</span>
                  <span>{overview.onboarding.discovery_summary.total_files ?? 0} files scanned</span>
                </div>
              </div>
                <div className="data-list__item">
                  <div>
                    <strong>Discovery summary</strong>
                    <p>
                      {overview.onboarding.discovery_summary.package_managers?.join(", ") || "no package manager detected"}
                  </p>
                </div>
                  <div className="data-list__meta">
                    <span>{overview.onboarding.pending_gated_tasks} gated tasks</span>
                    <span>{overview.onboarding.review_task_status ?? "no review task"}</span>
                  </div>
                </div>
                {(overview.onboarding.discovery_summary.workflow_details?.length ?? 0) > 0 ||
                (overview.onboarding.discovery_summary.workflow_labels?.length ?? 0) > 0 ? (
                  <div className="data-list__item">
                    <div>
                      <strong>Imported workflows</strong>
                      <p>{overview.onboarding.discovery_summary.workflow_labels?.join(", ")}</p>
                      {overview.onboarding.discovery_summary.workflow_details?.map((item) => (
                        <p key={`${item.label}-${item.path ?? ""}`}>
                          <strong>{item.label}</strong>
                          {item.path ? ` · ${item.path}` : ""}
                          {item.detail ? ` · ${item.detail}` : ""}
                        </p>
                      ))}
                    </div>
                    <div className="data-list__meta">
                      <span>{overview.onboarding.discovery_summary.workflow_details?.length ?? 0} signals</span>
                    </div>
                  </div>
                ) : null}
                {(overview.onboarding.discovery_summary.repo_areas?.length ?? 0) > 0 ? (
                  <div className="data-list__item">
                    <div>
                      <strong>Imported repo areas</strong>
                      <p>{overview.onboarding.discovery_summary.repo_areas?.join(", ")}</p>
                    </div>
                    <div className="data-list__meta">
                      <span>{overview.onboarding.discovery_summary.repo_areas?.length ?? 0} areas</span>
                    </div>
                  </div>
                ) : null}
                {overview.onboarding.reviewed_at ? (
                <div className="data-list__item">
                  <div>
                    <strong>Last decision</strong>
                    <p>{overview.onboarding.reviewed_by ?? "unknown actor"}</p>
                  </div>
                  <div className="data-list__meta">
                    <span>{new Date(overview.onboarding.reviewed_at).toLocaleString()}</span>
                  </div>
                </div>
              ) : null}
            </div>
            {overview.onboarding.review_required &&
            overview.onboarding.review_task_id &&
            overview.onboarding.review_task_status === "review" ? (
              <div className="task-card__actions">
                <button
                  type="button"
                  className="task-action task-action--approve"
                  disabled={pendingOnboardingReview === "approve" || pendingOnboardingReview === "reject"}
                  onClick={() => void handleOnboardingReview("approve")}
                >
                  {pendingOnboardingReview === "approve" ? "Approving..." : "Approve imported understanding"}
                </button>
                <button
                  type="button"
                  className="task-action task-action--reject"
                  disabled={pendingOnboardingReview === "approve" || pendingOnboardingReview === "reject"}
                  onClick={() => void handleOnboardingReview("reject")}
                >
                  {pendingOnboardingReview === "reject" ? "Rejecting..." : "Request changes"}
                </button>
              </div>
            ) : null}
          </article>
        ) : null}

        <article className="data-panel">
          <header className="data-panel__header">
            <h2>Supervisor pass</h2>
            <p>Manual orchestration trigger for readiness refresh, assignment, and stale-session checks.</p>
          </header>
          <div className="data-list">
            <div className="data-list__item">
              <div>
                <strong>Ready changes</strong>
                <p>{supervisorResult ? supervisorResult.ready_changes.length : 0} tasks updated in the last manual pass</p>
              </div>
              <div className="data-list__meta">
                <span>{supervisorResult ? supervisorResult.assigned_count : 0} assigned</span>
                <span>{supervisorResult ? supervisorResult.stale_sessions.length : 0} stale</span>
              </div>
            </div>
            {(supervisorResult?.allocations ?? []).map((allocation) => (
              <div key={`${allocation.agent_id}-${allocation.task_id}`} className="data-list__item">
                <div>
                  <strong>{allocation.task_title ?? allocation.task_id}</strong>
                  <p>{allocation.agent_id}</p>
                </div>
                <div className="data-list__meta">
                  <span>{allocation.status}</span>
                  <span>{allocation.assigned ? "new assignment" : "existing reservation"}</span>
                </div>
              </div>
            ))}
          </div>
        </article>

        <article className="data-panel">
          <header className="data-panel__header">
            <h2>Active work</h2>
            <p>What needs attention right now.</p>
          </header>
          <div className="data-list">
            {(overview?.active_work ?? []).map((item) => (
              <div key={item.task_id} className="data-list__item">
                <div>
                  <strong>{item.title}</strong>
                  <p>{item.goal_title ?? "Unlinked goal"}</p>
                </div>
                <div className="data-list__meta">
                  <span>{item.agent_name ?? "Unassigned"}</span>
                  <span>{item.status}</span>
                </div>
              </div>
            ))}
          </div>
        </article>

        <article className="data-panel">
          <header className="data-panel__header">
            <h2>Recent activity</h2>
            <p>Latest system movement from the blackboard.</p>
          </header>
          <div className="data-list">
            {(overview?.recent_activity ?? []).map((item, index) => (
              <div key={`${item.action}-${index}`} className="data-list__item">
                <div>
                  <strong>{item.action}</strong>
                  <p>{item.description}</p>
                </div>
                <div className="data-list__meta">
                  <span>{item.severity}</span>
                  <span>{new Date(item.created_at).toLocaleTimeString()}</span>
                </div>
              </div>
            ))}
          </div>
        </article>

        <article className="data-panel">
          <header className="data-panel__header">
            <h2>Recent failures</h2>
            <p>Failure memory for the latest failed or timed-out work.</p>
          </header>
          <div className="data-list">
            {(overview?.recent_failures ?? []).map((item) => (
              <div key={item.failure_id ?? `${item.task_id}-${item.created_at}`} className="data-list__item">
                <div>
                  <strong>{item.task_title ?? item.task_id ?? "Unlinked failure"}</strong>
                  <p>{item.summary}</p>
                  {item.quarantined_artifact_count ? (
                    <p>
                      Quarantined artifacts: {item.quarantined_artifact_count}
                    </p>
                  ) : null}
                </div>
                <div className="data-list__meta">
                  <span>{item.failure_type}</span>
                  <span>{new Date(item.created_at).toLocaleTimeString()}</span>
                  {item.operator_action ? (
                    <button
                      type="button"
                      className="task-action task-action--approve"
                      disabled={pendingFailureAction?.startsWith(`${item.failure_id}:`) ?? false}
                      onClick={() => item.failure_id && void handleOverviewFailureAction(item.failure_id, "primary")}
                    >
                      {pendingFailureAction === `${item.failure_id}:${item.operator_action.action}`
                        ? item.operator_action.action === "restore_and_requeue_quarantine_entry"
                          ? "Restoring..."
                          : item.operator_action.action === "dismiss_quarantine_entry"
                            ? "Dismissing..."
                            : item.operator_action.action === "reopen_quarantine_entry"
                              ? "Reopening..."
                              : item.operator_action.action === "restore_failure_artifacts"
                                ? "Restoring..."
                                : "Recovering..."
                        : item.operator_action.label}
                    </button>
                  ) : null}
                  {item.secondary_operator_action ? (
                    <button
                      type="button"
                      className="task-action task-action--secondary"
                      disabled={pendingFailureAction?.startsWith(`${item.failure_id}:`) ?? false}
                      onClick={() => item.failure_id && void handleOverviewFailureAction(item.failure_id, "secondary")}
                    >
                      {pendingFailureAction === `${item.failure_id}:${item.secondary_operator_action.action}`
                        ? item.secondary_operator_action.action === "dismiss_quarantine_entry"
                          ? "Dismissing..."
                          : item.secondary_operator_action.label
                        : item.secondary_operator_action.label}
                    </button>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        </article>

        <article className="data-panel">
          <header className="data-panel__header">
            <h2>Repeated failures</h2>
            <p>Tasks that are still over the repeated-failure threshold and may need explicit operator triage.</p>
          </header>
          <div className="data-list">
            {(overview?.repeated_failures ?? []).map((item) => (
              <div key={item.task_id} className="data-list__item">
                <div>
                  <strong>{item.task_title ?? item.task_id}</strong>
                  <p>{item.failure_count} logged failures</p>
                </div>
                <div className="data-list__meta">
                  <span>{item.task_id}</span>
                  <span>
                    {item.latest_failure_at ? new Date(item.latest_failure_at).toLocaleTimeString() : "No timestamp"}
                  </span>
                  {item.operator_action ? (
                    <button
                      type="button"
                      className="task-action task-action--approve"
                      disabled={pendingRepeatedFailureAction === `${item.task_id}:${item.operator_action.action}`}
                      onClick={() => void handleOverviewRepeatedFailureAction(item.task_id)}
                    >
                      {pendingRepeatedFailureAction === `${item.task_id}:${item.operator_action.action}`
                        ? "Resolving..."
                        : item.operator_action.label}
                    </button>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        </article>
      </section>
    </section>
  );
}
