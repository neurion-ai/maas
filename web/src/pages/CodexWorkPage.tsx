import { useEffect, useMemo, useState } from "react";
import { CodexIssueScopeToolbar } from "../components/CodexIssueScopeToolbar";
import { CodexIssueDetailPanel } from "../components/CodexIssueDetailPanel";
import { boardCounts, describeLaunchPosture, formatTimestamp, issueKeyMap, nextActionLabel, openBoardTasks, priorityLabel, resolvedBoardTasks, statusLabel } from "../lib/codexMvp";
import { filterCodexTasks, useCodexIssueScope, useCodexScopeOptions } from "../lib/codexIssueScopes";
import { fetchCodexIssueDetail, fetchPortfolio, runOrchestratorPass, updateProjectProviderCapacity } from "../lib/controlRoomApi";
import { fetchBoard, haltTask, markTaskForReplan, recoverAndRequeueTask, recoverTask, reviewTask } from "../lib/boardApi";
import { getSelectedProjectId } from "../lib/projectScope";
import { consumePendingTaskFocus } from "../lib/taskFocus";
import { useThrottledLivePulse } from "../lib/useLivePulse";
import type { BoardTask, CodexIssueDetailResponse, PortfolioProject } from "../types";

type WorkViewMode = "list" | "board";
type ViewTarget = "command" | "work" | "issues" | "agents" | "runs" | "system" | "projects";

const RUN_CONTROL_MIN_PENDING_MS = 900;

function laneTitle(key: "planned" | "ready" | "assigned" | "in_progress" | "review" | "blocked") {
  if (key === "planned") {
    return "Planned";
  }
  if (key === "ready") {
    return "Ready";
  }
  if (key === "assigned") {
    return "Assigned";
  }
  return key === "in_progress" ? "In progress" : key === "review" ? "Review" : "Blocked";
}

function issueLabel(task: BoardTask, fallbackKeys: Map<string, string>) {
  return task.issue_key ?? fallbackKeys.get(task.task_id) ?? task.task_id;
}

function nextVisibleTaskId(currentTaskId: string | null, openTasks: BoardTask[], doneTasks: BoardTask[]) {
  if (currentTaskId && [...openTasks, ...doneTasks].some((task) => task.task_id === currentTaskId)) {
    return currentTaskId;
  }
  return openTasks[0]?.task_id ?? doneTasks[0]?.task_id ?? null;
}

