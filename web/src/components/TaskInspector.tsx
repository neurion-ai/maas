import type { BoardTask, FilterOption, GoalTreeNode } from "../types";

const RECOVERABLE_REVIEW_STATES = new Set(["session_failed", "stale_session"]);

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
    return "Not recorded";
  }
  return new Date(value).toLocaleString();
}

function formatList(items?: string[] | null, limit = 4) {
  const values = (items ?? []).filter(Boolean);
  if (!values.length) {
    return "None";
  }
  if (values.length <= limit) {
    return values.join(", ");
  }
  return `${values.slice(0, limit).join(", ")} +${values.length - limit} more`;
}

function formatStatusLabel(value?: string | null) {
  if (!value) {
    return "Unknown";
  }
  return value.replaceAll("_", " ");
}

interface RepoPlanItem {
  synthesis_key: string;
  task_kind: string;
  title: string;
  source_label: string;
  paths: string[];
  command?: string | null;
  issue_key?: string | null;
  status?: string | null;
}

interface TaskInspectorProps {
  task: BoardTask | null;
  agentOptions?: FilterOption[];
  pendingActionKey?: string | null;
  goalPath?: GoalTreeNode[];
  siblingTasks?: BoardTask[];
  repoPlanItems?: RepoPlanItem[];
  onSelectSibling?: (taskId: string) => void;
  onReviewAction?: (taskId: string, decision: "approve" | "reject") => void;
  onAgentAction?: (agentId: string, action: "pause" | "resume") => void;
  onPriorityChange?: (taskId: string, priority: number) => void;
  onReassign?: (taskId: string, agentId: string) => void;
  onHalt?: (taskId: string) => void;
  onRecover?: (taskId: string) => void;
  onRecoverAndRequeue?: (taskId: string) => void;
  onMarkForReplan?: (taskId: string) => void;
  onFinishReplan?: (taskId: string) => void;
  onRunVerification?: (taskId: string) => void;
  onPrepareGitWorkspace?: (taskId: string) => void;
  onRefreshGitDiff?: (taskId: string) => void;
  onRetryLimitChange?: (taskId: string, autoRetryLimit: number | null) => void;
}

