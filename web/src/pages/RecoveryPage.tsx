import { useEffect, useState } from "react";
import { StatCard } from "../components/StatCard";
import { fetchRecoveryPolicy, setRecoveryPolicy } from "../lib/controlRoomApi";
import { useLivePulse } from "../lib/useLivePulse";
import type { RecoveryPolicyResponse, RecoveryPolicySettings } from "../types";

type RecoveryDraft = Record<keyof RecoveryPolicySettings, string>;

const BOOLEAN_FIELDS: (keyof RecoveryPolicySettings)[] = [
  "auto_retry_timeout_sessions",
  "auto_retry_failed_sessions"
];

const NUMBER_FIELDS: (keyof RecoveryPolicySettings)[] = [
  "max_timed_out_retries",
  "max_failed_session_retries",
  "timed_out_retry_cooldown_seconds",
  "failed_session_retry_cooldown_seconds",
  "recover_and_requeue_cooldown_seconds",
  "retry_backoff_multiplier",
  "retry_backoff_max_seconds"
];

function buildDraft(
  payload: RecoveryPolicyResponse,
  current: RecoveryDraft | null,
  reset = false
): RecoveryDraft {
  const serverDraft: RecoveryDraft = {
    auto_retry_timeout_sessions: payload.policy.auto_retry_timeout_sessions ? "true" : "false",
    auto_retry_failed_sessions: payload.policy.auto_retry_failed_sessions ? "true" : "false",
    max_timed_out_retries: String(payload.policy.max_timed_out_retries),
    max_failed_session_retries: String(payload.policy.max_failed_session_retries),
    timed_out_retry_cooldown_seconds: String(payload.policy.timed_out_retry_cooldown_seconds),
    failed_session_retry_cooldown_seconds: String(payload.policy.failed_session_retry_cooldown_seconds),
    recover_and_requeue_cooldown_seconds: String(payload.policy.recover_and_requeue_cooldown_seconds),
    retry_backoff_multiplier: String(payload.policy.retry_backoff_multiplier),
    retry_backoff_max_seconds: String(payload.policy.retry_backoff_max_seconds)
  };

  if (!current || reset) {
    return serverDraft;
  }

  return Object.fromEntries(
    Object.keys(serverDraft).map((key) => [key, current[key as keyof RecoveryDraft] ?? serverDraft[key as keyof RecoveryDraft]])
  ) as RecoveryDraft;
}

function buildDefaultsDraft(defaults: RecoveryPolicySettings): RecoveryDraft {
  return {
    auto_retry_timeout_sessions: defaults.auto_retry_timeout_sessions ? "true" : "false",
    auto_retry_failed_sessions: defaults.auto_retry_failed_sessions ? "true" : "false",
    max_timed_out_retries: String(defaults.max_timed_out_retries),
    max_failed_session_retries: String(defaults.max_failed_session_retries),
    timed_out_retry_cooldown_seconds: String(defaults.timed_out_retry_cooldown_seconds),
    failed_session_retry_cooldown_seconds: String(defaults.failed_session_retry_cooldown_seconds),
    recover_and_requeue_cooldown_seconds: String(defaults.recover_and_requeue_cooldown_seconds),
    retry_backoff_multiplier: String(defaults.retry_backoff_multiplier),
    retry_backoff_max_seconds: String(defaults.retry_backoff_max_seconds)
  };
}

function previewLabel(items: { attempt: number; delay_seconds: number }[]) {
  if (!items.length) {
    return "Disabled";
  }
  return items.map((item) => `#${item.attempt}: ${item.delay_seconds}s`).join(" | ");
}

