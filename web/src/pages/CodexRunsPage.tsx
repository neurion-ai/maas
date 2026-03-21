import { useEffect, useMemo, useState } from "react";
import { CodexRunDetailCard } from "../components/CodexRunDetailCard";
import { cancelCodexRun, fetchCodexRunDetail, fetchCodexRuns, fetchPortfolio, runOrchestratorPass, updateProjectProviderCapacity } from "../lib/controlRoomApi";
import { getSelectedProjectId } from "../lib/projectScope";
import { consumePendingRunFocus } from "../lib/runFocus";
import { setPendingTaskFocus } from "../lib/taskFocus";
import { useLivePulse } from "../lib/useLivePulse";
import { recoverAndRequeueTask } from "../lib/boardApi";
import { describeLaunchPosture, formatTimestamp } from "../lib/codexMvp";
import type { CodexRunDetailResponse, CodexRunListItem, PortfolioProject } from "../types";

type ViewTarget = "command" | "work" | "issues" | "agents" | "runs" | "system" | "projects";
type RunFilter = "all" | "active" | "failed" | "timed_out" | "completed" | "cancelled";

const RUN_CONTROL_MIN_PENDING_MS = 900;

function issueLabel(run: CodexRunListItem | CodexRunDetailResponse) {
  return run.issue_key ?? run.task_id ?? run.session_id;
}

