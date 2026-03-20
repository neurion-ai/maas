import { useEffect, useMemo, useState } from "react";
import { CodexIssueDetailPanel } from "../components/CodexIssueDetailPanel";
import { boardCounts, formatTimestamp, issueKeyMap, openBoardTasks, operatorQueueTasks, priorityLabel, resolvedBoardTasks, statusLabel } from "../lib/codexMvp";
import { fetchCodexIssueDetail, fetchFailures } from "../lib/controlRoomApi";
import { fetchBoard, markTaskForReplan, recoverAndRequeueTask, recoverTask, reviewTask } from "../lib/boardApi";
import { consumePendingTaskFocus } from "../lib/taskFocus";
import { useLivePulse } from "../lib/useLivePulse";
import type { BoardTask, CodexIssueDetailResponse, FailureItem } from "../types";

type IssuesTab = "queue" | "resolved";

function issueLabel(task: BoardTask, fallbackKeys: Map<string, string>) {
  return task.issue_key ?? fallbackKeys.get(task.task_id) ?? task.task_id;
}

export function CodexIssuesPage() {
  const [issuesTab, setIssuesTab] = useState<IssuesTab>("queue");
  const [tasks, setTasks] = useState<BoardTask[]>([]);
  const [resolved, setResolved] = useState<BoardTask[]>([]);
  const [failures, setFailures] = useState<FailureItem[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(() => consumePendingTaskFocus());
  const [detail, setDetail] = useState<CodexIssueDetailResponse | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pendingKey, setPendingKey] = useState<string | null>(null);
  const livePulse = useLivePulse();

  async function loadIssues(signal?: AbortSignal) {
    const [boardPayload, failuresPayload] = await Promise.all([fetchBoard({}, signal), fetchFailures()]);
    const openTasks = openBoardTasks(boardPayload.columns);
    const resolvedTasks = resolvedBoardTasks(boardPayload.columns);
    setTasks(openTasks);
    setResolved(resolvedTasks);
    setFailures(failuresPayload.recent);
    setSelectedTaskId((current) => current ?? openTasks[0]?.task_id ?? resolvedTasks[0]?.task_id ?? null);
  }

  useEffect(() => {
    const controller = new AbortController();
    void loadIssues(controller.signal).catch(() => setNotice("Issues refresh failed; showing the latest available state."));
    return () => controller.abort();
  }, [livePulse]);

  useEffect(() => {
    if (!selectedTaskId) {
      setDetail(null);
      return;
    }
    const controller = new AbortController();
    void fetchCodexIssueDetail(selectedTaskId, controller.signal, () => setNotice("Issue detail refresh fell back to cached data."))
      .then((payload) => setDetail(payload))
      .catch((error) => {
        if (!(error instanceof Error && error.name === "AbortError")) {
          setNotice("Issue detail refresh failed.");
        }
      });
    return () => controller.abort();
  }, [selectedTaskId, livePulse]);

  const keyMap = useMemo(() => issueKeyMap([{ key: "ready", title: "Ready", tasks }, { key: "done", title: "Done", tasks: resolved }]), [tasks, resolved]);
  const counts = useMemo(() => boardCounts([{ key: "ready", title: "Ready", tasks }, { key: "done", title: "Done", tasks: resolved }]), [tasks, resolved]);
  const queueItems = useMemo(() => operatorQueueTasks(tasks), [tasks]);
  const visibleItems = issuesTab === "queue" ? queueItems : resolved;
  const selectedTask = useMemo(() => {
    const allItems = [...queueItems, ...resolved];
    return allItems.find((task) => task.task_id === selectedTaskId) ?? visibleItems[0] ?? null;
  }, [queueItems, resolved, visibleItems, selectedTaskId]);

  useEffect(() => {
    if (!selectedTaskId) {
      return;
    }
    if (queueItems.some((task) => task.task_id === selectedTaskId)) {
      setIssuesTab((current) => (current === "queue" ? current : "queue"));
      return;
    }
    if (resolved.some((task) => task.task_id === selectedTaskId)) {
      setIssuesTab((current) => (current === "resolved" ? current : "resolved"));
      return;
    }
    setSelectedTaskId(visibleItems[0]?.task_id ?? null);
  }, [selectedTaskId, queueItems, resolved, visibleItems]);

  async function runAction(key: string, action: () => Promise<unknown>, message: string) {
    setPendingKey(key);
    setNotice(null);
    try {
      await action();
      await loadIssues();
      if (selectedTaskId) {
        setDetail(await fetchCodexIssueDetail(selectedTaskId));
      }
      setNotice(message);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Action failed.");
    } finally {
      setPendingKey(null);
    }
  }

  const detailActions = selectedTask ? (
    <>
      {selectedTask.status === "review" ? (
        <>
          <button
            type="button"
            className="codex-button codex-button--primary"
            disabled={pendingKey === `approve:${selectedTask.task_id}`}
            onClick={() =>
              void runAction(
                `approve:${selectedTask.task_id}`,
                () => reviewTask(selectedTask.task_id, "approve"),
                `Approved ${issueLabel(selectedTask, keyMap)}.`
              )
            }
          >
            {pendingKey === `approve:${selectedTask.task_id}` ? "Approving..." : "Approve"}
          </button>
          <button
            type="button"
            className="codex-button"
            disabled={pendingKey === `changes:${selectedTask.task_id}`}
            onClick={() =>
              void runAction(
                `changes:${selectedTask.task_id}`,
                () => reviewTask(selectedTask.task_id, "reject"),
                `Requested changes for ${issueLabel(selectedTask, keyMap)}.`
              )
            }
          >
            {pendingKey === `changes:${selectedTask.task_id}` ? "Updating..." : "Request changes"}
          </button>
        </>
      ) : null}
      {selectedTask.status === "blocked" ? (
        <>
          <button
            type="button"
            className="codex-button codex-button--primary"
            disabled={pendingKey === `recover:${selectedTask.task_id}`}
            onClick={() =>
              void runAction(
                `recover:${selectedTask.task_id}`,
                () => recoverTask(selectedTask.task_id),
                `Recovered ${issueLabel(selectedTask, keyMap)}.`
              )
            }
          >
            {pendingKey === `recover:${selectedTask.task_id}` ? "Recovering..." : "Recover"}
          </button>
          <button
            type="button"
            className="codex-button"
            disabled={pendingKey === `requeue:${selectedTask.task_id}`}
            onClick={() =>
              void runAction(
                `requeue:${selectedTask.task_id}`,
                () => recoverAndRequeueTask(selectedTask.task_id),
                `Recovered and requeued ${issueLabel(selectedTask, keyMap)}.`
              )
            }
          >
            {pendingKey === `requeue:${selectedTask.task_id}` ? "Requeueing..." : "Recover + requeue"}
          </button>
          <button
            type="button"
            className="codex-button"
            disabled={pendingKey === `replan:${selectedTask.task_id}`}
            onClick={() =>
              void runAction(
                `replan:${selectedTask.task_id}`,
                () => markTaskForReplan(selectedTask.task_id),
                `Marked ${issueLabel(selectedTask, keyMap)} for replan.`
              )
            }
          >
            {pendingKey === `replan:${selectedTask.task_id}` ? "Updating..." : "Mark for replan"}
          </button>
        </>
      ) : null}
    </>
  ) : null;

  return (
    <section className="codex-page">
      <header className="codex-page__header">
        <div>
          <span className="codex-kicker">Issues</span>
          <h1>Operator-facing exceptions, decisions, and resolved history</h1>
          <p>Queue shows issues that need judgment. Resolved keeps the full searchable trail instead of hiding it in a Done lane.</p>
        </div>
      </header>

      <div className="codex-toolbar">
        <div className="codex-toggle-group">
          <button type="button" className={issuesTab === "queue" ? "is-active" : ""} onClick={() => setIssuesTab("queue")}>
            Queue
          </button>
          <button type="button" className={issuesTab === "resolved" ? "is-active" : ""} onClick={() => setIssuesTab("resolved")}>
            Resolved
          </button>
        </div>
        <div className="codex-chip-row">
          <span className="codex-chip">{counts.review} review</span>
          <span className="codex-chip">{counts.blocked} blocked</span>
          <span className="codex-chip">{failures.length} recent failures</span>
          <span className="codex-chip">{counts.done} resolved</span>
        </div>
      </div>

      {notice ? <div className="codex-banner">{notice}</div> : null}

      <div className="codex-work-layout">
        <div className="codex-list-panel codex-panel">
          {visibleItems.map((task) => (
            <button
              key={task.task_id}
              type="button"
              className={`codex-work-row ${selectedTaskId === task.task_id ? "is-selected" : ""}`}
              onClick={() => setSelectedTaskId(task.task_id)}
            >
              <div className="codex-work-row__header">
                <div>
                  <strong>
                    {issueLabel(task, keyMap)} · {task.title}
                  </strong>
                  <span>{task.goal?.title ?? "Unlinked goal"}</span>
                </div>
                <span>{formatTimestamp(task.latest_failure_at ?? task.latest_verification_at ?? null)}</span>
              </div>
              <div className="codex-work-row__meta">
                <span>{task.agent?.name ?? "Unassigned"}</span>
                <span>{statusLabel(task.status, task.review_state)}</span>
                <span>{priorityLabel(task.priority)}</span>
              </div>
              <p>{task.description ?? "No issue summary recorded."}</p>
            </button>
          ))}
          {!visibleItems.length ? <div className="codex-empty-copy">No issues in this view.</div> : null}
        </div>

        <CodexIssueDetailPanel
          task={selectedTask}
          detail={detail}
          issueKeyMap={keyMap}
          actions={detailActions}
          onSelectTask={setSelectedTaskId}
        />
      </div>
    </section>
  );
}
