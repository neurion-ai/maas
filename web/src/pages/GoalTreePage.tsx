import { useEffect, useState } from "react";
import { fetchGoalTree } from "../lib/controlRoomApi";
import { useLivePulse } from "../lib/useLivePulse";
import type { GoalTreeNode, GoalTreeResponse } from "../types";

function GoalTreeItem({ node }: { node: GoalTreeNode }) {
  return (
    <li className="goal-tree__item">
      <div className="goal-card">
        <div className="goal-card__header">
          <strong>{node.title}</strong>
          <span className={`goal-status goal-status--${node.status}`}>{node.status}</span>
        </div>
        <p>{node.description}</p>
        <div className="goal-card__meta">
          <span>{node.goal_type}</span>
          <span>Priority {node.priority}</span>
          <span>{Object.values(node.task_counts).reduce((sum, value) => sum + value, 0)} tasks</span>
        </div>
      </div>
      {node.children.length > 0 && (
        <ul className="goal-tree">
          {node.children.map((child) => (
            <GoalTreeItem key={child.goal_id} node={child} />
          ))}
        </ul>
      )}
    </li>
  );
}

export function GoalTreePage() {
  const [tree, setTree] = useState<GoalTreeResponse | null>(null);
  const livePulse = useLivePulse();

  useEffect(() => {
    let mounted = true;
    async function loadTree() {
      const payload = await fetchGoalTree();
      if (mounted) {
        setTree(payload);
      }
    }

    void loadTree();
    return () => {
      mounted = false;
    };
  }, [livePulse]);

  return (
    <section className="control-page">
      <header className="page-hero">
        <div>
          <span className="eyebrow">Goal Tree</span>
          <h1>Hierarchy of work and intent</h1>
          <p>Strategic goals stay visible while day-to-day execution flows through the board.</p>
        </div>
      </header>

      <article className="data-panel">
        <header className="data-panel__header">
          <h2>Goal hierarchy</h2>
          <p>{tree?.total_goals ?? 0} total goals in the current project.</p>
        </header>
        <ul className="goal-tree">
          {(tree?.roots ?? []).map((root) => (
            <GoalTreeItem key={root.goal_id} node={root} />
          ))}
        </ul>
      </article>
    </section>
  );
}
