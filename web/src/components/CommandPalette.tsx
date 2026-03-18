import { useEffect, useMemo, useRef, useState } from "react";

export interface CommandPaletteAction {
  id: string;
  label: string;
  description: string;
  keywords?: string[];
  run: () => void;
}

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
  actions: CommandPaletteAction[];
}

function matchesQuery(action: CommandPaletteAction, query: string) {
  if (!query) {
    return true;
  }
  const haystack = [action.label, action.description, ...(action.keywords ?? [])].join(" ").toLowerCase();
  return haystack.includes(query);
}

export function CommandPalette({ open, onClose, actions }: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const filteredActions = useMemo(
    () => actions.filter((action) => matchesQuery(action, query.trim().toLowerCase())),
    [actions, query]
  );

  useEffect(() => {
    if (!open) {
      setQuery("");
      setSelectedIndex(0);
      return;
    }
    const frame = window.requestAnimationFrame(() => {
      inputRef.current?.focus();
    });
    return () => {
      window.cancelAnimationFrame(frame);
    };
  }, [open]);

  useEffect(() => {
    setSelectedIndex((current) => Math.min(current, Math.max(filteredActions.length - 1, 0)));
  }, [filteredActions.length]);

  useEffect(() => {
    if (!open) {
      return;
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setSelectedIndex((current) => Math.min(current + 1, Math.max(filteredActions.length - 1, 0)));
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        setSelectedIndex((current) => Math.max(current - 1, 0));
        return;
      }
      if (event.key === "Enter") {
        const nextAction = filteredActions[selectedIndex];
        if (nextAction) {
          event.preventDefault();
          nextAction.run();
          onClose();
        }
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [filteredActions, onClose, open, selectedIndex]);

  if (!open) {
    return null;
  }

  return (
    <div className="command-palette__backdrop" role="presentation" onClick={onClose}>
      <div
        className="command-palette"
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="command-palette__header">
          <div>
            <span className="eyebrow">Command Palette</span>
            <h2>Jump to anything or run a common operator action</h2>
          </div>
          <span className="status-chip">Esc to close</span>
        </div>
        <input
          ref={inputRef}
          className="command-palette__input"
          type="text"
          value={query}
          placeholder="Search pages, projects, and actions"
          onChange={(event) => setQuery(event.target.value)}
        />
        <div className="command-palette__results">
          {filteredActions.length ? (
            filteredActions.map((action, index) => (
              <button
                key={action.id}
                type="button"
                className={`command-palette__item ${selectedIndex === index ? "is-selected" : ""}`}
                onMouseEnter={() => setSelectedIndex(index)}
                onClick={() => {
                  action.run();
                  onClose();
                }}
              >
                <strong>{action.label}</strong>
                <span>{action.description}</span>
              </button>
            ))
          ) : (
            <div className="empty-state empty-state--compact">
              <strong>No matching actions</strong>
              <p>Try “run supervisor”, “incidents”, or a project name.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