export function CodexWorkPage({ onNavigate }: { onNavigate: (view: ViewTarget) => void }) {
  const [viewMode, setViewMode] = useState<WorkViewMode>("board");
  const [tasks, setTasks] = useState<BoardTask[]>([]);
  const [resolvedTasks, setResolvedTasks] = useState<BoardTask[]>([]);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(() => consumePendingTaskFocus());
  const [detail, setDetail] = useState<CodexIssueDetailResponse | null>(null);
  const [project, setProject] = useState<PortfolioProject | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pendingKey, setPendingKey] = useState<string | null>(null);
  const livePulse = useThrottledLivePulse(1200);
  const { scope, savedScopes, setScope, applySavedScope, saveCurrentScope, deleteSavedScope, resetScope } =
    useCodexIssueScope(getSelectedProjectId(), "work");

  async function loadBoard(signal?: AbortSignal) {
    const [payload, portfolioPayload] = await Promise.all([fetchBoard({}, signal), fetchPortfolio()]);
    const openTasks = openBoardTasks(payload.columns);
    const doneTasks = resolvedBoardTasks(payload.columns);
    setTasks(openTasks);
    setResolvedTasks(doneTasks);
    const nextTaskId = nextVisibleTaskId(selectedTaskId, openTasks, doneTasks);
    setSelectedTaskId(nextTaskId);
    const selectedProjectId = getSelectedProjectId();
    setProject(
      portfolioPayload.projects.find((item) => item.project_id === selectedProjectId) ??
        portfolioPayload.projects[0] ??
        null
    );
    return { openTasks, doneTasks, nextTaskId };
  }

  useEffect(() => {
    const controller = new AbortController();
    void loadBoard(controller.signal).catch(() => {
      setNotice("Work refresh failed; showing the latest available data.");
    });
    return () => controller.abort();
  }, [livePulse]);

  useEffect(() => {
    if (!selectedTaskId) {
      setDetail(null);
      return;
    }
    setDetail(null);
    const controller = new AbortController();
    void fetchCodexIssueDetail(selectedTaskId, controller.signal, () => setNotice("Issue detail refresh fell back to cached data."))
      .then((payload) => setDetail(payload))
      .catch((error) => {
        if (!(error instanceof Error && error.name === "AbortError")) {
          setNotice("Issue detail refresh failed.");
        }
      });
    return () => controller.abort();
  }, [selectedTaskId]);

  useEffect(() => {
    if (!selectedTaskId) {
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

  const keyMap = useMemo(
    () => issueKeyMap([{ key: "ready", title: "Ready", tasks }, { key: "done", title: "Done", tasks: resolvedTasks }]),
    [tasks, resolvedTasks]
  );
  const scopeOptions = useCodexScopeOptions([...tasks, ...resolvedTasks]);
  const filteredTasks = useMemo(() => filterCodexTasks(tasks, scope), [tasks, scope]);
  const filteredResolved = useMemo(
    () => filterCodexTasks(resolvedTasks, { ...scope, queueFilter: "all" }),
    [resolvedTasks, scope]
  );
  const counts = useMemo(
    () => boardCounts([{ key: "ready", title: "Ready", tasks: filteredTasks }, { key: "done", title: "Done", tasks: filteredResolved }]),
    [filteredTasks, filteredResolved]
  );
  const selectedTask = useMemo(
    () =>
      [...filteredTasks, ...filteredResolved].find((task) => task.task_id === selectedTaskId) ??
      filteredTasks[0] ??
      filteredResolved[0] ??
      null,
    [filteredTasks, filteredResolved, selectedTaskId]
  );
  useEffect(() => {
    if (!selectedTaskId && (filteredTasks.length || filteredResolved.length)) {
      setSelectedTaskId(filteredTasks[0]?.task_id ?? filteredResolved[0]?.task_id ?? null);
      return;
    }
    if (
      selectedTaskId &&
      !filteredTasks.some((task) => task.task_id === selectedTaskId) &&
      !filteredResolved.some((task) => task.task_id === selectedTaskId)
    ) {
      setSelectedTaskId(filteredTasks[0]?.task_id ?? filteredResolved[0]?.task_id ?? null);
    }
  }, [filteredTasks, filteredResolved, selectedTaskId]);
  const launchPosture = useMemo(() => describeLaunchPosture(project), [project]);

  const grouped = useMemo(
    () => ({
      planned: filteredTasks.filter((task) => task.status === "planned"),
      ready: filteredTasks.filter((task) => task.status === "ready"),
      assigned: filteredTasks.filter((task) => task.status === "assigned"),
      in_progress: filteredTasks.filter((task) => task.status === "in_progress"),
      review: filteredTasks.filter((task) => task.status === "review"),
      blocked: filteredTasks.filter((task) => task.status === "blocked"),
    }),
    [filteredTasks]
  );
  const visibleLanes = useMemo(
    () =>
      (["planned", "ready", "assigned", "in_progress", "review", "blocked"] as const).filter(
        (lane) => grouped[lane].length > 0 || ["ready", "assigned", "in_progress", "review", "blocked"].includes(lane)
      ),
    [grouped]
  );

  async function holdPendingState(startedAt: number) {
    const remaining = RUN_CONTROL_MIN_PENDING_MS - (Date.now() - startedAt);
    if (remaining > 0) {
      await new Promise((resolve) => window.setTimeout(resolve, remaining));
    }
  }

  async function runAction(key: string, action: () => Promise<unknown>, message: string) {
    setPendingKey(key);
    setNotice(null);
    try {
      await action();
      setDetail(null);
      const refresh = await loadBoard();
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

  function renderWorkRow(task: BoardTask) {
    const selected = selectedTaskId === task.task_id;
    return (
      <button
        key={task.task_id}
        type="button"
        className={`codex-work-row ${selected ? "is-selected" : ""}`}
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
        <p>{task.description ?? nextActionLabel(task)}</p>
        <div className="codex-work-row__chips">
          <span className="codex-chip">{task.failure_count ?? 0} failures</span>
          <span className="codex-chip">{task.scoped_paths?.length ?? 0} paths</span>
          <span className="codex-chip">{task.validation_commands?.length ?? 0} checks</span>
        </div>
      </button>
    );
  }

  async function handleRunCycle() {
    const startedAt = Date.now();
    setPendingKey("run-cycle");
    setNotice(null);
    try {
      const result = await runOrchestratorPass(6, 4, true);
      await loadBoard();
      if (selectedTaskId) {
        setDetail(await fetchCodexIssueDetail(selectedTaskId));
      }
      await holdPendingState(startedAt);
      await loadBoard();
      if (selectedTaskId) {
        setDetail(await fetchCodexIssueDetail(selectedTaskId));
      }
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

  async function handleDrain() {
    if (!project) {
      return;
    }
    const startedAt = Date.now();
    setPendingKey("drain-cycle");
    setNotice(null);
    try {
      await updateProjectProviderCapacity(project.project_id, {
        queue_mode: "draining",
        max_running_jobs: project.provider_capacity.max_running_jobs,
        preferred_provider_id: project.provider_capacity.preferred_provider_id ?? null,
      });
      await loadBoard();
      await holdPendingState(startedAt);
      await loadBoard();
      setNotice("Queue is draining. Running and queued work can finish, but new assigned issues will not launch.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Drain failed.");
    } finally {
      setPendingKey(null);
    }
  }

  async function handlePause() {
    if (!project) {
      return;
    }
    const startedAt = Date.now();
    setPendingKey("pause-cycle");
    setNotice(null);
    try {
      await updateProjectProviderCapacity(project.project_id, {
        queue_mode: "paused",
        max_running_jobs: project.provider_capacity.max_running_jobs,
        preferred_provider_id: project.provider_capacity.preferred_provider_id ?? null,
      });
      await loadBoard();
      await holdPendingState(startedAt);
      await loadBoard();
      setNotice("Paused new Codex launches. Active runs will continue until they finish.");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Pause failed.");
    } finally {
      setPendingKey(null);
    }
  }

  async function handleResumeCycle() {
    if (!project) {
      return;
    }
    const startedAt = Date.now();
    setPendingKey("resume-cycle");
    setNotice(null);
    try {
      await updateProjectProviderCapacity(project.project_id, {
        queue_mode: "running",
        max_running_jobs: project.provider_capacity.max_running_jobs,
        preferred_provider_id: project.provider_capacity.preferred_provider_id ?? null,
      });
      const result = await runOrchestratorPass(6, 4, true);
      await loadBoard();
      if (selectedTaskId) {
        setDetail(await fetchCodexIssueDetail(selectedTaskId));
      }
      await holdPendingState(startedAt);
      await loadBoard();
      if (selectedTaskId) {
        setDetail(await fetchCodexIssueDetail(selectedTaskId));
      }
      const started = (result.provider_jobs_processed ?? 0) + (result.provider_jobs_dispatched ?? 0);
      setNotice(`Resumed execution. ${started} run${started === 1 ? "" : "s"} started.`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Resume failed.");
    } finally {
      setPendingKey(null);
    }
  }

  return (
    <section className="codex-page">
      <header className="codex-page__header">
        <div>
          <span className="codex-kicker">Work</span>
          <h1>Same issues in list or board form</h1>
          <p>The board only shows active flow. Resolved work stays searchable instead of filling a giant Done lane.</p>
        </div>
        <div className="codex-page__actions">
          <button type="button" className="codex-button codex-button--primary" disabled={pendingKey !== null} onClick={() => void handleRunCycle()}>
            {pendingKey === "run-cycle" ? "Running..." : "Run next cycle"}
          </button>
          {launchPosture.mode === "running" ? (
            <>
              <button type="button" className="codex-button" disabled={pendingKey !== null || !project} onClick={() => void handleDrain()}>
                {pendingKey === "drain-cycle" ? "Draining..." : "Drain queue"}
              </button>
              <button type="button" className="codex-button" disabled={pendingKey !== null || !project} onClick={() => void handlePause()}>
                {pendingKey === "pause-cycle" ? "Pausing..." : "Pause launches"}
              </button>
            </>
          ) : launchPosture.mode === "draining" ? (
            <>
              <button type="button" className="codex-button" disabled={pendingKey !== null || !project} onClick={() => void handleResumeCycle()}>
                {pendingKey === "resume-cycle" ? "Resuming..." : "Resume launches"}
              </button>
              <button type="button" className="codex-button" disabled={pendingKey !== null || !project} onClick={() => void handlePause()}>
                {pendingKey === "pause-cycle" ? "Pausing..." : "Pause launches"}
              </button>
            </>
          ) : (
            <button type="button" className="codex-button" disabled={pendingKey !== null || !project} onClick={() => void handleResumeCycle()}>
              {pendingKey === "resume-cycle" ? "Resuming..." : "Resume launches"}
            </button>
          )}
        </div>
      </header>

      {notice ? <div className="codex-banner">{notice}</div> : null}

      <div className="codex-work-layout">
        <div className="codex-work-main">
          <CodexIssueScopeToolbar
            leading={
              <div className="codex-toggle-group">
                <button type="button" className={viewMode === "list" ? "is-active" : ""} onClick={() => setViewMode("list")}>
                  List
                </button>
                <button type="button" className={viewMode === "board" ? "is-active" : ""} onClick={() => setViewMode("board")}>
                  Board
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
            <span className="codex-chip">{counts.planned} planned</span>
            <span className="codex-chip">{counts.ready} ready</span>
            <span className="codex-chip">{counts.assigned} assigned</span>
            <span className="codex-chip">{counts.in_progress} in progress</span>
            <span className="codex-chip">{counts.review} review</span>
            <span className="codex-chip">{counts.blocked} blocked</span>
            <span className="codex-chip">{counts.done} resolved</span>
            <span className="codex-chip">{launchPosture.label}</span>
          </div>

          {viewMode === "list" ? (
            <div className="codex-list-panel codex-panel">
              {filteredTasks.length ? filteredTasks.map((task) => renderWorkRow(task)) : <div className="codex-empty-copy">No open issues match the current view.</div>}
            </div>
          ) : (
            <div className="codex-board-grid">
              {visibleLanes.map((lane) => (
                <section key={lane} className="codex-board-lane codex-panel">
                  <div className="codex-board-lane__header">
                    <strong>{laneTitle(lane)}</strong>
                    <span>{grouped[lane].length}</span>
                  </div>
                  <div className="codex-board-lane__body">
                    {grouped[lane].length ? (
                      grouped[lane].map((task) => (
                        <button
                          key={task.task_id}
                          type="button"
                          className={`codex-board-card ${selectedTaskId === task.task_id ? "is-selected" : ""}`}
                          onClick={() => setSelectedTaskId(task.task_id)}
                        >
                          <div className="codex-board-card__meta">
                            <span>{issueLabel(task, keyMap)}</span>
                            <span>{priorityLabel(task.priority)}</span>
                          </div>
                          <strong>{task.title}</strong>
                          <span>{task.agent?.name ?? "Unassigned"}</span>
                          <span>{statusLabel(task.status, task.review_state)}</span>
                        </button>
                      ))
                    ) : (
                      <div className="codex-empty-copy">No issues in this lane.</div>
                    )}
                  </div>
                </section>
              ))}
            </div>
          )}

          <div className="codex-resolved-strip codex-panel">
            <div className="codex-panel__header">
              <div>
                <span className="codex-kicker">Resolved</span>
                <h2>{counts.done} resolved issues</h2>
              </div>
            </div>
            <div className="codex-resolved-list">
              {filteredResolved.slice(0, 8).map((task) => (
                <button key={task.task_id} type="button" className="codex-resolved-item" onClick={() => setSelectedTaskId(task.task_id)}>
                  <strong>{issueLabel(task, keyMap)}</strong>
                  <span>{task.title}</span>
                  <span>{task.agent?.name ?? "MAAS"}</span>
                </button>
              ))}
              {!filteredResolved.length ? <div className="codex-empty-copy">No resolved issues match the current view.</div> : null}
            </div>
          </div>
        </div>

        <CodexIssueDetailPanel
          task={selectedTask}
          detail={detail}
          issueKeyMap={keyMap}
          actions={detailActions}
          onSelectTask={setSelectedTaskId}
          onNavigate={onNavigate}
        />
      </div>
    </section>
  );
}
