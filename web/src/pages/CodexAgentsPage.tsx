import { useEffect, useState } from "react";
import { assignNextTask, fetchAgentRoster, fetchCodexAgentDetail, fetchCodexRunDetail, recoverAgent } from "../lib/controlRoomApi";
import { formatTimestamp } from "../lib/codexMvp";
import { setPendingTaskFocus } from "../lib/taskFocus";
import { useLivePulse } from "../lib/useLivePulse";
import type { AgentRosterEntry, CodexAgentDetailResponse, CodexRunDetailResponse } from "../types";

type ViewTarget = "work" | "issues" | "agents" | "system" | "projects" | "command";

function formatHeartbeat(seconds?: number | null) {
  if (seconds == null) {
    return "No heartbeat";
  }
  if (seconds < 60) {
    return `${seconds}s ago`;
  }
  return `${Math.round(seconds / 60)}m ago`;
}

function formatAgentRole(agent: AgentRosterEntry) {
  const display = agent.display_name.trim().toLowerCase();
  const role = agent.role.trim().toLowerCase();
  if (!role || role === display) {
    return null;
  }
  return agent.role;
}

export function CodexAgentsPage({ onNavigate }: { onNavigate: (view: ViewTarget) => void }) {
  const [agents, setAgents] = useState<AgentRosterEntry[]>([]);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [detail, setDetail] = useState<CodexAgentDetailResponse | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [selectedRunDetail, setSelectedRunDetail] = useState<CodexRunDetailResponse | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pendingKey, setPendingKey] = useState<string | null>(null);
  const livePulse = useLivePulse();

  async function loadAgents() {
    const rosterPayload = await fetchAgentRoster();
    setAgents(rosterPayload.agents);
    setSelectedAgentId((current) => current ?? rosterPayload.agents[0]?.agent_id ?? null);
  }

  useEffect(() => {
    void loadAgents().catch(() => setNotice("Agent refresh failed; showing the latest available roster."));
  }, [livePulse]);

  useEffect(() => {
    if (!selectedAgentId) {
      setDetail(null);
      return;
    }
    const controller = new AbortController();
    void fetchCodexAgentDetail(selectedAgentId, controller.signal, () => setNotice("Agent detail fell back to cached data."))
      .then((payload) => setDetail(payload))
      .catch((error) => {
        if (!(error instanceof Error && error.name === "AbortError")) {
          setNotice("Agent detail refresh failed.");
        }
      });
    return () => controller.abort();
  }, [selectedAgentId, livePulse]);

  useEffect(() => {
    setSelectedRunId((current) =>
      detail?.runs.some((run) => run.session_id === current) ? current : detail?.runs[0]?.session_id ?? null
    );
  }, [detail?.runs]);

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
        }
      });
    return () => controller.abort();
  }, [selectedRunId]);

  const selectedAgent = agents.find((agent) => agent.agent_id === selectedAgentId) ?? agents[0] ?? null;
  const ownedIssues = detail?.owned_issues ?? [];
  const agentRuns = detail?.runs ?? [];
  const agentHistory = detail?.history ?? [];
  const activeRunCount = agentRuns.filter((run) => run.status === "active").length;

  async function runAction(key: string, action: () => Promise<unknown>, message: string) {
    setPendingKey(key);
    setNotice(null);
    try {
      await action();
      await loadAgents();
      if (selectedAgentId) {
        setDetail(await fetchCodexAgentDetail(selectedAgentId));
      }
      setNotice(message);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Agent action failed.");
    } finally {
      setPendingKey(null);
    }
  }

  return (
    <section className="codex-page">
      <header className="codex-page__header">
        <div>
          <span className="codex-kicker">Agents</span>
          <h1>See who is doing what and how healthy the machine is</h1>
          <p>This is a Codex-only operator view: current issue ownership, recent execution threads, and the latest agent-local history.</p>
        </div>
      </header>

      {notice ? <div className="codex-banner">{notice}</div> : null}

      <div className="codex-work-layout">
        <div className="codex-list-panel codex-panel">
          {agents.map((agent) => (
            <button
              key={agent.agent_id}
              type="button"
              className={`codex-agent-row ${selectedAgentId === agent.agent_id ? "is-selected" : ""}`}
              onClick={() => setSelectedAgentId(agent.agent_id)}
            >
              <div className="codex-agent-row__top">
                <div className="codex-agent-row__identity">
                  <strong>{agent.display_name}</strong>
                  {formatAgentRole(agent) ? <span>{formatAgentRole(agent)}</span> : null}
                </div>
                <span className={`codex-status-chip codex-status-chip--${agent.status}`}>{agent.status.replaceAll("_", " ")}</span>
              </div>
              <div className="codex-agent-row__task">{agent.current_task_title ?? "Idle"}</div>
              <div className="codex-agent-row__meta">
                <span>{agent.current_task_id ?? "No active issue"}</span>
                <span>{formatHeartbeat(agent.heartbeat_age_seconds)}</span>
              </div>
            </button>
          ))}
        </div>

        <aside className="codex-detail-panel codex-panel">
          {selectedAgent ? (
            <>
              <div className="codex-panel__header">
                <div>
                  <span className="codex-kicker">Agent</span>
                  <h2>{selectedAgent.display_name}</h2>
                  <p>{selectedAgent.role}</p>
                </div>
                <span className={`codex-status-chip codex-status-chip--${selectedAgent.status}`}>{selectedAgent.status}</span>
              </div>

              <div className="codex-detail-grid">
                <div className="codex-metric-card">
                  <span className="codex-kicker">Current issue</span>
                  <strong>{detail?.agent.current_task_title ?? selectedAgent.current_task_title ?? "Idle"}</strong>
                  <span>{detail?.agent.current_issue_key ?? selectedAgent.current_task_id ?? "No active issue"}</span>
                </div>
                <div className="codex-metric-card">
                  <span className="codex-kicker">Heartbeat</span>
                  <strong>{formatHeartbeat(selectedAgent.heartbeat_age_seconds)}</strong>
                  <span>{(selectedAgent.heartbeat_age_seconds ?? 0) >= 90 ? "Stale enough to inspect" : "Codex runtime only"}</span>
                </div>
                <div className="codex-metric-card">
                  <span className="codex-kicker">Owned issues</span>
                  <strong>{ownedIssues.length}</strong>
                  <span>{ownedIssues.filter((task) => task.status === "in_progress").length} active now</span>
                </div>
                <div className="codex-metric-card">
                  <span className="codex-kicker">Execution threads</span>
                  <strong>{activeRunCount}</strong>
                  <span>{agentRuns.length} recent runs</span>
                </div>
              </div>

              <div className="codex-detail-actions">
                <button
                  type="button"
                  className="codex-button codex-button--primary"
                  disabled={pendingKey === `assign:${selectedAgent.agent_id}`}
                  onClick={() =>
                    void runAction(
                      `assign:${selectedAgent.agent_id}`,
                      () => assignNextTask(selectedAgent.agent_id),
                      `Assigned the next issue to ${selectedAgent.display_name}.`
                    )
                  }
                >
                  {pendingKey === `assign:${selectedAgent.agent_id}` ? "Assigning..." : "Assign next issue"}
                </button>
                {selectedAgent.status === "error" ? (
                  <button
                    type="button"
                    className="codex-button"
                    disabled={pendingKey === `recover:${selectedAgent.agent_id}`}
                    onClick={() =>
                      void runAction(
                        `recover:${selectedAgent.agent_id}`,
                        () => recoverAgent(selectedAgent.agent_id),
                        `Recovered ${selectedAgent.display_name}.`
                      )
                    }
                  >
                    {pendingKey === `recover:${selectedAgent.agent_id}` ? "Recovering..." : "Recover"}
                  </button>
                ) : null}
              </div>

              <section className="codex-detail-section">
                <div className="codex-section-heading">
                  <strong>Recent runs</strong>
                  <span>{agentRuns.length}</span>
                </div>
                <div className="codex-run-list">
                  {agentRuns.length ? (
                    agentRuns.map((run) => (
                      <button
                        key={run.session_id}
                        type="button"
                        className={`codex-run-item codex-run-item--interactive ${run.task_id ? "is-clickable" : ""}`}
                        onClick={() => setSelectedRunId(run.session_id)}
                      >
                        <div className="codex-run-item__meta">
                          <strong>{run.task_title ?? run.task_id ?? "No linked issue"}</strong>
                          <span>{run.status.replaceAll("_", " ")}</span>
                        </div>
                        <span>{run.status_message ?? run.provider_type}</span>
                        <span>{formatTimestamp(run.started_at)}</span>
                      </button>
                    ))
                  ) : (
                    <div className="codex-empty-copy">No recent runs were recorded for this agent.</div>
                  )}
                </div>
              </section>

              <section className="codex-detail-section">
                <div className="codex-section-heading">
                  <strong>Selected run</strong>
                  <span>{selectedRunDetail ? selectedRunDetail.status.replaceAll("_", " ") : "none"}</span>
                </div>
                {selectedRunDetail ? (
                <div className="codex-review-callout">
                  <strong>{selectedRunDetail.status_message ?? "No runtime summary recorded."}</strong>
                    <p>
                      {selectedRunDetail.task_title ?? selectedRunDetail.task_id ?? "Unlinked issue"} ·{" "}
                      {selectedRunDetail.provider_type.replaceAll("_", " ")} · {selectedRunDetail.execution_mode?.replaceAll("_", " ") ?? "unknown mode"} ·{" "}
                      started {formatTimestamp(selectedRunDetail.started_at)}
                    </p>
                    <div className="codex-review-facts">
                      <div className="codex-review-fact">
                        <span>Status</span>
                        <strong>{selectedRunDetail.status.replaceAll("_", " ")}</strong>
                      </div>
                      <div className="codex-review-fact">
                        <span>Progress</span>
                        <strong>{selectedRunDetail.progress_pct ?? 0}%</strong>
                      </div>
                      <div className="codex-review-fact">
                        <span>Heartbeat</span>
                        <strong>{selectedRunDetail.last_heartbeat_at ? formatTimestamp(selectedRunDetail.last_heartbeat_at) : "No heartbeat"}</strong>
                      </div>
                    </div>
                    {selectedRunDetail.output_preview?.content ? (
                      <pre className="codex-output-preview__content">{selectedRunDetail.output_preview.content}</pre>
                    ) : (
                      <div className="codex-empty-copy">No runtime output preview is available for this run yet.</div>
                    )}
                    {selectedRunDetail.task_id ? (
                      <div className="codex-detail-actions">
                        <button
                          type="button"
                          className="codex-button"
                          onClick={() => {
                            setPendingTaskFocus(selectedRunDetail.task_id!);
                            onNavigate("work");
                          }}
                        >
                          Open issue
                        </button>
                      </div>
                    ) : null}
                  </div>
                ) : (
                  <div className="codex-empty-copy">Select a run to inspect its runtime output and status.</div>
                )}
              </section>

              <section className="codex-detail-section">
                <div className="codex-section-heading">
                  <strong>Owned issues</strong>
                  <span>{ownedIssues.length}</span>
                </div>
                <div className="codex-run-list">
                  {ownedIssues.length ? (
                    ownedIssues.map((task) => (
                      <button
                        key={task.task_id}
                        type="button"
                        className="codex-run-item codex-run-item--interactive"
                        onClick={() => {
                          setPendingTaskFocus(task.task_id);
                          onNavigate(task.status === "review" || task.status === "blocked" ? "issues" : "work");
                        }}
                      >
                        <div className="codex-run-item__meta">
                          <strong>{task.issue_key ?? task.task_id}</strong>
                          <span>{task.status.replaceAll("_", " ")}</span>
                        </div>
                        <span>{task.title}</span>
                      </button>
                    ))
                  ) : (
                    <div className="codex-empty-copy">No issues are currently assigned to this agent.</div>
                  )}
                </div>
              </section>

              <section className="codex-detail-section">
                <div className="codex-section-heading">
                  <strong>Recent history</strong>
                  <span>{agentHistory.length}</span>
                </div>
                <div className="codex-history-list">
                  {agentHistory.length ? (
                    agentHistory.map((event) => (
                      <button
                        key={`${event.source}:${event.event_id}`}
                        type="button"
                        className={`codex-history-item codex-history-item--interactive ${event.task_id ? "is-clickable" : ""}`}
                        onClick={() => {
                          if (!event.task_id) {
                            return;
                          }
                          setPendingTaskFocus(event.task_id);
                          onNavigate("issues");
                        }}
                        disabled={!event.task_id}
                      >
                        <div className="codex-history-item__meta">
                          <strong>{event.title}</strong>
                          <span>{formatTimestamp(event.created_at)}</span>
                        </div>
                        <span>{event.description}</span>
                      </button>
                    ))
                  ) : (
                    <div className="codex-empty-copy">No recent history was recorded for this agent.</div>
                  )}
                </div>
              </section>
            </>
          ) : (
            <div className="codex-empty-copy">No agents are available in this project.</div>
          )}
        </aside>
      </div>
    </section>
  );
}
