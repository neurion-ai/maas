import { useEffect, useMemo, useState } from "react";
import { OperatorLoopPanel } from "../components/OperatorLoopPanel";
import { CodexIssueScopeToolbar } from "../components/CodexIssueScopeToolbar";
import { CodexIssueDetailPanel } from "../components/CodexIssueDetailPanel";
import { boardCounts, formatTimestamp, issueKeyMap, priorityLabel, statusLabel } from "../lib/codexMvp";
import { filterCodexTasks, useCodexIssueScope, useCodexScopeOptions } from "../lib/codexIssueScopes";
import { batchReviewIssues, fetchCodexIssueDetail, fetchCodexIssueIndex } from "../lib/controlRoomApi";
import type { OperatorLoopItem, OperatorWorkflowState } from "../lib/operatorLoop";
import {
  haltTask,
  markTaskForReplan,
  prepareTaskGitWorkspace,
  recoverAndRequeueTask,
  recoverTask,
  refreshTaskGitDiff,
  reviewTask,
  runTaskVerification,
} from "../lib/boardApi";
import { getSelectedProjectId } from "../lib/projectScope";
import { consumePendingTaskFocus } from "../lib/taskFocus";
import { useLivePulse } from "../lib/useLivePulse";
import type { BoardTask, CodexIssueDetailResponse, CodexIssueIndexResponse } from "../types";

type IssuesTab = "queue" | "resolved";
type ViewTarget = "command" | "work" | "issues" | "agents" | "runs" | "system" | "projects";

function issueLabel(task: BoardTask, fallbackKeys: Map<string, string>) {
  return task.issue_key ?? fallbackKeys.get(task.task_id) ?? task.task_id;
}

function nextVisibleTaskId(currentTaskId: string | null, openTasks: BoardTask[], resolvedTasks: BoardTask[]) {
  if (currentTaskId && [...openTasks, ...resolvedTasks].some((task) => task.task_id === currentTaskId)) {
    return currentTaskId;
  }
  return openTasks[0]?.task_id ?? resolvedTasks[0]?.task_id ?? null;
}