export function TaskInspector({
  task,
  agentOptions = [],
  pendingActionKey,
  goalPath = [],
  siblingTasks = [],
  repoPlanItems = [],
  onSelectSibling,
  onReviewAction,
  onAgentAction,
  onPriorityChange,
  onReassign,
  onHalt,
  onRecover,
  onRecoverAndRequeue,
  onMarkForReplan,
  onFinishReplan,
  onRunVerification,
  onPrepareGitWorkspace,
  onRefreshGitDiff,
  onRetryLimitChange
}: TaskInspectorProps) {
  if (!task) {
    return (
      <div className="empty-state empty-state--compact">
        <strong>No task selected.</strong>
        <p>Select a card to inspect the task, evidence, and available actions.</p>
      </div>
    );
  }

  const canReview = task.status === "review" && !!onReviewAction;
  const canToggleAgent = !!task.agent?.id && !!onAgentAction && (task.agent?.status === "running" || task.agent?.status === "paused");
  const canSteerTask = task.status !== "done" && task.status !== "cancelled";
  const canReassign = canSteerTask && task.status !== "in_progress" && !!onReassign && agentOptions.length > 0;
  const canReprioritize = canSteerTask && !!onPriorityChange;
  const canHalt = canSteerTask && !!onHalt;
  const canRecover =
    task.status === "blocked" && !!onRecover && RECOVERABLE_REVIEW_STATES.has(task.review_state ?? "");
  const canRecoverAndRequeue =
    task.status === "blocked" && !!onRecoverAndRequeue && RECOVERABLE_REVIEW_STATES.has(task.review_state ?? "");
  const canMarkForReplan =
    task.status !== "in_progress" &&
    task.status !== "done" &&
    task.status !== "cancelled" &&
    task.status !== "review" &&
    task.review_state !== "needs_replan" &&
    !!onMarkForReplan &&
    ((task.retry_count ?? 0) > 0 ||
      !!task.next_retry_at ||
      task.review_state === "retry_backoff" ||
      RECOVERABLE_REVIEW_STATES.has(task.review_state ?? ""));
  const canFinishReplan = task.status === "blocked" && task.review_state === "needs_replan" && !!onFinishReplan;
  const canRunVerification = !!task.has_verification_recipe && !!onRunVerification;
  const canPrepareGitWorkspace = !!task.git_workspace_supported && !task.git_workspace_prepared && !!onPrepareGitWorkspace;
  const canRefreshGitDiff = !!task.git_workspace_prepared && !!onRefreshGitDiff;
  const canSetRetryLimit = canSteerTask && !!onRetryLimitChange;
  const retryLimitOptions = Array.from(
    new Set(
      [null, 0, 1, 2, 3, 5, 10, task.auto_retry_limit ?? null].filter((value) => value === null || value >= 0)
    )
  ) as Array<number | null>;

  return (
    <div className="task-inspector-v2">
      <div className="task-inspector-v2__header">
        <div>
          <div className="task-inspector-v2__meta">
            <span className="status-pill">{formatPriority(task.priority)}</span>
            <span className="status-pill">{formatStatusLabel(task.status)}</span>
            {task.review_state ? <span className="status-pill">{formatStatusLabel(task.review_state)}</span> : null}
          </div>
          <h2>{task.title}</h2>
          <p>{task.description ?? "No task description captured yet."}</p>
        </div>
      </div>

      <div className="task-inspector-v2__summary">
        <div>
          <span>Assignee</span>
          <strong>{task.agent?.name ?? "Unassigned"}</strong>
        </div>
        <div>
          <span>Goal</span>
          <strong>{task.goal?.title ?? "Unlinked"}</strong>
        </div>
        <div>
          <span>Verification</span>
          <strong>{task.latest_verification_status ?? "Not run"}</strong>
        </div>
        <div>
          <span>Next retry</span>
          <strong>{task.next_retry_at ? formatTime(task.next_retry_at) : "Ready now"}</strong>
        </div>
      </div>

      <div className="task-inspector-v2__sections">
        <section className="inspector-panel">
          <div className="inspector-panel__header">
            <strong>Why this task exists</strong>
          </div>
          <div className="inspector-copy-stack">
            <p>{task.scheduler_summary ?? "No scheduler rationale recorded yet."}</p>
            {goalPath.length ? (
              <div className="inspector-breadcrumb" aria-label="Goal path">
                {goalPath.map((node, index) => (
                  <span key={node.goal_id} className="inspector-breadcrumb__item">
                    {index > 0 ? <span className="inspector-breadcrumb__sep">/</span> : null}
                    <span>{node.title}</span>
                  </span>
                ))}
              </div>
            ) : (
              <span className="muted-copy">No goal path is attached to this task.</span>
            )}
            {siblingTasks.length ? (
              <div className="inspector-flow__list">
                <span className="inspector-list-label">Related tasks</span>
                {siblingTasks.slice(0, 5).map((sibling) => (
                  <button
                    key={sibling.task_id}
                    type="button"
                    className="inspector-nav-row"
                    onClick={() => onSelectSibling?.(sibling.task_id)}
                  >
                    <span className="inspector-nav-row__copy">
                      <strong>{sibling.title}</strong>
                      <span>{formatStatusLabel(sibling.status)}</span>
                    </span>
                    <span className="inspector-nav-row__action">Open</span>
                  </button>
                ))}
              </div>
            ) : null}
          </div>
        </section>

        <section className="inspector-panel">
          <div className="inspector-panel__header">
            <strong>Repo scope and evidence</strong>
          </div>
          <div className="inspector-copy-stack">
            <p><strong>Paths:</strong> {formatList(task.scoped_paths)}</p>
            <p><strong>Validation:</strong> {formatList(task.validation_commands)}</p>
            <p>
              <strong>Git workspace:</strong>{" "}
              {task.git_workspace_prepared
                ? `${task.git_workspace_branch ?? "prepared"} · ${task.git_workspace_change_summary ?? "diff ready"}`
                : task.git_workspace_supported
                  ? "Supported, not prepared"
                  : "Not supported"}
            </p>
            {repoPlanItems.length ? (
              <div className="inspector-flow__list">
                <span className="inspector-list-label">Matching repo-plan items</span>
                {repoPlanItems.map((item) => (
                  <div key={item.synthesis_key} className="inspector-static-row">
                    <strong>{item.title}</strong>
                    <span>
                      {[item.issue_key, item.status, formatList(item.paths, 2)].filter(Boolean).join(" · ")}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <span className="muted-copy">No repo-plan items matched this task scope.</span>
            )}
          </div>
        </section>

        <section className="inspector-panel">
          <div className="inspector-panel__header">
            <strong>Steer this task</strong>
          </div>
          <div className="task-inspector-v2__actions">
            <div className="task-inspector-v2__buttons">
              {canReview ? (
                <>
                  <button
                    type="button"
                    className="task-action task-action--approve"
                    disabled={pendingActionKey === `review:${task.task_id}:approve` || pendingActionKey === `review:${task.task_id}:reject`}
                    onClick={() => onReviewAction?.(task.task_id, "approve")}
                  >
                    {pendingActionKey === `review:${task.task_id}:approve` ? "Working..." : "Approve"}
                  </button>
                  <button
                    type="button"
                    className="task-action task-action--reject"
                    disabled={pendingActionKey === `review:${task.task_id}:approve` || pendingActionKey === `review:${task.task_id}:reject`}
                    onClick={() => onReviewAction?.(task.task_id, "reject")}
                  >
                    {pendingActionKey === `review:${task.task_id}:reject` ? "Working..." : "Request changes"}
                  </button>
                </>
              ) : null}
              {canRecover ? (
                <button
                  type="button"
                  className="task-action task-action--secondary"
                  disabled={pendingActionKey === `recover:${task.task_id}`}
                  onClick={() => onRecover?.(task.task_id)}
                >
                  {pendingActionKey === `recover:${task.task_id}` ? "Working..." : "Recover"}
                </button>
              ) : null}
              {canRecoverAndRequeue ? (
                <button
                  type="button"
                  className="task-action task-action--approve"
                  disabled={pendingActionKey === `recover-and-requeue:${task.task_id}`}
                  onClick={() => onRecoverAndRequeue?.(task.task_id)}
                >
                  {pendingActionKey === `recover-and-requeue:${task.task_id}` ? "Working..." : "Recover + requeue"}
                </button>
              ) : null}
              {canMarkForReplan ? (
                <button
                  type="button"
                  className="task-action task-action--ghost"
                  disabled={pendingActionKey === `mark-for-replan:${task.task_id}`}
                  onClick={() => onMarkForReplan?.(task.task_id)}
                >
                  {pendingActionKey === `mark-for-replan:${task.task_id}` ? "Working..." : "Mark for replan"}
                </button>
              ) : null}
              {canFinishReplan ? (
                <button
                  type="button"
                  className="task-action task-action--approve"
                  disabled={pendingActionKey === `finish-replan:${task.task_id}`}
                  onClick={() => onFinishReplan?.(task.task_id)}
                >
                  {pendingActionKey === `finish-replan:${task.task_id}` ? "Working..." : "Finish replan"}
                </button>
              ) : null}
              {canRunVerification ? (
                <button
                  type="button"
                  className="task-action task-action--ghost"
                  disabled={pendingActionKey === `run-verification:${task.task_id}`}
                  onClick={() => onRunVerification?.(task.task_id)}
                >
                  {pendingActionKey === `run-verification:${task.task_id}` ? "Working..." : "Run verification"}
                </button>
              ) : null}
              {canPrepareGitWorkspace ? (
                <button
                  type="button"
                  className="task-action task-action--ghost"
                  disabled={pendingActionKey === `prepare-git-workspace:${task.task_id}`}
                  onClick={() => onPrepareGitWorkspace?.(task.task_id)}
                >
                  {pendingActionKey === `prepare-git-workspace:${task.task_id}` ? "Working..." : "Prepare git"}
                </button>
              ) : null}
              {canRefreshGitDiff ? (
                <button
                  type="button"
                  className="task-action task-action--ghost"
                  disabled={pendingActionKey === `refresh-git-diff:${task.task_id}`}
                  onClick={() => onRefreshGitDiff?.(task.task_id)}
                >
                  {pendingActionKey === `refresh-git-diff:${task.task_id}` ? "Working..." : "Refresh diff"}
                </button>
              ) : null}
              {canHalt ? (
                <button
                  type="button"
                  className="task-action task-action--reject"
                  disabled={pendingActionKey === `halt:${task.task_id}`}
                  onClick={() => onHalt?.(task.task_id)}
                >
                  {pendingActionKey === `halt:${task.task_id}` ? "Working..." : "Halt task"}
                </button>
              ) : null}
              {canToggleAgent && task.agent?.id ? (
                <button
                  type="button"
                  className="task-action task-action--secondary"
                  disabled={pendingActionKey === `agent:${task.agent.id}:${task.agent.status === "paused" ? "resume" : "pause"}`}
                  onClick={() => onAgentAction?.(task.agent!.id, task.agent?.status === "paused" ? "resume" : "pause")}
                >
                  {task.agent?.status === "paused" ? "Resume agent" : "Pause agent"}
                </button>
              ) : null}
            </div>

            <div className="task-inspector-v2__controls">
              {canReprioritize ? (
                <label className="field-control">
                  <span>Priority</span>
                  <select
                    value={String(task.priority)}
                    disabled={pendingActionKey === `reprioritize:${task.task_id}`}
                    onChange={(event) => onPriorityChange?.(task.task_id, Number(event.target.value))}
                  >
                    {[50, 75, 90, 100].map((value) => (
                      <option key={value} value={value}>
                        {value}
                      </option>
                    ))}
                  </select>
                </label>
              ) : null}
              {canReassign ? (
                <label className="field-control">
                  <span>Assign</span>
                  <select
                    value={task.agent?.id ?? ""}
                    disabled={pendingActionKey === `reassign:${task.task_id}`}
                    onChange={(event) => onReassign?.(task.task_id, event.target.value)}
                  >
                    <option value="" disabled>
                      Select agent
                    </option>
                    {agentOptions.map((option) => (
                      <option key={option.id} value={option.id}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
              ) : null}
              {canSetRetryLimit ? (
                <label className="field-control">
                  <span>Retry limit</span>
                  <select
                    value={task.auto_retry_limit == null ? "" : String(task.auto_retry_limit)}
                    disabled={pendingActionKey === `retry-limit:${task.task_id}`}
                    onChange={(event) =>
                      onRetryLimitChange?.(
                        task.task_id,
                        event.target.value === "" ? null : Number(event.target.value)
                      )
                    }
                  >
                    {retryLimitOptions.map((value) => (
                      <option key={value == null ? "default" : value} value={value == null ? "" : String(value)}>
                        {value == null ? "Project default" : value}
                      </option>
                    ))}
                  </select>
                </label>
              ) : null}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
