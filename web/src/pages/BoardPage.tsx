import { startTransition, useDeferredValue, useEffect, useMemo, useState } from "react";
import { fetchBoard, haltTask, reassignTask, reprioritizeTask, reviewTask, setAgentState } from "../lib/boardApi";
import { useLivePulse } from "../lib/useLivePulse";
import type { BoardFiltersInput, BoardResponse, FilterOption } from "../types";
import { BoardColumn } from "../components/BoardColumn";
import { StatCard } from "../components/StatCard";

const PRIORITY_OPTIONS = [
  { value: "0", label: "Any priority" },
  { value: "50", label: "Medium and up" },
  { value: "75", label: "High and up" },
  { value: "90", label: "Critical only" }
];

export function BoardPage() {
  const [board, setBoard] = useState<BoardResponse | null>(null);
  const [query, setQuery] = useState("");
  const [blockedOnly, setBlockedOnly] = useState(false);
  const [reviewOnly, setReviewOnly] = useState(false);
  const [priorityMin, setPriorityMin] = useState("0");
  const [agentId, setAgentId] = useState("");
  const [goalId, setGoalId] = useState("");
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [pendingActionKey, setPendingActionKey] = useState<string | null>(null);
  const deferredQuery = useDeferredValue(query);
  const livePulse = useLivePulse();

  const boardFilters: BoardFiltersInput = useMemo(
    () => ({
      search: deferredQuery.trim() || undefined,
      blockedOnly,
      reviewOnly,
      priorityMin: Number(priorityMin) || undefined,
      agentId: agentId || undefined,
      goalId: goalId || undefined
    }),
    [agentId, blockedOnly, deferredQuery, goalId, priorityMin, reviewOnly]
  );

  async function loadBoard(signal?: AbortSignal) {
    setIsRefreshing(true);
    try {
      const nextBoard = await fetchBoard(boardFilters, signal);
      startTransition(() => {
        setBoard(nextBoard);
      });
    } catch (error) {
      if (!(error instanceof Error && error.name === "AbortError")) {
        setNotice("Board refresh failed; showing the most recent available data.");
      }
    } finally {
      setIsRefreshing(false);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    void loadBoard(controller.signal);
    const intervalId = window.setInterval(() => {
      void loadBoard(controller.signal);
    }, 15000);

    return () => {
      controller.abort();
      window.clearInterval(intervalId);
    };
  }, [boardFilters]);

  useEffect(() => {
    if (livePulse === 0) {
      return;
    }
    void loadBoard();
  }, [livePulse]);

  const visibleTaskCount = useMemo(() => {
    if (!board) {
      return 0;
    }
    return board.columns.reduce((sum, column) => sum + column.tasks.length, 0);
  }, [board]);

  const filterOptions = useMemo(() => {
    const empty: FilterOption[] = [];
    return {
      agents: board?.filter_options?.agents ?? empty,
      goals: board?.filter_options?.goals ?? empty
    };
  }, [board]);

  async function handleReviewAction(taskId: string, decision: "approve" | "reject") {
    const actionKey = `review:${taskId}:${decision}`;
    setPendingActionKey(actionKey);
    setNotice(null);
    try {
      await reviewTask(taskId, decision);
      setNotice(`Review ${decision}ed for ${taskId}.`);
      await loadBoard();
    } catch {
      setNotice("Review action is not available yet on this backend.");
    } finally {
      setPendingActionKey(null);
    }
  }

  async function handleAgentAction(nextAgentId: string, action: "pause" | "resume") {
    const actionKey = `agent:${nextAgentId}:${action}`;
    setPendingActionKey(actionKey);
    setNotice(null);
    try {
      await setAgentState(nextAgentId, action);
      setNotice(`Agent ${action} requested for ${nextAgentId}.`);
      await loadBoard();
    } catch {
      setNotice("Agent steering is not available yet on this backend.");
    } finally {
      setPendingActionKey(null);
    }
  }

  async function handlePriorityChange(taskId: string, priority: number) {
    const actionKey = `reprioritize:${taskId}`;
    setPendingActionKey(actionKey);
    setNotice(null);
    try {
      await reprioritizeTask(taskId, priority);
      setNotice(`Priority updated for ${taskId}.`);
      await loadBoard();
    } catch {
      setNotice("Priority update failed; keep the current board snapshot under review.");
    } finally {
      setPendingActionKey(null);
    }
  }

  async function handleReassign(taskId: string, nextAgentId: string) {
    const actionKey = `reassign:${taskId}`;
    setPendingActionKey(actionKey);
    setNotice(null);
    try {
      await reassignTask(taskId, nextAgentId);
      setNotice(`Task ${taskId} reassigned to ${nextAgentId}.`);
      await loadBoard();
    } catch {
      setNotice("Task reassignment failed; keep the current board snapshot under review.");
    } finally {
      setPendingActionKey(null);
    }
  }

  async function handleHalt(taskId: string) {
    const actionKey = `halt:${taskId}`;
    setPendingActionKey(actionKey);
    setNotice(null);
    try {
      await haltTask(taskId);
      setNotice(`Task ${taskId} halted.`);
      await loadBoard();
    } catch {
      setNotice("Task halt failed; keep the current board snapshot under review.");
    } finally {
      setPendingActionKey(null);
    }
  }

  return (
    <main className="board-shell">
      <section className="hero-panel">
        <div className="hero-panel__copy">
          <span className="eyebrow">MAAS Control Room</span>
          <h1>Agent work, review queues, and blockers in one board-first view.</h1>
          <p>
            The board is the primary operating surface: plan work, watch live sessions, and
            spot stalled tasks before they turn into drift.
          </p>
        </div>
        <div className="hero-panel__status">
          <label className="search-box">
            <span>Filter board</span>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search task, goal, agent, or id"
            />
          </label>
          <div className="status-chip">
            <span className={`status-chip__dot ${isRefreshing ? "is-live" : ""}`} />
            {isRefreshing ? "Refreshing board" : "Live board"}
          </div>
        </div>
      </section>

      <section className="filters-panel">
        <div className="filters-panel__header">
          <div>
            <h2>Board filters</h2>
            <p>These are sent to the server when supported and degrade safely when they are not.</p>
          </div>
          {notice ? <p className="filters-panel__notice">{notice}</p> : null}
        </div>
        <div className="filters-panel__grid">
          <label className="filter-field">
            <span>Priority</span>
            <select value={priorityMin} onChange={(event) => setPriorityMin(event.target.value)}>
              {PRIORITY_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="filter-field">
            <span>Agent</span>
            <select value={agentId} onChange={(event) => setAgentId(event.target.value)}>
              <option value="">All agents</option>
              {filterOptions.agents.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="filter-field">
            <span>Goal</span>
            <select value={goalId} onChange={(event) => setGoalId(event.target.value)}>
              <option value="">All goals</option>
              {filterOptions.goals.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <div className="toggle-row">
            <button
              type="button"
              className={`toggle-pill ${blockedOnly ? "is-active" : ""}`}
              onClick={() => setBlockedOnly((current) => !current)}
            >
              Blocked only
            </button>
            <button
              type="button"
              className={`toggle-pill ${reviewOnly ? "is-active" : ""}`}
              onClick={() => setReviewOnly((current) => !current)}
            >
              Review only
            </button>
          </div>
        </div>
      </section>

      <section className="stats-grid">
        <StatCard label="Tasks in view" value={visibleTaskCount} />
        <StatCard label="Active agents" value={board?.summary.active_agents ?? 0} tone="good" />
        <StatCard label="Blocked tasks" value={board?.summary.blocked_tasks ?? 0} tone="warn" />
        <StatCard label="Review queue" value={board?.summary.review_tasks ?? 0} />
      </section>

      <section className="board-toolbar">
        <div>
          <h2>Operational Kanban</h2>
          <p>Columns are server-defined through the task-first `/api/board` contract.</p>
        </div>
        <span className="timestamp">
          {board?.generated_at ? `Snapshot ${new Date(board.generated_at).toLocaleTimeString()}` : "Loading"}
        </span>
      </section>

      <section className="board-grid" aria-label="MAAS task board">
        {(board?.columns ?? []).map((column) => (
          <BoardColumn
            key={column.key}
            column={column}
            agentOptions={filterOptions.agents}
            pendingActionKey={pendingActionKey}
            onReviewAction={handleReviewAction}
            onAgentAction={handleAgentAction}
            onPriorityChange={handlePriorityChange}
            onReassign={handleReassign}
            onHalt={handleHalt}
          />
        ))}
      </section>
    </main>
  );
}
