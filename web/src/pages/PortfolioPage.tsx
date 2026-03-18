import { useEffect, useState } from "react";
import { StatCard } from "../components/StatCard";
import {
  fetchPortfolio,
  processProviderJob,
  runOrchestratorPass,
  updateEscalationStatus,
  updateProjectProviderCapacity,
  updateProjectRiskPolicy
} from "../lib/controlRoomApi";
import { setSelectedProjectId } from "../lib/projectScope";
import { useLivePulse } from "../lib/useLivePulse";
import type { OrchestratorRunResponse, PortfolioResponse } from "../types";

function healthLabel(health: string) {
  if (health === "critical") {
    return "Critical";
  }
  if (health === "warn") {
    return "Needs attention";
  }
  if (health === "archived") {
    return "Archived";
  }
  return "Healthy";
}

export function PortfolioPage() {
  const [portfolio, setPortfolio] = useState<PortfolioResponse | null>(null);
  const [orchestratorResult, setOrchestratorResult] = useState<OrchestratorRunResponse | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [runningOrchestrator, setRunningOrchestrator] = useState(false);
  const [pendingActionKey, setPendingActionKey] = useState<string | null>(null);
  const [riskDrafts, setRiskDrafts] = useState<Record<string, { priorityThreshold: number; sensitivePaths: string }>>({});
  const livePulse = useLivePulse();

  useEffect(() => {
    let mounted = true;

    async function loadPortfolio() {
      try {
        const payload = await fetchPortfolio();
        if (mounted) {
          setPortfolio(payload);
          setRiskDrafts((current) => {
            const next = { ...current };
            payload.projects.forEach((project) => {
              if (!next[project.project_id]) {
                next[project.project_id] = {
                  priorityThreshold: project.risk_policy.priority_threshold,
                  sensitivePaths: project.risk_policy.sensitive_path_prefixes.join(", ")
                };
              }
            });
            return next;
          });
        }
      } catch {
        if (mounted) {
          setNotice("Portfolio view is unavailable; keeping the last project list snapshot.");
        }
      }
    }

    void loadPortfolio();
    return () => {
      mounted = false;
    };
  }, [livePulse]);

  async function handleRunOrchestrator() {
    setRunningOrchestrator(true);
    setNotice(null);
    try {
      const payload = await runOrchestratorPass(4, 2);
      setOrchestratorResult(payload);
      setPortfolio(await fetchPortfolio());
      setNotice(
        `Orchestrator assigned ${payload.assigned_count} tasks, processed ${payload.provider_jobs_processed} queued jobs, and touched ${payload.project_runs.length} projects.`
      );
    } catch {
      setNotice("Orchestrator pass failed; keeping the current portfolio snapshot.");
    } finally {
      setRunningOrchestrator(false);
    }
  }

  async function handleEscalationAction(escalationId: string, action: "approve" | "reject") {
    const actionKey = `escalation:${escalationId}:${action}`;
    setPendingActionKey(actionKey);
    setNotice(null);
    try {
      await updateEscalationStatus(escalationId, action);
      setPortfolio(await fetchPortfolio());
      setNotice(`Escalation ${action}d.`);
    } catch {
      setNotice("Escalation action failed; keeping the current command-center snapshot.");
    } finally {
      setPendingActionKey(null);
    }
  }

  async function handleProcessProviderJob(jobId: string) {
    const actionKey = `provider-job:${jobId}:process`;
    setPendingActionKey(actionKey);
    setNotice(null);
    try {
      const payload = await processProviderJob(jobId);
      setPortfolio(await fetchPortfolio());
      setNotice(`Processed provider job ${jobId} with status ${payload.status}.`);
    } catch {
      setNotice("Provider job processing failed; keeping the current command-center snapshot.");
    } finally {
      setPendingActionKey(null);
    }
  }

  async function handleUpdateProviderCapacity(
    projectId: string,
    queueMode: "running" | "draining" | "paused",
    maxRunningJobs: number
  ) {
    const actionKey = `provider-capacity:${projectId}`;
    setPendingActionKey(actionKey);
    setNotice(null);
    try {
      await updateProjectProviderCapacity(projectId, {
        queue_mode: queueMode,
        max_running_jobs: maxRunningJobs
      });
      setPortfolio(await fetchPortfolio());
      setNotice(`Updated provider capacity for ${projectId}.`);
    } catch {
      setNotice("Provider capacity update failed; keeping the current command-center snapshot.");
    } finally {
      setPendingActionKey(null);
    }
  }

  async function handleUpdateRiskPolicy(projectId: string) {
    const actionKey = `risk-policy:${projectId}`;
    const draft = riskDrafts[projectId];
    if (!draft) {
      return;
    }
    setPendingActionKey(actionKey);
    setNotice(null);
    try {
      const sensitivePathPrefixes = draft.sensitivePaths
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean);
      await updateProjectRiskPolicy(projectId, {
        priority_threshold: draft.priorityThreshold,
        sensitive_path_prefixes: sensitivePathPrefixes
      });
      setPortfolio(await fetchPortfolio());
      setNotice(`Updated risk routing policy for ${projectId}.`);
    } catch {
      setNotice("Risk routing policy update failed; keeping the current command-center snapshot.");
    } finally {
      setPendingActionKey(null);
    }
  }

  return (
    <section className="control-page">
      <header className="page-hero">
        <div>
          <span className="eyebrow">Portfolio</span>
          <h1>Cross-project portfolio</h1>
          <p>Track which projects are blocked, noisy, or runtime-unready without switching the active scope first.</p>
        </div>
        <div className="page-hero__actions">
          <button
            type="button"
            className="task-action task-action--secondary"
            disabled={runningOrchestrator}
            onClick={() => void handleRunOrchestrator()}
          >
            {runningOrchestrator ? "Running orchestrator..." : "Run orchestrator pass"}
          </button>
          {notice ? <p className="page-hero__notice">{notice}</p> : null}
        </div>
      </header>

      <section className="stats-grid">
        <StatCard label="Active projects" value={portfolio?.summary.active_projects ?? 0} />
        <StatCard label="Projects with issues" value={portfolio?.summary.projects_with_issues ?? 0} tone="warn" />
        <StatCard label="Open alerts" value={portfolio?.summary.open_alerts ?? 0} tone="warn" />
        <StatCard label="Blocked tasks" value={portfolio?.summary.blocked_tasks ?? 0} tone="warn" />
        <StatCard label="Active sessions" value={portfolio?.summary.active_sessions ?? 0} />
        <StatCard label="Recovery pressure" value={portfolio?.summary.recovery_pressure ?? 0} tone="warn" />
        <StatCard label="Open escalations" value={portfolio?.summary.open_escalations ?? 0} tone="warn" />
        <StatCard label="Queued jobs" value={portfolio?.summary.queued_provider_jobs ?? 0} />
      </section>

      <article className="data-panel">
        <header className="data-panel__header">
          <div>
            <h2>Project health</h2>
            <p>Each row rolls up alerts, blocked work, recovery pressure, and provider readiness for that project.</p>
          </div>
          {orchestratorResult ? (
            <span className="status-chip">
              Last pass: {orchestratorResult.provider_jobs_processed} jobs, {orchestratorResult.assigned_count} assignments
            </span>
          ) : null}
        </header>
        <div className="data-list">
          {portfolio?.projects.map((project) => (
            <div key={project.project_id} className="data-list__item">
              <div>
                <strong>{project.name}</strong>
                <p>{project.description || project.project_type}</p>
                <p>
                  {healthLabel(project.health)} · {project.onboarding_mode ?? "greenfield"} · {project.state}
                </p>
                <p>
                  {project.blocked_tasks} blocked · {project.open_alerts} open alerts · {project.active_sessions} active sessions ·{" "}
                  {project.open_quarantine_entries + project.dead_letter_entries + project.repeated_failure_tasks} recovery signals
                </p>
                <p>
                  Providers ready {project.provider_readiness.ready}/{project.provider_readiness.total}
                  {project.provider_readiness.issues ? ` · ${project.provider_readiness.issues} issues` : ""}
                  {project.provider_readiness.unknown ? ` · ${project.provider_readiness.unknown} unknown` : ""}
                </p>
                <p>
                  Fair share {project.scheduler_policy.fair_share_weight} · max active sessions {project.scheduler_policy.max_active_sessions}
                  {project.at_scheduler_capacity ? " · at scheduler capacity" : ""}
                </p>
                <p>
                  Queue {project.provider_capacity.queue_mode} · max running jobs {project.provider_capacity.max_running_jobs} ·{" "}
                  {project.provider_capacity.running_jobs} running / {project.provider_capacity.queued_jobs} queued
                  {project.provider_capacity.at_capacity ? " · at capacity" : ""}
                </p>
                <p>
                  Risk routing at priority {project.risk_policy.priority_threshold}
                  {project.risk_policy.sensitive_path_prefixes.length
                    ? ` · sensitive paths: ${project.risk_policy.sensitive_path_prefixes.join(", ")}`
                    : " · no sensitive path prefixes"}
                </p>
              </div>
              <div className="data-list__meta">
                <span>{project.task_count} tasks</span>
                <span>{project.agent_count} agents</span>
                <label className="task-inline-control">
                  <span>Queue mode</span>
                  <select
                    value={project.provider_capacity.queue_mode}
                    disabled={pendingActionKey === `provider-capacity:${project.project_id}`}
                    onChange={(event) =>
                      void handleUpdateProviderCapacity(
                        project.project_id,
                        event.target.value as "running" | "draining" | "paused",
                        project.provider_capacity.max_running_jobs
                      )
                    }
                  >
                    <option value="running">running</option>
                    <option value="draining">draining</option>
                    <option value="paused">paused</option>
                  </select>
                </label>
                <label className="task-inline-control">
                  <span>Max jobs</span>
                  <select
                    value={String(project.provider_capacity.max_running_jobs)}
                    disabled={pendingActionKey === `provider-capacity:${project.project_id}`}
                    onChange={(event) =>
                      void handleUpdateProviderCapacity(
                        project.project_id,
                        project.provider_capacity.queue_mode,
                        Number(event.target.value)
                      )
                    }
                  >
                    {[0, 1, 2, 3, 4, 5].map((value) => (
                      <option key={value} value={value}>
                        {value}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="task-inline-control">
                  <span>Risk threshold</span>
                  <select
                    value={String(riskDrafts[project.project_id]?.priorityThreshold ?? project.risk_policy.priority_threshold)}
                    disabled={pendingActionKey === `risk-policy:${project.project_id}`}
                    onChange={(event) =>
                      setRiskDrafts((current) => ({
                        ...current,
                        [project.project_id]: {
                          priorityThreshold: Number(event.target.value),
                          sensitivePaths:
                            current[project.project_id]?.sensitivePaths ??
                            project.risk_policy.sensitive_path_prefixes.join(", ")
                        }
                      }))
                    }
                  >
                    {[70, 80, 90, 95, 100, 101].map((value) => (
                      <option key={value} value={value}>
                        {value === 101 ? "disabled" : value}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="task-inline-control">
                  <span>Sensitive paths</span>
                  <input
                    type="text"
                    value={riskDrafts[project.project_id]?.sensitivePaths ?? project.risk_policy.sensitive_path_prefixes.join(", ")}
                    disabled={pendingActionKey === `risk-policy:${project.project_id}`}
                    onChange={(event) =>
                      setRiskDrafts((current) => ({
                        ...current,
                        [project.project_id]: {
                          priorityThreshold:
                            current[project.project_id]?.priorityThreshold ?? project.risk_policy.priority_threshold,
                          sensitivePaths: event.target.value
                        }
                      }))
                    }
                  />
                </label>
                <button
                  type="button"
                  className="task-action task-action--secondary"
                  disabled={pendingActionKey === `risk-policy:${project.project_id}`}
                  onClick={() => void handleUpdateRiskPolicy(project.project_id)}
                >
                  Save risk policy
                </button>
                <button
                  type="button"
                  className="task-action task-action--secondary"
                  disabled={project.state === "archived"}
                  onClick={() => setSelectedProjectId(project.project_id)}
                >
                  Open project
                </button>
              </div>
            </div>
          ))}
        </div>
      </article>

      <section className="data-grid data-grid--two">
        <article className="data-panel">
          <header className="data-panel__header">
            <div>
              <h2>Open escalations</h2>
              <p>Approve or reject risky actions across every active project from one queue.</p>
            </div>
          </header>
          <div className="data-list">
            {(portfolio?.command_center.open_escalations ?? []).length ? (
              portfolio?.command_center.open_escalations.map((item) => (
                <div key={item.escalation_id} className="data-list__item">
                  <div>
                    <strong>{item.project_name ?? item.project_id}</strong>
                    <p>
                      {item.action_type} · {item.resource_type} {item.resource_id}
                    </p>
                    <p>{item.reason || "No escalation reason provided."}</p>
                  </div>
                  <div className="data-list__meta">
                    <button
                      type="button"
                      className="task-action task-action--approve"
                      disabled={pendingActionKey === `escalation:${item.escalation_id}:approve`}
                      onClick={() => void handleEscalationAction(item.escalation_id, "approve")}
                    >
                      {pendingActionKey === `escalation:${item.escalation_id}:approve` ? "Approving..." : "Approve"}
                    </button>
                    <button
                      type="button"
                      className="task-action task-action--reject"
                      disabled={pendingActionKey === `escalation:${item.escalation_id}:reject`}
                      onClick={() => void handleEscalationAction(item.escalation_id, "reject")}
                    >
                      {pendingActionKey === `escalation:${item.escalation_id}:reject` ? "Rejecting..." : "Reject"}
                    </button>
                  </div>
                </div>
              ))
            ) : (
              <p className="empty-state">No open escalations.</p>
            )}
          </div>
        </article>

        <article className="data-panel">
          <header className="data-panel__header">
            <div>
              <h2>Provider backlog</h2>
              <p>Process queued provider work without switching into each project.</p>
            </div>
          </header>
          <div className="data-list">
            {(portfolio?.command_center.queued_provider_jobs ?? []).length ? (
              portfolio?.command_center.queued_provider_jobs.map((job) => (
                <div key={job.job_id} className="data-list__item">
                  <div>
                    <strong>{job.project_name ?? job.project_id}</strong>
                    <p>{job.provider_id} · {job.title ?? job.task_id}</p>
                    <p>{job.status} · queued {new Date(job.created_at).toLocaleString()}</p>
                  </div>
                  <div className="data-list__meta">
                    <button
                      type="button"
                      className="task-action task-action--secondary"
                      disabled={job.status !== "queued" || pendingActionKey === `provider-job:${job.job_id}:process`}
                      onClick={() => void handleProcessProviderJob(job.job_id)}
                    >
                      {pendingActionKey === `provider-job:${job.job_id}:process` ? "Processing..." : "Process now"}
                    </button>
                  </div>
                </div>
              ))
            ) : (
              <p className="empty-state">No queued provider jobs.</p>
            )}
          </div>
        </article>
      </section>

      <section className="data-grid data-grid--two">
        <article className="data-panel">
          <header className="data-panel__header">
            <div>
              <h2>Urgent alerts</h2>
              <p>Critical and warning alerts across projects, ordered by urgency.</p>
            </div>
          </header>
          <div className="data-list">
            {(portfolio?.command_center.urgent_alerts ?? []).length ? (
              portfolio?.command_center.urgent_alerts.map((alert) => (
                <div key={alert.alert_id} className="data-list__item">
                  <div>
                    <strong>{alert.project_name ?? alert.project_id}</strong>
                    <p>{alert.title}</p>
                    <p>{alert.description}</p>
                  </div>
                  <div className="data-list__meta">
                    <span>{alert.severity}</span>
                    <button
                      type="button"
                      className="task-action task-action--secondary"
                      onClick={() => setSelectedProjectId(alert.project_id ?? "")}
                    >
                      Open project
                    </button>
                  </div>
                </div>
              ))
            ) : (
              <p className="empty-state">No urgent alerts.</p>
            )}
          </div>
        </article>

        <article className="data-panel">
          <header className="data-panel__header">
            <div>
              <h2>Recovery hotlist</h2>
              <p>Retry-exhausted work that still needs operator attention.</p>
            </div>
          </header>
          <div className="data-list">
            {(portfolio?.command_center.open_dead_letter_entries ?? []).length ? (
              portfolio?.command_center.open_dead_letter_entries.map((entry) => (
                <div key={entry.dlq_id} className="data-list__item">
                  <div>
                    <strong>{entry.project_name ?? entry.project_id}</strong>
                    <p>{entry.title}</p>
                    <p>
                      {entry.reason} · retry count {entry.retry_count ?? 0}
                    </p>
                  </div>
                  <div className="data-list__meta">
                    <button
                      type="button"
                      className="task-action task-action--secondary"
                      onClick={() => setSelectedProjectId(entry.project_id)}
                    >
                      Open project
                    </button>
                  </div>
                </div>
              ))
            ) : (
              <p className="empty-state">No open DLQ entries.</p>
            )}
          </div>
        </article>
      </section>
    </section>
  );
}