export function RecoveryPage() {
  const [recovery, setRecovery] = useState<RecoveryPolicyResponse | null>(null);
  const [draft, setDraft] = useState<RecoveryDraft | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pendingSave, setPendingSave] = useState(false);
  const livePulse = useLivePulse();

  useEffect(() => {
    let mounted = true;

    async function loadRecovery() {
      const payload = await fetchRecoveryPolicy();
      if (mounted) {
        setRecovery(payload);
        setDraft((current) => buildDraft(payload, current));
      }
    }

    void loadRecovery();
    return () => {
      mounted = false;
    };
  }, [livePulse]);

  async function reload(reset = false) {
    const payload = await fetchRecoveryPolicy();
    setRecovery(payload);
    setDraft((current) => buildDraft(payload, current, reset));
  }

  function updateDraft(field: keyof RecoveryPolicySettings, value: string) {
    setDraft((current) => (current ? { ...current, [field]: value } : current));
  }

  async function handleSave(nextDraft?: RecoveryDraft) {
    const currentDraft = nextDraft ?? draft;
    if (!currentDraft) {
      return;
    }

    const payload: Record<string, string | number | boolean> = {};
    BOOLEAN_FIELDS.forEach((field) => {
      payload[field] = currentDraft[field] === "true";
    });
    NUMBER_FIELDS.forEach((field) => {
      payload[field] = Number(currentDraft[field]);
    });

    setPendingSave(true);
    setNotice(null);
    try {
      await setRecoveryPolicy(payload);
      await reload(true);
      setNotice("Updated project recovery policy.");
    } catch {
      setNotice("Recovery policy update failed; keeping the previous policy in effect.");
    } finally {
      setPendingSave(false);
    }
  }

  async function handleResetToDefaults() {
    if (!recovery) {
      return;
    }
    const defaultsDraft = buildDefaultsDraft(recovery.defaults);
    await handleSave(defaultsDraft);
  }

  const currentDraft = draft;

  return (
    <section className="control-page">
      <header className="page-hero">
        <div>
          <span className="eyebrow">Recovery</span>
          <h1>Retry policy and backoff controls</h1>
          <p>Inspect retry pressure, adjust timeout and failed-session retry policy, and preview the actual cooldown schedule operators are creating.</p>
        </div>
        {notice ? <p className="filters-panel__notice">{notice}</p> : null}
      </header>

      <section className="stats-grid">
        <StatCard label="Backoff tasks" value={recovery?.summary.retry_backoff_tasks ?? 0} tone="warn" />
        <StatCard label="Retry history" value={recovery?.summary.tasks_with_retry_history ?? 0} />
        <StatCard label="Recoverable blocked" value={recovery?.summary.recoverable_blocked_tasks ?? 0} tone="warn" />
        <StatCard label="Open failure alerts" value={recovery?.summary.open_failure_alerts ?? 0} tone="warn" />
        <StatCard label="Repeated incidents" value={recovery?.summary.open_repeated_failure_alerts ?? 0} tone="warn" />
        <StatCard label="Quarantine open" value={recovery?.summary.open_quarantine_entries ?? 0} />
      </section>

      <section className="overview-grid">
        <article className="data-panel">
          <header className="data-panel__header">
            <div>
              <h2>Recovery policy</h2>
              <p>These settings control automatic timeout retries, failed-session retries, and the cooldown applied when operators recover and requeue blocked work.</p>
            </div>
          </header>
          {currentDraft ? (
            <div className="recovery-settings">
              <div className="filters-panel__grid">
                <label className="filter-field">
                  <span>Auto retry timeout sessions</span>
                  <select
                    value={currentDraft.auto_retry_timeout_sessions}
                    onChange={(event) => updateDraft("auto_retry_timeout_sessions", event.target.value)}
                  >
                    <option value="false">Disabled</option>
                    <option value="true">Enabled</option>
                  </select>
                </label>
                <label className="filter-field">
                  <span>Max timed-out retries</span>
                  <input
                    type="number"
                    min="0"
                    value={currentDraft.max_timed_out_retries}
                    onChange={(event) => updateDraft("max_timed_out_retries", event.target.value)}
                  />
                </label>
                <label className="filter-field">
                  <span>Timed-out cooldown seconds</span>
                  <input
                    type="number"
                    min="0"
                    value={currentDraft.timed_out_retry_cooldown_seconds}
                    onChange={(event) => updateDraft("timed_out_retry_cooldown_seconds", event.target.value)}
                  />
                </label>
                <label className="filter-field">
                  <span>Auto retry failed sessions</span>
                  <select
                    value={currentDraft.auto_retry_failed_sessions}
                    onChange={(event) => updateDraft("auto_retry_failed_sessions", event.target.value)}
                  >
                    <option value="false">Disabled</option>
                    <option value="true">Enabled</option>
                  </select>
                </label>
                <label className="filter-field">
                  <span>Max failed-session retries</span>
                  <input
                    type="number"
                    min="0"
                    value={currentDraft.max_failed_session_retries}
                    onChange={(event) => updateDraft("max_failed_session_retries", event.target.value)}
                  />
                </label>
                <label className="filter-field">
                  <span>Failed-session cooldown seconds</span>
                  <input
                    type="number"
                    min="0"
                    value={currentDraft.failed_session_retry_cooldown_seconds}
                    onChange={(event) => updateDraft("failed_session_retry_cooldown_seconds", event.target.value)}
                  />
                </label>
                <label className="filter-field">
                  <span>Recover + requeue cooldown</span>
                  <input
                    type="number"
                    min="0"
                    value={currentDraft.recover_and_requeue_cooldown_seconds}
                    onChange={(event) => updateDraft("recover_and_requeue_cooldown_seconds", event.target.value)}
                  />
                </label>
                <label className="filter-field">
                  <span>Backoff multiplier</span>
                  <input
                    type="number"
                    min="1"
                    value={currentDraft.retry_backoff_multiplier}
                    onChange={(event) => updateDraft("retry_backoff_multiplier", event.target.value)}
                  />
                </label>
                <label className="filter-field">
                  <span>Backoff max seconds</span>
                  <input
                    type="number"
                    min="0"
                    value={currentDraft.retry_backoff_max_seconds}
                    onChange={(event) => updateDraft("retry_backoff_max_seconds", event.target.value)}
                  />
                </label>
              </div>
              <div className="task-card__actions">
                <button type="button" className="task-action task-action--approve" disabled={pendingSave} onClick={() => void handleSave()}>
                  {pendingSave ? "Saving..." : "Save policy"}
                </button>
                <button
                  type="button"
                  className="task-action task-action--secondary"
                  disabled={pendingSave}
                  onClick={() => void handleResetToDefaults()}
                >
                  Reset to defaults
                </button>
              </div>
            </div>
          ) : null}
        </article>

        <article className="data-panel">
          <header className="data-panel__header">
            <div>
              <h2>Backoff preview</h2>
              <p>The preview shows the actual delay schedule that the current multiplier and cap will produce.</p>
            </div>
          </header>
          <div className="data-list">
            <div className="data-list__item">
              <div>
                <strong>Timed-out sessions</strong>
                <p>{previewLabel(recovery?.backoff_preview.timed_out_retry_delays ?? [])}</p>
              </div>
            </div>
            <div className="data-list__item">
              <div>
                <strong>Failed sessions</strong>
                <p>{previewLabel(recovery?.backoff_preview.failed_session_retry_delays ?? [])}</p>
              </div>
            </div>
            <div className="data-list__item">
              <div>
                <strong>Recover + requeue</strong>
                <p>{previewLabel(recovery?.backoff_preview.recover_and_requeue_delays ?? [])}</p>
              </div>
            </div>
          </div>
        </article>
      </section>
    </section>
  );
}