export function CodexIssuesPage({
  onNavigate,
  operatorWorkflow,
  operatorWorkflowWarning,
  onOpenOperatorItem,
}: {
  onNavigate: (view: ViewTarget) => void;
  operatorWorkflow: OperatorWorkflowState | null;
  operatorWorkflowWarning?: string | null;
  onOpenOperatorItem: (item: OperatorLoopItem) => void;
}) {
  const [issuesTab, setIssuesTab] = useState<IssuesTab>("queue");
  const [issueIndex, setIssueIndex] = useState<CodexIssueIndexResponse | null>(null);
  const [tasks, setTasks] = useState<BoardTask[]>([]);
  const [resolved, setResolved] = useState<BoardTask[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(() => consumePendingTaskFocus());
  const [detail, setDetail] = useState<CodexIssueDetailResponse | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pendingKey, setPendingKey] = useState<string | null>(null);
  const [packetSelection, setPacketSelection] = useState<Record<string, string[]>>({});
  const livePulse = useLivePulse();
  const { scope, savedScopes, setScope, applySavedScope, saveCurrentScope, deleteSavedScope, resetScope } =
    useCodexIssueScope(getSelectedProjectId(), "issues");

  async function loadIssues(signal?: AbortSignal) {
    const payload = await fetchCodexIssueIndex(signal);
    const openTasks = [
      ...payload.queue.review.items,
      ...payload.queue.blocked_failures.items,
      ...payload.queue.blocked_dependencies.items,
    ];
    const resolvedTasks = payload.resolved;
    setIssueIndex(payload);
    setTasks(openTasks);
    setResolved(resolvedTasks);
    const nextTaskId = nextVisibleTaskId(selectedTaskId, openTasks, resolvedTasks);
    setSelectedTaskId(nextTaskId);
    return { openTasks, resolvedTasks, nextTaskId };
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
  const scopeOptions = useCodexScopeOptions([...tasks, ...resolved]);
  const filteredReviewItems = useMemo(
    () => filterCodexTasks(issueIndex?.queue.review.items ?? [], scope),
    [issueIndex, scope]
  );
  const filteredBlockedFailureItems = useMemo(
    () => filterCodexTasks(issueIndex?.queue.blocked_failures.items ?? [], scope),
    [issueIndex, scope]
  );
  const filteredBlockedDependencyItems = useMemo(
    () => filterCodexTasks(issueIndex?.queue.blocked_dependencies.items ?? [], scope),
    [issueIndex, scope]
  );
  const filteredOpenTasks = useMemo(
    () => [...filteredReviewItems, ...filteredBlockedFailureItems, ...filteredBlockedDependencyItems],
    [filteredReviewItems, filteredBlockedFailureItems, filteredBlockedDependencyItems]
  );
  const filteredResolved = useMemo(
    () => filterCodexTasks(resolved, { ...scope, queueFilter: "all" }),
    [resolved, scope]
  );
  const counts = useMemo(
    () => boardCounts([{ key: "ready", title: "Ready", tasks: filteredOpenTasks }, { key: "done", title: "Done", tasks: filteredResolved }]),
    [filteredOpenTasks, filteredResolved]
  );
  const filteredBatchReviewPackets = useMemo(() => {
    const visibleTaskIds = new Set(filteredReviewItems.map((task) => task.task_id));
    return (issueIndex?.queue.review.batch_review?.packets ?? [])
      .map((packet) => {
        const packetItems = (packet.items ?? []).filter((item) => visibleTaskIds.has(item.task_id));
        const eligibleTaskIds = packetItems.map((item) => item.task_id);
        return {
          ...packet,
          items: packetItems,
          eligible_task_ids: eligibleTaskIds,
          eligible_count: eligibleTaskIds.length,
        };
      })
      .filter((packet) => (packet.eligible_count ?? 0) > 0);
  }, [filteredReviewItems, issueIndex]);
  const visibleItems = issuesTab === "queue" ? filteredOpenTasks : filteredResolved;
  const selectedTask = useMemo(() => {
    const allItems = [...filteredOpenTasks, ...filteredResolved];
    return allItems.find((task) => task.task_id === selectedTaskId) ?? visibleItems[0] ?? null;
  }, [filteredOpenTasks, filteredResolved, visibleItems, selectedTaskId]);

  useEffect(() => {
    if (!selectedTaskId) {
      return;
    }
    if (filteredOpenTasks.some((task) => task.task_id === selectedTaskId)) {
      setIssuesTab((current) => (current === "queue" ? current : "queue"));
      return;
    }
    if (filteredResolved.some((task) => task.task_id === selectedTaskId)) {
      setIssuesTab((current) => (current === "resolved" ? current : "resolved"));
      return;
    }
    setSelectedTaskId(visibleItems[0]?.task_id ?? null);
  }, [selectedTaskId, filteredOpenTasks, filteredResolved, visibleItems]);

  useEffect(() => {
    setPacketSelection((current) => {
      const next = { ...current };
      const activePacketKeys = new Set(filteredBatchReviewPackets.map((packet) => packet.packet_key));
      for (const packet of filteredBatchReviewPackets) {
        const validIds = new Set((packet.eligible_task_ids ?? []).filter(Boolean));
        if (packet.packet_key in current) {
          next[packet.packet_key] = (current[packet.packet_key] ?? []).filter((taskId) => validIds.has(taskId));
          continue;
        }
        next[packet.packet_key] = [...validIds];
      }
      for (const key of Object.keys(next)) {
        if (!activePacketKeys.has(key)) {
          delete next[key];
        }
      }
      return next;
    });
  }, [filteredBatchReviewPackets]);

  function selectedPacketTaskIds(packetKey: string, eligibleTaskIds: string[]) {
    return (packetSelection[packetKey] ?? eligibleTaskIds).filter((taskId) => eligibleTaskIds.includes(taskId));
  }

  function togglePacketTask(packetKey: string, taskId: string) {
    setPacketSelection((current) => {
      const existing = current[packetKey] ?? [];
      const next = existing.includes(taskId)
        ? existing.filter((candidate) => candidate !== taskId)
        : [...existing, taskId];
      return { ...current, [packetKey]: next };
    });
  }

  async function runAction(key: string, action: () => Promise<unknown>, message: string) {
    setPendingKey(key);
    setNotice(null);
    try {
      await action();
      setDetail(null);
      const refresh = await loadIssues();
      if (refresh.nextTaskId) {
        setDetail(await fetchCodexIssueDetail(refresh.nextTaskId));
      }
      setNotice(message);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Action failed.");
    } finally {
      setPendingKey(null);
    }
  }

  async function handleBatchReview(
    packetKey: string,
    packetTaskIds: string[],
    decision: "approve" | "reject",
    packetTitle?: string | null
  ) {
    if (!packetTaskIds.length) {
      return;
    }
    setPendingKey(`batch-review:${decision}:${packetKey}`);
    setNotice(null);
    try {
      await batchReviewIssues(packetTaskIds, decision);
      const refresh = await loadIssues();
      if (refresh.nextTaskId) {
        setDetail(await fetchCodexIssueDetail(refresh.nextTaskId));
      }
      setNotice(
        `${decision === "approve" ? "Approved" : "Requested changes for"} ${packetTaskIds.length} issue${packetTaskIds.length === 1 ? "" : "s"} from ${packetTitle ?? "the low-risk review packet"}.`
      );
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Batch review failed.");
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
      {selectedTask.status === "in_progress" ? (
        <button
          type="button"
          className="codex-button"
          disabled={pendingKey === `halt:${selectedTask.task_id}`}
          onClick={() =>
            void runAction(
              `halt:${selectedTask.task_id}`,
              () => haltTask(selectedTask.task_id),
              `Stopped ${issueLabel(selectedTask, keyMap)} and cancelled its active run.`
            )
          }
        >
          {pendingKey === `halt:${selectedTask.task_id}` ? "Stopping..." : "Stop issue"}
        </button>
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

      {notice ? <div className="codex-banner">{notice}</div> : null}

      <OperatorLoopPanel
        workflow={operatorWorkflow}
        compact
        maxItems={3}
        title="Review and recovery desk"
        description="Issues owns operator decisions and blocked-work recovery. Use Command for loop posture and Runs for live-session evidence."
        onSelectItem={onOpenOperatorItem}
        warning={operatorWorkflowWarning}
        footer={
          <div className="codex-detail-actions">
            <button type="button" className="codex-button codex-button--primary" onClick={() => onNavigate("command")}>
              Open Command
            </button>
            <button type="button" className="codex-button" onClick={() => onNavigate("runs")}>
              Open Runs
            </button>
          </div>
        }
      />

      <div className="codex-work-layout">
        <div className="codex-work-main">
          <CodexIssueScopeToolbar
            leading={
              <div className="codex-toggle-group">
                <button type="button" className={issuesTab === "queue" ? "is-active" : ""} onClick={() => setIssuesTab("queue")}>
                  Queue
                </button>
                <button type="button" className={issuesTab === "resolved" ? "is-active" : ""} onClick={() => setIssuesTab("resolved")}>
                  Resolved
                </button>
              </div>
            }
            scope={scope}
            savedScopes={savedScopes}
            agentOptions={scopeOptions.agents}
            goalOptions={scopeOptions.goals}
            onScopeChange={setScope}
            onReset={resetScope}
            onApplySaved={applySavedScope}
            onSaveCurrent={saveCurrentScope}
            onDeleteSaved={deleteSavedScope}
          />

          <div className="codex-chip-row">
            <span className="codex-chip">{filteredReviewItems.length} review</span>
            <span className="codex-chip">{filteredBlockedFailureItems.length + filteredBlockedDependencyItems.length} blocked</span>
            <span className="codex-chip">{filteredBlockedFailureItems.length} recent failures</span>
            <span className="codex-chip">{counts.done} resolved</span>
          </div>

        <div className="codex-list-panel codex-panel">
          {issuesTab === "queue" ? (
            <>
              <section className="codex-list-section">
                <div className="codex-section-heading">
                  <strong>Review queue</strong>
                  <span>{filteredReviewItems.length}</span>
                </div>
                {filteredBatchReviewPackets.length ? (
                  <div className="codex-run-list">
                    {filteredBatchReviewPackets.map((packet) => (
                      <div key={packet.packet_key} className="codex-output-item">
                        <strong>{packet.title ?? "Low-risk review packet"}</strong>
                        <span>{packet.summary ?? "Eligible review issues can be decided together."}</span>
                        <span>
                          {(packet.eligible_count ?? packet.eligible_task_ids?.length ?? 0)} issue
                          {(packet.eligible_count ?? packet.eligible_task_ids?.length ?? 0) === 1 ? "" : "s"}
                        </span>
                        <span>
                          {packet.packet_scope_label ?? "Shared scope"}
                          {packet.auto_approve_eligible_count ? ` · ${packet.auto_approve_eligible_count} auto-approve eligible` : ""}
                        </span>
                        <div className="codex-run-list codex-run-list--compact">
                          {(packet.items ?? []).map((item) => {
                            const selectedIds = selectedPacketTaskIds(packet.packet_key, packet.eligible_task_ids ?? []);
                            const checked = selectedIds.includes(item.task_id);
                            return (
                              <div key={item.task_id} className="codex-packet-item">
                                <input
                                  type="checkbox"
                                  checked={checked}
                                  onChange={() => togglePacketTask(packet.packet_key, item.task_id)}
                                />
                                <button
                                  type="button"
                                  className="codex-packet-item__content"
                                  onClick={() => setSelectedTaskId(item.task_id)}
                                >
                                  <strong>{item.issue_key ?? item.task_id} · {item.title}</strong>
                                  <span>
                                    {item.goal_title ?? "Unlinked goal"}
                                    {item.latest_verification_at ? ` · ${formatTimestamp(item.latest_verification_at)}` : ""}
                                  </span>
                                  <span>
                                    {priorityLabel(item.priority)}
                                    {item.auto_approve_eligible ? " · auto-approve eligible" : ""}
                                  </span>
                                </button>
                              </div>
                            );
                          })}
                        </div>
                        <div className="codex-detail-actions">
                          <button
                            type="button"
                            className="codex-button"
                            onClick={() =>
                              setPacketSelection((current) => ({
                                ...current,
                                [packet.packet_key]: [...(packet.eligible_task_ids ?? [])],
                              }))
                            }
                          >
                            Select all
                          </button>
                          <button
                            type="button"
                            className="codex-button"
                            onClick={() =>
                              setPacketSelection((current) => ({
                                ...current,
                                [packet.packet_key]: [],
                              }))
                            }
                          >
                            Clear
                          </button>
                          <button
                            type="button"
                            className="codex-button codex-button--primary"
                            disabled={
                              pendingKey === `batch-review:approve:${packet.packet_key}` ||
                              selectedPacketTaskIds(packet.packet_key, packet.eligible_task_ids ?? []).length === 0
                            }
                            onClick={() =>
                              void handleBatchReview(
                                packet.packet_key,
                                selectedPacketTaskIds(packet.packet_key, packet.eligible_task_ids ?? []),
                                "approve",
                                packet.title ?? "the low-risk review packet"
                              )
                            }
                          >
                            {pendingKey === `batch-review:approve:${packet.packet_key}`
                              ? "Approving..."
                              : `Approve ${selectedPacketTaskIds(packet.packet_key, packet.eligible_task_ids ?? []).length}`}
                          </button>
                          <button
                            type="button"
                            className="codex-button"
                            disabled={
                              pendingKey === `batch-review:reject:${packet.packet_key}` ||
                              selectedPacketTaskIds(packet.packet_key, packet.eligible_task_ids ?? []).length === 0
                            }
                            onClick={() =>
                              void handleBatchReview(
                                packet.packet_key,
                                selectedPacketTaskIds(packet.packet_key, packet.eligible_task_ids ?? []),
                                "reject",
                                packet.title ?? "the low-risk review packet"
                              )
                            }
                          >
                            {pendingKey === `batch-review:reject:${packet.packet_key}`
                              ? "Updating..."
                              : "Request changes"}
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="codex-empty-copy">{issueIndex?.queue.review.batch_review?.summary ?? "No current review items meet the low-risk batch-review rules."}</div>
                )}
                {filteredReviewItems.length ? (
                  filteredReviewItems.map((task) => (
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
                        <span>{formatTimestamp(task.latest_verification_at ?? null)}</span>
                      </div>
                      <div className="codex-work-row__meta">
                        <span>{task.agent?.name ?? "Unassigned"}</span>
                        <span>{priorityLabel(task.priority)}</span>
                        <span>{task.validation_commands?.length ?? 0} checks</span>
                      </div>
                      <p>{task.description ?? "No issue summary recorded."}</p>
                    </button>
                  ))
                ) : (
                  <div className="codex-empty-copy">Nothing is waiting for operator review right now.</div>
                )}
              </section>

              <section className="codex-list-section">
                <div className="codex-section-heading">
                  <strong>{issueIndex?.queue.blocked_failures.title ?? "Blocked by failures"}</strong>
                  <span>{filteredBlockedFailureItems.length}</span>
                </div>
                {filteredBlockedFailureItems.length ? (
                  filteredBlockedFailureItems.map((task) => (
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
                        <span>{formatTimestamp(task.latest_failure_at ?? null)}</span>
                      </div>
                      <div className="codex-work-row__meta">
                        <span>{task.agent?.name ?? "Unassigned"}</span>
                        <span>{statusLabel(task.status, task.review_state)}</span>
                        <span>{task.failure_count ?? 0} failures</span>
                      </div>
                      <p>{task.description ?? "No issue summary recorded."}</p>
                    </button>
                  ))
                ) : (
                  <div className="codex-empty-copy">No failure-driven issues are blocked right now.</div>
                )}
              </section>

              <section className="codex-list-section">
                <div className="codex-section-heading">
                  <strong>{issueIndex?.queue.blocked_dependencies.title ?? "Blocked by dependencies or operator state"}</strong>
                  <span>{filteredBlockedDependencyItems.length}</span>
                </div>
                {filteredBlockedDependencyItems.length ? (
                  filteredBlockedDependencyItems.map((task) => (
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
                        <span>{formatTimestamp(task.latest_failure_at ?? null)}</span>
                      </div>
                      <div className="codex-work-row__meta">
                        <span>{task.agent?.name ?? "Unassigned"}</span>
                        <span>{statusLabel(task.status, task.review_state)}</span>
                        <span>{priorityLabel(task.priority)}</span>
                      </div>
                      <p>{task.description ?? "No issue summary recorded."}</p>
                    </button>
                  ))
                ) : (
                  <div className="codex-empty-copy">No dependency-driven issues are blocked right now.</div>
                )}
              </section>
            </>
          ) : (
            <>
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
            </>
          )}
        </div>
        </div>

        <CodexIssueDetailPanel
          task={selectedTask}
          detail={detail}
          issueKeyMap={keyMap}
          actions={detailActions}
          pendingActionKey={pendingKey}
          onRunVerification={
            selectedTask
              ? (taskId) =>
                  void runAction(
                    `run-verification:${taskId}`,
                    () => runTaskVerification(taskId),
                    `Ran verification for ${keyMap.get(taskId) ?? taskId}.`
                  )
              : undefined
          }
          onPrepareGitWorkspace={
            selectedTask
              ? (taskId) =>
                  void runAction(
                    `git-workspace:${taskId}`,
                    () => prepareTaskGitWorkspace(taskId),
                    `Prepared a git workspace for ${keyMap.get(taskId) ?? taskId}.`
                  )
              : undefined
          }
          onRefreshGitDiff={
            selectedTask
              ? (taskId) =>
                  void runAction(
                    `git-workspace:${taskId}`,
                    () => refreshTaskGitDiff(taskId),
                    `Refreshed git diff evidence for ${keyMap.get(taskId) ?? taskId}.`
                  )
              : undefined
          }
          onSelectTask={setSelectedTaskId}
          onNavigate={onNavigate}
        />
      </div>
    </section>
  );
}
