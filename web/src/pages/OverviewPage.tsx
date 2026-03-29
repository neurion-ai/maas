import { useEffect, useState } from "react";
import {
  fetchOverview,
  fetchRepoFile,
  fetchRepoTree,
  refreshRepoPlan,
  rescanBrownfieldProject,
  runAlertOperatorAction,
  runFailureOperatorAction,
  runSupervisorPass,
  updateBrownfieldOnboardingReview
} from "../lib/controlRoomApi";
import { reviewTask } from "../lib/boardApi";
import { useLivePulse } from "../lib/useLivePulse";
import type { OverviewResponse, RepoFileResponse, RepoTreeResponse, SupervisorRunResponse } from "../types";
import { StatCard } from "../components/StatCard";

export function OverviewPage() {
  const [overview, setOverview] = useState<OverviewResponse | null>(null);
  const [supervisorResult, setSupervisorResult] = useState<SupervisorRunResponse | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [isRunningSupervisor, setIsRunningSupervisor] = useState(false);
  const [pendingFailureAction, setPendingFailureAction] = useState<string | null>(null);
  const [pendingRepeatedFailureAction, setPendingRepeatedFailureAction] = useState<string | null>(null);
  const [pendingOnboardingReview, setPendingOnboardingReview] = useState<string | null>(null);
  const [pendingBrownfieldRescan, setPendingBrownfieldRescan] = useState(false);
  const [pendingRepoPlanRefresh, setPendingRepoPlanRefresh] = useState(false);
  const [pendingOnboardingReviewUpdate, setPendingOnboardingReviewUpdate] = useState<string | null>(null);
  const [repoTree, setRepoTree] = useState<RepoTreeResponse | null>(null);
  const [repoFile, setRepoFile] = useState<RepoFileResponse | null>(null);
  const [pendingRepoPath, setPendingRepoPath] = useState<string | null>(null);
  const livePulse = useLivePulse();
  const brownfieldTrust = overview?.onboarding?.repo_plan_state?.trust ?? overview?.onboarding?.repo_plan_trust ?? null;

  useEffect(() => {
    let mounted = true;

    async function loadOverview() {
      const payload = await fetchOverview();
      if (mounted) {
        setOverview(payload);
      }
    }

    void loadOverview();

    return () => {
      mounted = false;
    };
  }, [livePulse]);

  useEffect(() => {
    let mounted = true;
    if (overview?.onboarding?.mode !== "brownfield") {
      setRepoTree(null);
      setRepoFile(null);
      return () => {
        mounted = false;
      };
    }

    async function loadInitialRepoTree() {
      try {
        const payload = await fetchRepoTree("");
        if (mounted) {
          setRepoTree(payload);
        }
      } catch {
        if (mounted) {
          setNotice("Imported repository browser is unavailable; keeping onboarding summary only.");
        }
      }
    }

    void loadInitialRepoTree();

    return () => {
      mounted = false;
    };
  }, [overview?.project?.project_id, overview?.onboarding?.mode]);

  async function handleRunSupervisor() {
    setIsRunningSupervisor(true);
    setNotice(null);
    try {
      const result = await runSupervisorPass(2);
      setSupervisorResult(result);
      const projectScopeSummary =
        result.project_runs.length > 1 ? ` across ${result.project_runs.length} projects` : "";
      setNotice(
        `Supervisor refreshed ${result.ready_changes.length} tasks, assigned ${result.assigned_count}, and found ${result.stale_sessions.length} stale sessions${projectScopeSummary}.`
      );
      setOverview(await fetchOverview());
    } catch {
      setNotice("Supervisor run failed; keeping the most recent overview snapshot.");
    } finally {
      setIsRunningSupervisor(false);
    }
  }

  async function handleOverviewFailureAction(
    failureId: string,
    actionKind: "primary" | "secondary" = "primary",
  ) {
    const failure = overview?.recent_failures.find((item) => item.failure_id === failureId);
    const operatorAction =
      actionKind === "secondary" ? failure?.secondary_operator_action : failure?.operator_action;
    if (!operatorAction) {
      return;
    }

    setPendingFailureAction(`${failureId}:${operatorAction.action}`);
    setNotice(null);
    try {
      await runFailureOperatorAction(operatorAction);
      setOverview(await fetchOverview());
      if (operatorAction.action === "restore_and_requeue_quarantine_entry") {
        setNotice(`Restored quarantined artifacts and returned task ${operatorAction.related_task_id} to the queue.`);
      } else if (operatorAction.action === "dismiss_quarantine_entry") {
        setNotice(`Dismissed quarantine incident for failure ${failureId}; artifacts remain isolated.`);
      } else if (operatorAction.action === "reopen_quarantine_entry") {
        setNotice(`Reopened dismissed quarantine entry for failure ${failureId}.`);
      } else if (operatorAction.action === "restore_failure_artifacts") {
        setNotice(`Restored quarantined artifacts for failure ${failureId}.`);
      } else {
        setNotice(`Recovered and requeued task ${operatorAction.resource_id}.`);
      }
    } catch {
      setNotice("Failure action failed; keep the incident under operator review.");
    } finally {
      setPendingFailureAction(null);
    }
  }

  async function handleOverviewRepeatedFailureAction(taskId: string) {
    const repeatedFailure = overview?.repeated_failures.find((item) => item.task_id === taskId);
    if (!repeatedFailure?.operator_action) {
      return;
    }

    setPendingRepeatedFailureAction(`${taskId}:${repeatedFailure.operator_action.action}`);
    setNotice(null);
    try {
      await runAlertOperatorAction(repeatedFailure.operator_action);
      setOverview(await fetchOverview());
      setNotice(`Resolved the repeated-failure incident for ${taskId}.`);
    } catch {
      setNotice("Repeated-failure resolution failed; keep the task under operator review.");
    } finally {
      setPendingRepeatedFailureAction(null);
    }
  }

  async function handleOnboardingReview(decision: "approve" | "reject") {
    const reviewTaskId = overview?.onboarding?.review_task_id;
    if (!reviewTaskId) {
      return;
    }

    setPendingOnboardingReview(decision);
    setNotice(null);
    try {
      await reviewTask(reviewTaskId, decision);
      setOverview(await fetchOverview());
      setNotice(
        decision === "approve"
          ? "Brownfield onboarding approved; imported work is now eligible for scheduling."
          : "Brownfield onboarding sent back with changes requested; imported work remains gated."
      );
    } catch {
      setNotice("Brownfield onboarding review action failed; keep the imported work under operator review.");
    } finally {
      setPendingOnboardingReview(null);
    }
  }

  async function handleBrownfieldRescan() {
    const projectId = overview?.project?.project_id;
    if (!projectId) {
      return;
    }

    setPendingBrownfieldRescan(true);
    setNotice(null);
    try {
      const payload = await rescanBrownfieldProject(projectId);
      const refreshedOverview = await fetchOverview();
      setOverview(refreshedOverview);
      try {
        const refreshedTree = await fetchRepoTree("");
        setRepoTree(refreshedTree);
        setRepoFile(null);
      } catch {
        setRepoTree(null);
        setRepoFile(null);
      }
      setNotice(
        payload.drift?.detected
          ? `Brownfield rescan detected drift and reopened review: ${payload.drift?.summary ?? "changes detected"}.`
          : "Brownfield rescan completed with no material drift detected."
      );
    } catch {
      setNotice("Brownfield rescan failed; keeping the current imported understanding.");
    } finally {
      setPendingBrownfieldRescan(false);
    }
  }

  async function handleUpdateOnboardingReview(
    payload: {
      ignored_paths: string[];
      accepted_workflow_labels?: string[] | null;
      accepted_runbook_labels?: string[] | null;
    },
    noticeMessage: string,
    pendingKey: string
  ) {
    const projectId = overview?.project?.project_id;
    if (!projectId) {
      return;
    }

    setPendingOnboardingReviewUpdate(pendingKey);
    setNotice(null);
    try {
      await updateBrownfieldOnboardingReview(projectId, payload);
      setOverview(await fetchOverview());
      setNotice(noticeMessage);
    } catch {
      setNotice("Updating brownfield onboarding review inputs failed; keeping the current imported understanding.");
    } finally {
      setPendingOnboardingReviewUpdate(null);
    }
  }

  async function handleRefreshRepoPlan() {
    const projectId = overview?.project?.project_id;
    if (!projectId) {
      return;
    }

    setPendingRepoPlanRefresh(true);
    setNotice(null);
    try {
      const payload = await refreshRepoPlan(projectId);
      setOverview(await fetchOverview());
      setNotice(
        `Repo-grounded plan refreshed: ${payload.preview?.generated_task_count ?? 0} synthesized tasks, ${payload.created_task_ids?.length ?? 0} created, ${payload.updated_task_ids?.length ?? 0} updated.`
      );
    } catch {
      setNotice("Refreshing the repo-grounded plan failed; keeping the current brownfield plan state.");
    } finally {
      setPendingRepoPlanRefresh(false);
    }
  }

  async function handleToggleIgnoredPath(path: string) {
    const reviewOverrides = overview?.onboarding?.review_overrides;
    if (!reviewOverrides) {
      return;
    }
    const ignoredPaths = reviewOverrides.ignored_paths.includes(path)
      ? reviewOverrides.ignored_paths.filter((item) => item !== path)
      : [...reviewOverrides.ignored_paths, path];
    await handleUpdateOnboardingReview(
      {
        ignored_paths: ignoredPaths,
        accepted_workflow_labels: reviewOverrides.accepted_workflow_labels,
        accepted_runbook_labels: reviewOverrides.accepted_runbook_labels
      },
      ignoredPaths.includes(path)
        ? `Ignored imported scope ${path} for onboarding release.`
        : `Restored imported scope ${path} to the onboarding release set.`,
      `ignore:${path}`
    );
  }

  async function handleToggleAcceptedWorkflow(label: string) {
    const reviewOverrides = overview?.onboarding?.review_overrides;
    if (!reviewOverrides) {
      return;
    }
    const acceptedWorkflowLabels = reviewOverrides.accepted_workflow_labels.includes(label)
      ? reviewOverrides.accepted_workflow_labels.filter((item) => item !== label)
      : [...reviewOverrides.accepted_workflow_labels, label];
    await handleUpdateOnboardingReview(
      {
        ignored_paths: reviewOverrides.ignored_paths,
        accepted_workflow_labels: acceptedWorkflowLabels,
        accepted_runbook_labels: reviewOverrides.accepted_runbook_labels
      },
      acceptedWorkflowLabels.includes(label)
        ? `Included imported workflow ${label} in onboarding release.`
        : `Excluded imported workflow ${label} from onboarding release.`,
      `workflow:${label}`
    );
  }

  async function handleToggleAcceptedRunbook(label: string) {
    const reviewOverrides = overview?.onboarding?.review_overrides;
    if (!reviewOverrides) {
      return;
    }
    const acceptedRunbookLabels = reviewOverrides.accepted_runbook_labels.includes(label)
      ? reviewOverrides.accepted_runbook_labels.filter((item) => item !== label)
      : [...reviewOverrides.accepted_runbook_labels, label];
    await handleUpdateOnboardingReview(
      {
        ignored_paths: reviewOverrides.ignored_paths,
        accepted_workflow_labels: reviewOverrides.accepted_workflow_labels,
        accepted_runbook_labels: acceptedRunbookLabels
      },
      acceptedRunbookLabels.includes(label)
        ? `Included imported runbook command ${label} in onboarding release.`
        : `Excluded imported runbook command ${label} from onboarding release.`,
      `runbook:${label}`
    );
  }

  async function handleBrowseRepoPath(path: string) {
    setPendingRepoPath(path || ".");
    try {
      const payload = await fetchRepoTree(path);
      setRepoTree(payload);
      setRepoFile(null);
    } catch {
      setNotice("Unable to load that imported repo area.");
    } finally {
      setPendingRepoPath(null);
    }
  }

  async function handleOpenRepoFile(path: string) {
    setPendingRepoPath(path);
    try {
      const payload = await fetchRepoFile(path);
      setRepoFile(payload);
    } catch {
      setNotice("Unable to preview that imported file.");
    } finally {
      setPendingRepoPath(null);
    }
  }

  return (
    <section className="control-page">
      <header className="page-hero">
        <div>
          <span className="eyebrow">Overview</span>
          <h1>{overview?.project?.name ?? "MAAS Control Room"}</h1>
          <p>{overview?.project?.description ?? "High-level system status, active work, and recent movement."}</p>
        </div>
        <div className="page-hero__actions">
          <button
            type="button"
            className="task-action task-action--secondary"
            disabled={isRunningSupervisor}
            onClick={() => void handleRunSupervisor()}
          >
            {isRunningSupervisor ? "Running supervisor..." : "Run supervisor pass"}
          </button>
          {notice ? <p className="page-hero__notice">{notice}</p> : null}
        </div>
      </header>

      <section className="stats-grid">
        <StatCard label="Tasks total" value={overview?.summary.tasks_total ?? 0} />
        <StatCard label="In progress" value={overview?.summary.tasks_in_progress ?? 0} tone="good" />
        <StatCard label="Review queue" value={overview?.summary.tasks_review ?? 0} />
        <StatCard label="Blocked" value={overview?.summary.tasks_blocked ?? 0} tone="warn" />
        <StatCard label="Open escalations" value={overview?.summary.escalations_open ?? 0} tone="warn" />
        <StatCard label="Failures logged" value={overview?.summary.failures_total ?? 0} tone="warn" />
        <StatCard label="Repeated failures" value={overview?.summary.repeated_failure_tasks ?? 0} tone="warn" />
      </section>

      <section className="overview-grid">
        {overview?.onboarding?.mode === "brownfield" ? (
          <article className="data-panel">
            <header className="data-panel__header">
              <div>
                <h2>Brownfield onboarding</h2>
                <p>Imported repo understanding must be explicitly reviewed before the seeded work is released.</p>
              </div>
              <button
                type="button"
                className="task-action task-action--secondary"
                disabled={pendingBrownfieldRescan}
                onClick={() => void handleBrownfieldRescan()}
              >
                {pendingBrownfieldRescan ? "Rescanning..." : "Rescan import"}
              </button>
            </header>
              <div className="data-list">
                <div className="data-list__item">
                <div>
                  <strong>Status</strong>
                  <p>{overview.onboarding.review_status.replaceAll("_", " ")}</p>
                </div>
                <div className="data-list__meta">
                  <span>{overview.onboarding.discovery_summary.primary_language ?? "unknown stack"}</span>
                  <span>{overview.onboarding.discovery_summary.total_files ?? 0} files scanned</span>
                </div>
              </div>
                <div className="data-list__item">
                  <div>
                    <strong>Discovery summary</strong>
                    <p>
                      {overview.onboarding.discovery_summary.package_managers?.join(", ") || "no package manager detected"}
                  </p>
                </div>
                  <div className="data-list__meta">
                    <span>{overview.onboarding.pending_gated_tasks} gated tasks</span>
                    <span>{overview.onboarding.review_task_status ?? "no review task"}</span>
                  </div>
                </div>
                {overview.onboarding.last_scanned_at ? (
                  <div className="data-list__item">
                    <div>
                      <strong>Latest rescan</strong>
                      <p>{overview.onboarding.last_scanned_by ?? "unknown actor"}</p>
                      {overview.onboarding.drift_summary?.summary ? <p>{overview.onboarding.drift_summary.summary}</p> : null}
                      {(overview.onboarding.drift_summary?.changes?.length ?? 0) > 0
                        ? overview.onboarding.drift_summary?.changes?.map((item) => <p key={item}>{item}</p>)
                        : null}
                    </div>
                    <div className="data-list__meta">
                      <span>{new Date(overview.onboarding.last_scanned_at).toLocaleString()}</span>
                      <span>{overview.onboarding.drift_summary?.detected ? "drift detected" : "no drift"}</span>
                    </div>
                  </div>
                ) : null}
                {overview.onboarding.repo_plan_preview ? (
                  <div className="data-list__item">
                    <div>
                      <strong>Repo-grounded plan</strong>
                      <p>
                        {overview.onboarding.repo_plan_preview.generated_task_count} synthesized tasks ·{" "}
                        {overview.onboarding.repo_plan_preview.verification_task_count} verification recipes ·{" "}
                        {overview.onboarding.repo_plan_preview.repo_area_task_count} repo areas
                      </p>
                      {(overview.onboarding.repo_plan_state?.last_refreshed_at ?? null) ? (
                        <p>
                          Last refreshed by {overview.onboarding.repo_plan_state?.last_refreshed_by ?? "unknown actor"}
                          {" · "}
                          {new Date(overview.onboarding.repo_plan_state?.last_refreshed_at ?? "").toLocaleString()}
                          {overview.onboarding.repo_plan_state?.stale ? " · stale after onboarding changes" : ""}
                        </p>
                      ) : (
                        <p>Preview only until onboarding is approved and the synthesized backlog is refreshed.</p>
                      )}
                      {brownfieldTrust ? <p>{brownfieldTrust.summary}</p> : null}
                      {brownfieldTrust ? <p>{brownfieldTrust.detail}</p> : null}
                      {brownfieldTrust ? <p>Recommended action: {brownfieldTrust.recommended_action}</p> : null}
                      {overview.onboarding.repo_plan_state?.lineage?.recent_refreshes?.[0] ? (
                        <p>
                          Latest refresh: {overview.onboarding.repo_plan_state.lineage.recent_refreshes[0].created_count} created ·{" "}
                          {overview.onboarding.repo_plan_state.lineage.recent_refreshes[0].updated_count} updated ·{" "}
                          {overview.onboarding.repo_plan_state.lineage.recent_refreshes[0].cancelled_count} superseded
                        </p>
                      ) : null}
                      {(overview.onboarding.repo_plan_state?.lineage?.superseded_items?.length ?? 0) > 0
                        ? overview.onboarding.repo_plan_state?.lineage?.superseded_items.slice(0, 3).map((item) => (
                            <p key={item.task_id}>
                              <strong>{item.issue_key ?? item.title}</strong>
                              {" superseded"}
                              {item.superseded_by?.issue_key || item.superseded_by?.title
                                ? ` by ${item.superseded_by?.issue_key ?? item.superseded_by?.title}`
                                : ""}
                            </p>
                          ))
                        : null}
                      {overview.onboarding.repo_plan_preview.items?.map((item) => (
                        <p key={item.synthesis_key}>
                          <strong>{item.title}</strong>
                          {item.issue_key ? ` · ${item.issue_key}` : ""}
                          {item.status ? ` · ${item.status.replaceAll("_", " ")}` : ""}
                          {item.command ? ` · ${item.command}` : ""}
                          {(item.paths?.length ?? 0) > 0 ? ` · ${item.paths.join(", ")}` : ""}
                          {(item.linked_items?.length ?? 0) > 0
                            ? ` · linked ${item.linked_items
                                ?.map((linked) =>
                                  linked.issue_key
                                    ? `${linked.direction === "incoming" ? "from" : "to"} ${linked.issue_key}`
                                    : null
                                )
                                .filter(Boolean)
                                .join(", ")}`
                            : ""}
                        </p>
                      ))}
                    </div>
                    <div className="data-list__meta">
                      <span>{overview.onboarding.repo_plan_state?.active_task_count ?? 0} active synthesized tasks</span>
                      {brownfieldTrust ? (
                        <span>
                          {brownfieldTrust.state.replaceAll("_", " ")} · drift {brownfieldTrust.drift_severity}
                        </span>
                      ) : null}
                      {overview.onboarding.repo_plan_state?.lineage ? (
                        <span>
                          {overview.onboarding.repo_plan_state.lineage.superseded_task_count} superseded ·{" "}
                          {overview.onboarding.repo_plan_state.lineage.historical_task_count} historical
                        </span>
                      ) : null}
                      {overview.onboarding.review_status === "approved" ? (
                        <button
                          type="button"
                          className="task-action task-action--secondary"
                          disabled={pendingRepoPlanRefresh}
                          onClick={() => void handleRefreshRepoPlan()}
                        >
                          {pendingRepoPlanRefresh ? "Refreshing..." : "Refresh repo plan"}
                        </button>
                      ) : null}
                    </div>
                  </div>
                ) : null}
                {(overview.onboarding.discovery_summary.workflow_details?.length ?? 0) > 0 ||
                (overview.onboarding.discovery_summary.workflow_labels?.length ?? 0) > 0 ? (
                  <div className="data-list__item">
                    <div>
                      <strong>Imported workflows</strong>
                      <p>{overview.onboarding.discovery_summary.workflow_labels?.join(", ")}</p>
                      {overview.onboarding.discovery_summary.workflow_details?.map((item) => (
                        <p key={`${item.label}-${item.path ?? ""}`}>
                          <strong>{item.label}</strong>
                          {item.path ? ` · ${item.path}` : ""}
                          {item.detail ? ` · ${item.detail}` : ""}
                          {" · "}
                          <button
                            type="button"
                            className="inline-link-button"
                            disabled={pendingOnboardingReviewUpdate === `workflow:${item.label}`}
                            onClick={() => void handleToggleAcceptedWorkflow(item.label)}
                          >
                            {pendingOnboardingReviewUpdate === `workflow:${item.label}`
                              ? "Saving..."
                              : overview.onboarding?.review_overrides?.accepted_workflow_labels.includes(item.label)
                                ? "Exclude"
                                : "Include"}
                          </button>
                          {item.path ? (
                            <>
                              {" · "}
                              <button
                                type="button"
                                className="inline-link-button"
                                disabled={pendingRepoPath === item.path}
                                onClick={() => void handleOpenRepoFile(item.path ?? "")}
                              >
                                {pendingRepoPath === item.path ? "Opening..." : "Open file"}
                              </button>
                            </>
                          ) : null}
                        </p>
                      ))}
                    </div>
                    <div className="data-list__meta">
                      <span>{overview.onboarding.discovery_summary.workflow_details?.length ?? 0} signals</span>
                    </div>
                  </div>
                ) : null}
                {(overview.onboarding.discovery_summary.runbook_commands?.length ?? 0) > 0 ? (
                  <div className="data-list__item">
                    <div>
                      <strong>Imported runbook</strong>
                      {overview.onboarding.discovery_summary.runbook_commands?.map((item) => (
                        <p key={`${item.label}-${item.command ?? ""}-${item.path ?? ""}`}>
                          <strong>{item.label}</strong>
                          {item.command ? ` · ${item.command}` : ""}
                          {item.path ? ` · ${item.path}` : ""}
                          {item.detail ? ` · ${item.detail}` : ""}
                          {item.review_note ? ` · ${item.review_note}` : ""}
                          {" · "}
                          <button
                            type="button"
                            className="inline-link-button"
                            disabled={pendingOnboardingReviewUpdate === `runbook:${item.label}`}
                            onClick={() => void handleToggleAcceptedRunbook(item.label)}
                          >
                            {pendingOnboardingReviewUpdate === `runbook:${item.label}`
                              ? "Saving..."
                              : overview.onboarding?.review_overrides?.accepted_runbook_labels.includes(item.label)
                                ? "Exclude"
                                : "Include"}
                          </button>
                          {item.path ? (
                            <>
                              {" · "}
                              <button
                                type="button"
                                className="inline-link-button"
                                disabled={pendingRepoPath === item.path}
                                onClick={() => void handleOpenRepoFile(item.path ?? "")}
                              >
                                {pendingRepoPath === item.path ? "Opening..." : "Open file"}
                              </button>
                            </>
                          ) : null}
                        </p>
                      ))}
                    </div>
                    <div className="data-list__meta">
                      <span>{overview.onboarding.discovery_summary.runbook_commands?.length ?? 0} recipes</span>
                    </div>
                  </div>
                ) : null}
                {(overview.onboarding.discovery_summary.repo_areas?.length ?? 0) > 0 ? (
                  <div className="data-list__item">
                    <div>
                      <strong>Imported repo areas</strong>
                      <p>{overview.onboarding.discovery_summary.repo_areas?.join(", ")}</p>
                    </div>
                    <div className="data-list__meta">
                      <span>{overview.onboarding.discovery_summary.repo_areas?.length ?? 0} areas</span>
                    </div>
                  </div>
                ) : null}
                {(overview.onboarding.discovery_summary.codebase_map?.length ?? 0) > 0 ? (
                  <div className="data-list__item">
                    <div>
                      <strong>Imported codebase map</strong>
                      {overview.onboarding.discovery_summary.codebase_map?.map((item) => (
                        <p key={`${item.name}-${item.path ?? ""}`}>
                          <strong>{item.name}</strong>
                          {` · ${item.kind.replaceAll("_", " ")}`}
                          {item.path ? ` · ${item.path}` : ""}
                          {` · ${item.primary_language}`}
                          {` · ${item.file_count} files`}
                          {item.summary ? ` · ${item.summary}` : ""}
                          {item.path ? (
                            <>
                              {" · "}
                              <button
                                type="button"
                                className="inline-link-button"
                                disabled={pendingOnboardingReviewUpdate === `ignore:${item.path}`}
                                onClick={() => void handleToggleIgnoredPath(item.path ?? "")}
                              >
                                {pendingOnboardingReviewUpdate === `ignore:${item.path}`
                                  ? "Saving..."
                                  : overview.onboarding?.review_overrides?.ignored_paths.includes(item.path)
                                    ? "Unignore"
                                    : "Ignore"}
                              </button>
                            </>
                          ) : null}
                          {item.path ? (
                            <>
                              {" · "}
                              <button
                                type="button"
                                className="inline-link-button"
                                disabled={pendingRepoPath === item.path}
                                onClick={() => void handleBrowseRepoPath(item.path ?? "")}
                              >
                                {pendingRepoPath === item.path ? "Loading..." : "Browse"}
                              </button>
                            </>
                          ) : null}
                          {(item.sample_files?.length ?? 0) > 0 ? (
                            <>
                              <br />
                              <span>Sample files: </span>
                              {item.sample_files?.map((samplePath, index) => (
                                <span key={samplePath}>
                                  {index > 0 ? ", " : ""}
                                  <button
                                    type="button"
                                    className="inline-link-button"
                                    disabled={pendingRepoPath === samplePath}
                                    onClick={() => void handleOpenRepoFile(samplePath)}
                                  >
                                    {samplePath}
                                  </button>
                                </span>
                              ))}
                            </>
                          ) : null}
                        </p>
                      ))}
                    </div>
                    <div className="data-list__meta">
                      <span>{overview.onboarding.discovery_summary.codebase_map?.length ?? 0} mapped areas</span>
                    </div>
                  </div>
                ) : null}
                {overview.onboarding.reviewed_at ? (
                <div className="data-list__item">
                  <div>
                    <strong>Last decision</strong>
                    <p>{overview.onboarding.reviewed_by ?? "unknown actor"}</p>
                  </div>
                  <div className="data-list__meta">
                    <span>{new Date(overview.onboarding.reviewed_at).toLocaleString()}</span>
                  </div>
                </div>
              ) : null}
            </div>
            {overview.onboarding.review_required &&
            overview.onboarding.review_task_id &&
            overview.onboarding.review_task_status === "review" ? (
              <div className="task-card__actions">
                <button
                  type="button"
                  className="task-action task-action--approve"
                  disabled={pendingOnboardingReview === "approve" || pendingOnboardingReview === "reject"}
                  onClick={() => void handleOnboardingReview("approve")}
                >
                  {pendingOnboardingReview === "approve" ? "Approving..." : "Approve imported understanding"}
                </button>
                <button
                  type="button"
                  className="task-action task-action--reject"
                  disabled={pendingOnboardingReview === "approve" || pendingOnboardingReview === "reject"}
                  onClick={() => void handleOnboardingReview("reject")}
                >
                  {pendingOnboardingReview === "reject" ? "Rejecting..." : "Request changes"}
                </button>
              </div>
            ) : null}
          </article>
        ) : null}

        {overview?.onboarding?.mode === "brownfield" ? (
          <article className="data-panel">
            <header className="data-panel__header">
              <h2>Imported repository</h2>
              <p>Browse the imported source tree and preview files directly from the brownfield source root.</p>
            </header>
            <div className="data-list">
              <div className="data-list__item">
                <div>
                  <strong>Current area</strong>
                  <p>{repoTree?.path || "."}</p>
                </div>
                <div className="data-list__meta">
                  {repoTree?.parent_path ? (
                    <button
                      type="button"
                      className="task-action task-action--secondary"
                      disabled={pendingRepoPath === repoTree.parent_path}
                      onClick={() => void handleBrowseRepoPath(repoTree.parent_path ?? "")}
                    >
                      {pendingRepoPath === repoTree.parent_path ? "Loading..." : "Up one level"}
                    </button>
                  ) : (
                    <span>{repoTree?.entries.length ?? 0} entries</span>
                  )}
                </div>
              </div>
              {(repoTree?.entries ?? []).map((entry) => (
                <div key={entry.path} className="data-list__item">
                  <div>
                    <strong>{entry.name}</strong>
                    <p>{entry.path}</p>
                  </div>
                  <div className="data-list__meta">
                    <span>{entry.kind}</span>
                    {entry.kind === "directory" ? (
                      <button
                        type="button"
                        className="task-action task-action--secondary"
                        disabled={pendingRepoPath === entry.path}
                        onClick={() => void handleBrowseRepoPath(entry.path)}
                      >
                        {pendingRepoPath === entry.path ? "Loading..." : "Browse"}
                      </button>
                    ) : (
                      <button
                        type="button"
                        className="task-action task-action--secondary"
                        disabled={pendingRepoPath === entry.path}
                        onClick={() => void handleOpenRepoFile(entry.path)}
                      >
                        {pendingRepoPath === entry.path ? "Opening..." : "Preview"}
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
            {repoFile ? (
              <div className="repo-preview">
                <div className="repo-preview__header">
                  <strong>{repoFile.path}</strong>
                  <span>
                    {repoFile.previewable ? repoFile.content_kind : "binary"} · {repoFile.size} bytes
                    {repoFile.truncated ? " · truncated" : ""}
                  </span>
                </div>
                <pre>{repoFile.content ?? "Preview unavailable for this file type."}</pre>
              </div>
            ) : null}
          </article>
        ) : null}

        <article className="data-panel">
          <header className="data-panel__header">
            <h2>Supervisor pass</h2>
            <p>Manual orchestration trigger for readiness refresh, assignment, and stale-session checks.</p>
          </header>
          <div className="data-list">
            <div className="data-list__item">
              <div>
                <strong>Ready changes</strong>
                <p>{supervisorResult ? supervisorResult.ready_changes.length : 0} tasks updated in the last manual pass</p>
              </div>
              <div className="data-list__meta">
                <span>{supervisorResult ? supervisorResult.assigned_count : 0} assigned</span>
                <span>{supervisorResult ? supervisorResult.stale_sessions.length : 0} stale</span>
              </div>
            </div>
            {(supervisorResult?.allocations ?? []).map((allocation) => (
              <div key={`${allocation.agent_id}-${allocation.task_id}`} className="data-list__item">
                <div>
                  <strong>{allocation.task_title ?? allocation.task_id}</strong>
                  <p>{allocation.agent_id}</p>
                </div>
                <div className="data-list__meta">
                  <span>{allocation.status}</span>
                  <span>{allocation.assigned ? "new assignment" : "existing reservation"}</span>
                </div>
              </div>
            ))}
          </div>
        </article>

        <article className="data-panel">
          <header className="data-panel__header">
            <h2>Active work</h2>
            <p>What needs attention right now.</p>
          </header>
          <div className="data-list">
            {(overview?.active_work ?? []).map((item) => (
              <div key={item.task_id} className="data-list__item">
                <div>
                  <strong>{item.title}</strong>
                  <p>{item.goal_title ?? "Unlinked goal"}</p>
                </div>
                <div className="data-list__meta">
                  <span>{item.agent_name ?? "Unassigned"}</span>
                  <span>{item.status}</span>
                </div>
              </div>
            ))}
          </div>
        </article>

        <article className="data-panel">
          <header className="data-panel__header">
            <h2>Recent activity</h2>
            <p>Latest system movement from the blackboard.</p>
          </header>
          <div className="data-list">
            {(overview?.recent_activity ?? []).map((item, index) => (
              <div key={`${item.action}-${index}`} className="data-list__item">
                <div>
                  <strong>{item.action}</strong>
                  <p>{item.description}</p>
                </div>
                <div className="data-list__meta">
                  <span>{item.severity}</span>
                  <span>{new Date(item.created_at).toLocaleTimeString()}</span>
                </div>
              </div>
            ))}
          </div>
        </article>

        <article className="data-panel">
          <header className="data-panel__header">
            <h2>Recent failures</h2>
            <p>Failure memory for the latest failed or timed-out work.</p>
          </header>
          <div className="data-list">
            {(overview?.recent_failures ?? []).map((item) => (
              <div key={item.failure_id ?? `${item.task_id}-${item.created_at}`} className="data-list__item">
                <div>
                  <strong>{item.task_title ?? item.task_id ?? "Unlinked failure"}</strong>
                  <p>{item.summary}</p>
                  {item.quarantined_artifact_count ? (
                    <p>
                      Quarantined artifacts: {item.quarantined_artifact_count}
                    </p>
                  ) : null}
                </div>
                <div className="data-list__meta">
                  <span>{item.failure_type}</span>
                  <span>{new Date(item.created_at).toLocaleTimeString()}</span>
                  {item.operator_action ? (
                    <button
                      type="button"
                      className="task-action task-action--approve"
                      disabled={pendingFailureAction?.startsWith(`${item.failure_id}:`) ?? false}
                      onClick={() => item.failure_id && void handleOverviewFailureAction(item.failure_id, "primary")}
                    >
                      {pendingFailureAction === `${item.failure_id}:${item.operator_action.action}`
                        ? item.operator_action.action === "restore_and_requeue_quarantine_entry"
                          ? "Restoring..."
                          : item.operator_action.action === "dismiss_quarantine_entry"
                            ? "Dismissing..."
                            : item.operator_action.action === "reopen_quarantine_entry"
                              ? "Reopening..."
                              : item.operator_action.action === "restore_failure_artifacts"
                                ? "Restoring..."
                                : "Recovering..."
                        : item.operator_action.label}
                    </button>
                  ) : null}
                  {item.secondary_operator_action ? (
                    <button
                      type="button"
                      className="task-action task-action--secondary"
                      disabled={pendingFailureAction?.startsWith(`${item.failure_id}:`) ?? false}
                      onClick={() => item.failure_id && void handleOverviewFailureAction(item.failure_id, "secondary")}
                    >
                      {pendingFailureAction === `${item.failure_id}:${item.secondary_operator_action.action}`
                        ? item.secondary_operator_action.action === "dismiss_quarantine_entry"
                          ? "Dismissing..."
                          : item.secondary_operator_action.label
                        : item.secondary_operator_action.label}
                    </button>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        </article>

        <article className="data-panel">
          <header className="data-panel__header">
            <h2>Repeated failures</h2>
            <p>Tasks that are still over the repeated-failure threshold and may need explicit operator triage.</p>
          </header>
          <div className="data-list">
            {(overview?.repeated_failures ?? []).map((item) => (
              <div key={item.task_id} className="data-list__item">
                <div>
                  <strong>{item.task_title ?? item.task_id}</strong>
                  <p>{item.failure_count} logged failures</p>
                </div>
                <div className="data-list__meta">
                  <span>{item.task_id}</span>
                  <span>
                    {item.latest_failure_at ? new Date(item.latest_failure_at).toLocaleTimeString() : "No timestamp"}
                  </span>
                  {item.operator_action ? (
                    <button
                      type="button"
                      className="task-action task-action--approve"
                      disabled={pendingRepeatedFailureAction === `${item.task_id}:${item.operator_action.action}`}
                      onClick={() => void handleOverviewRepeatedFailureAction(item.task_id)}
                    >
                      {pendingRepeatedFailureAction === `${item.task_id}:${item.operator_action.action}`
                        ? "Resolving..."
                        : item.operator_action.label}
                    </button>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        </article>
      </section>
    </section>
  );
}
