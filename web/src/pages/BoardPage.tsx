import { startTransition, useDeferredValue, useEffect, useMemo, useState } from "react";
import { fetchBoard } from "../lib/boardApi";
import type { BoardResponse } from "../types";
import { BoardColumn } from "../components/BoardColumn";
import { StatCard } from "../components/StatCard";

export function BoardPage() {
  const [board, setBoard] = useState<BoardResponse | null>(null);
  const [query, setQuery] = useState("");
  const [isRefreshing, setIsRefreshing] = useState(false);
  const deferredQuery = useDeferredValue(query);

  useEffect(() => {
    let isMounted = true;

    async function loadBoard() {
      setIsRefreshing(true);
      const nextBoard = await fetchBoard();
      if (!isMounted) {
        return;
      }
      startTransition(() => {
        setBoard(nextBoard);
      });
      setIsRefreshing(false);
    }

    void loadBoard();
    const intervalId = window.setInterval(() => {
      void loadBoard();
    }, 15000);

    return () => {
      isMounted = false;
      window.clearInterval(intervalId);
    };
  }, []);

  const filteredBoard = useMemo(() => {
    if (!board) {
      return null;
    }

    const normalizedQuery = deferredQuery.trim().toLowerCase();
    if (!normalizedQuery) {
      return board;
    }

    return {
      ...board,
      columns: board.columns.map((column) => ({
        ...column,
        tasks: column.tasks.filter((task) => {
          return [
            task.title,
            task.goal?.title ?? "",
            task.agent?.name ?? "",
            task.task_id
          ]
            .join(" ")
            .toLowerCase()
            .includes(normalizedQuery);
        })
      }))
    };
  }, [board, deferredQuery]);

  const visibleTaskCount = useMemo(() => {
    if (!filteredBoard) {
      return 0;
    }
    return filteredBoard.columns.reduce((sum, column) => sum + column.tasks.length, 0);
  }, [filteredBoard]);

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
        {(filteredBoard?.columns ?? []).map((column) => (
          <BoardColumn key={column.key} column={column} />
        ))}
      </section>
    </main>
  );
}