export function CodexRunsPage({ onNavigate }: { onNavigate: (view: ViewTarget) => void }) {
  const [runs, setRuns] = useState<CodexRunListItem[]>([]);
  const [project, setProject] = useState<PortfolioProject | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(() => consumePendingRunFocus());
  const [selectedRunDetail, setSelectedRunDetail] = useState<CodexRunDetailResponse | null>(null);
  const [statusFilter, setStatusFilter] = useState<RunFilter>("all");
  const [search, setSearch] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [pendingKey, setPendingKey] = useState<string | null>(null);
  const livePulse = useLivePulse();

  async function loadRuns(signal?: AbortSignal) {
    const [runsPayload, portfolioPayload] = await Promise.all([
      fetchCodexRuns(
        {
          limit: 200,
          status: statusFilter === "all" ? undefined : statusFilter,
          search: search.trim() || undefined,
        },
        signal
      ),
      fetchPortfolio(),
    ]);
    setRuns(runsPayload.items);
    setSelectedRunId((current) => current ?? runsPayload.items[0]?.session_id ?? null);
    const selectedProjectId = getSelectedProjectId();
    setProject(
      portfolioPayload.projects.find((item) => item.project_id === selectedProjectId) ??
        portfolioPayload.projects[0] ??
        null
    );
    return runsPayload.items;
  }

  useEffect(() => {
    const controller = new AbortController();
    void loadRuns(controller.signal).catch(() => setNotice("Runs refresh failed; showing the latest available execution state."));
    return () => controller.abort();
  }, [livePulse, statusFilter, search]);

  useEffect(() => {
    if (!selectedRunId) {
      setSelectedRunDetail(null);
      return;
    }
    const controller = new AbortController();
    void fetchCodexRunDetail(selectedRunId, controller.signal)
      .then((payload) => setSelectedRunDetail(payload))
      .catch((error) => {
        if (!(error instanceof Error && error.name === "AbortError")) {
          setSelectedRunDetail(null);
          setNotice("Run detail refresh failed.");
        }
      });
    return () => controller.abort();
  }, [selectedRunId, livePulse]);

  useEffect(() => {
    if (!selectedRunId) {
      return;
    }
    if (!runs.some((run) => run.session_id === selectedRunId)) {
      setSelectedRunId(runs[0]?.session_id ?? null);
    }
  }, [runs, selectedRunId]);

  const summary = useMemo(
    () => ({
      active: runs.filter((run) => run.status === "active").length,
      stale: runs.filter((run) => run.is_stale).length,
      failed: runs.filter((run) => run.status === "failed" || run.status === "timed_out").length,
      completed: runs.filter((run) => run.status === "completed").length,
    }),
    [runs]
  );
  const launchPosture = useMemo(() => describeLaunchPosture(project), [project]);

  async function holdPendingState(startedAt: number) {
    const remaining = RUN_CONTROL_MIN_PENDING_MS - (Date.now() - startedAt);
    if (remaining > 0) {
      await new Promise((resolve) => window.setTimeout(resolve, remaining));
    }
  }

  async function handleRunCycle() {
    const startedAt = Date.now();
    setPendingKey("run");
    setNotice(null);
    try {
      const result = await runOrchestratorPass(6, 4, true);
      await loadRuns();
      await holdPendingState(startedAt);
      await loadRuns();
      const started = (result.provider_jobs_processed ?? 0) + (result.provider_jobs_dispatched ?? 0);
      setNotice(`Cycle complete. ${started} run${started === 1 ? "" : "s"} started or dispatched.`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Run cycle failed.");
    } finally {
      setPendingKey(null);
    }
  }

  async function updateLaunchMode(queueMode: "running" | "draining" | "paused", successMessage: string, pending: string) {
    if (!project) {
      return;
    }
    const startedAt = Date.now();
    setPendingKey(pending);
    setNotice(null);
    try {
      await updateProjectProviderCapacity(project.project_id, {
        queue_mode: queueMode,
        max_running_jobs: project.provider_capacity.max_running_jobs,
        preferred_provider_id: project.provider_capacity.preferred_provider_id ?? null,
      });
      await loadRuns();
      await holdPendingState(startedAt);
      await loadRuns();
      setNotice(successMessage);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Could not update launch posture.");
    } finally {
      setPendingKey(null);
    }
  }

  async function handleCancelRun() {
    if (!selectedRunDetail?.is_live) {
      return;
    }
    setPendingKey(`cancel:${selectedRunDetail.session_id}`);
    setNotice(null);
    try {
      await cancelCodexRun(selectedRunDetail.session_id);
      await loadRuns();
      if (selectedRunDetail.session_id) {
        setSelectedRunDetail(await fetchCodexRunDetail(selectedRunDetail.session_id).catch(() => null));
      }
      setNotice(`Stopped ${issueLabel(selectedRunDetail)}.`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Run cancel failed.");
    } finally {
      setPendingKey(null);
    }
  }

  async function handleReplayIssue() {
    if (!selectedRunDetail?.task_id) {
      return;
    }
    setPendingKey(`replay:${selectedRunDetail.session_id}`);
    setNotice(null);
    try {
      await recoverAndRequeueTask(selectedRunDetail.task_id);
      await loadRuns();
      setNotice(`Recovered and requeued ${issueLabel(selectedRunDetail)} from its last failed run.`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Replay failed.");
    } finally {
      setPendingKey(null);
    }
  }

  const selectedRunActions = selectedRunDetail ? (
    <>
      {selectedRunDetail.task_id ? (
        <button
          type="button"
          className="codex-button codex-button--primary"
          onClick={() => {
            setPendingTaskFocus(selectedRunDetail.task_id!);
            onNavigate("work");
          }}
        >
          Open issue
        </button>
      ) : null}
      {selectedRunDetail.is_live ? (
        <button
          type="button"
          className="codex-button"
          disabled={pendingKey === `cancel:${selectedRunDetail.session_id}`}
          onClick={() => void handleCancelRun()}
        >
          {pendingKey === `cancel:${selectedRunDetail.session_id}` ? "Stopping..." : "Stop issue"}
        </button>
      ) : null}
      {selectedRunDetail.task_id && selectedRunDetail.task_status === "blocked" ? (
        <button
          type="button"
          className="codex-button"
          disabled={pendingKey === `replay:${selectedRunDetail.session_id}`}
          onClick={() => void handleReplayIssue()}
        >
          {pendingKey === `replay:${selectedRunDetail.session_id}` ? "Requeueing..." : "Recover + requeue"}
        </button>
      ) : null}
    </>
  ) : null;

  return (
    <section className="codex-page">
      <header className="codex-page__header">
        <div>
          <span className="codex-kicker">Runs</span>
          <h1>Inspect live Codex execution, trace failures, and stop work safely</h1>
          <p>Runs are the truth of what actually happened. Use this page for active sessions, stale-run diagnosis, and replay from failed work.</p>
        </div>
        <div className="codex-page__actions">
          <button type="button" className="codex-button codex-button--primary" disabled={pendingKey !== null} onClick={() => void handleRunCycle()}>
            {pendingKey === "run" ? "Running..." : "Run next cycle"}
          </button>
          {launchPosture.mode === "running" ? (
            <>
              <button type="button" className="codex-button" disabled={pendingKey !== null || !project} onClick={() => void updateLaunchMode("draining", "Queue is draining. Running and queued work can finish, but new launches are held back.", "drain")}>
                {pendingKey === "drain" ? "Draining..." : "Drain queue"}
              </button>
              <button type="button" className="codex-button" disabled={pendingKey !== null || !project} onClick={() => void updateLaunchMode("paused", "Paused new Codex launches. Active runs will finish.", "pause")}>
                {pendingKey === "pause" ? "Pausing..." : "Pause launches"}
              </button>
            </>
          ) : (
            <button type="button" className="codex-button" disabled={pendingKey !== null || !project} onClick={() => void updateLaunchMode("running", "Resumed Codex launches.", "resume")}>
              {pendingKey === "resume" ? "Resuming..." : "Resume launches"}
            </button>
          )}
        </div>
      </header>

      {notice ? <div className="codex-banner">{notice}</div> : null}

      <div className="codex-metric-grid">
        <article className="codex-panel codex-stat">
          <strong>{runs.length}</strong>
          <span>Loaded runs</span>
          <p>Current project execution history.</p>
        </article>
        <article className="codex-panel codex-stat">
          <strong>{summary.active}</strong>
          <span>Active runs</span>
          <p>{summary.stale} stale enough to inspect</p>
        </article>
        <article className="codex-panel codex-stat">
          <strong>{summary.failed}</strong>
          <span>Failed runs</span>
          <p>Timed out or failed sessions.</p>
        </article>
        <article className="codex-panel codex-stat">
          <strong>{launchPosture.label}</strong>
          <span>Launch posture</span>
          <p>{launchPosture.summary}</p>
        </article>
      </div>

      <div className="codex-work-layout">
        <div className="codex-work-main">
          <div className="codex-scope-toolbar codex-panel">
            <div className="codex-toggle-group">
              {(["all", "active", "failed", "timed_out", "completed", "cancelled"] as const).map((value) => (
                <button key={value} type="button" className={statusFilter === value ? "is-active" : ""} onClick={() => setStatusFilter(value)}>
                  {value.replaceAll("_", " ")}
                </button>
              ))}
            </div>
            <input
              className="codex-input"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search by issue, agent, run id, or status message"
            />
          </div>

          <div className="codex-list-panel codex-panel">
            {runs.length ? (
              runs.map((run) => (
                <button
                  key={run.session_id}
                  type="button"
                  className={`codex-work-row ${selectedRunId === run.session_id ? "is-selected" : ""}`}
                  onClick={() => setSelectedRunId(run.session_id)}
                >
                  <div className="codex-work-row__header">
                    <div>
                      <strong>{issueLabel(run)} · {run.task_title ?? "Unlinked run"}</strong>
                      <span>{run.goal_title ?? "No linked goal"}</span>
                    </div>
                    <span>{formatTimestamp(run.ended_at ?? run.started_at)}</span>
                  </div>
                  <div className="codex-work-row__meta">
                    <span>{run.agent_name ?? run.agent_id ?? "Unknown agent"}</span>
                    <span>{run.provider_type.replaceAll("_", " ")}</span>
                    <span>{run.status.replaceAll("_", " ")}</span>
                    {run.is_stale ? <span>stale</span> : null}
                  </div>
                  <p>{run.diagnostic_summary ?? run.status_message ?? "No runtime summary recorded."}</p>
                  <div className="codex-work-row__chips">
                    <span className="codex-chip">{run.progress_pct ?? 0}% progress</span>
                    <span className="codex-chip">{run.artifact_count} artifacts</span>
                    <span className="codex-chip">{run.failure_count} failures</span>
                  </div>
                </button>
              ))
            ) : (
              <div className="codex-empty-copy">No runs match the current filter.</div>
            )}
          </div>
        </div>

        <aside className="codex-detail-panel codex-panel">
          <CodexRunDetailCard run={selectedRunDetail} actions={selectedRunActions} />
        </aside>
      </div>
    </section>
  );
}
