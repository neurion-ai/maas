"""FastAPI application for MAAS."""

from typing import List, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from maas.db import connect, project_paths
from maas.paths import ProjectPaths
from maas.services.alerts import fetch_alerts, update_alert_status
from maas.services.artifacts import (
    build_artifact_export_bundle,
    fetch_artifact_comparison,
    fetch_artifact_detail,
    fetch_artifacts,
    resolve_artifact_download,
)
from maas.services.board import fetch_board
from maas.services.dashboard import fetch_agent_roster, fetch_goal_tree, fetch_overview
from maas.services.escalations import approve_escalation, fetch_escalations, reject_escalation, request_escalation
from maas.services.failure_memory import fetch_failure_log, fetch_quarantine_queue
from maas.services.git_workspaces import capture_task_git_diff, fetch_task_git_workspace, prepare_task_git_workspace
from maas.services.lifecycle import end_session, heartbeat, log_activity, produce_artifact, start_session
from maas.services.live import build_live_snapshot, sse_stream, websocket_stream
from maas.services.orchestrator import run_orchestrator_once
from maas.services.provider_runtime import (
    process_next_provider_job,
    process_provider_job,
    provider_runtime_overview,
    provider_job_queue,
    queue_provider_task,
    run_provider_preflight,
    run_provider_task,
    set_provider_mode,
    set_provider_settings,
)
from maas.services.provider_workers import run_provider_worker_once
from maas.services.portfolio import fetch_portfolio
from maas.services.projects import (
    archive_project,
    create_project,
    list_projects,
    rescan_brownfield_project,
    resolve_project_id,
    restore_project,
    update_brownfield_onboarding_review,
)
from maas.services.queue_capacity import update_project_queue_capacity_policy
from maas.services.recovery_policy import fetch_project_recovery_overview, update_project_recovery_policy
from maas.services.repo_browser import fetch_repo_file_preview, fetch_repo_tree
from maas.services.repo_plan import refresh_repo_grounded_plan
from maas.services.scheduler import allocate_ready_tasks, assign_next_task, evaluate_task, refresh_ready_tasks, resolve_ready_tasks
from maas.services.scheduler_policy import update_project_scheduler_policy
from maas.services.security import fetch_task_capabilities
from maas.services.steering import (
    dismiss_quarantine_entry,
    recover_and_requeue_task,
    finish_task_replan,
    halt_task,
    mark_task_for_replan,
    pause_agent,
    purge_session_artifacts,
    purge_task_artifacts,
    reassign_task,
    recover_agent,
    recover_task,
    release_task_retry_backoff,
    reset_task_circuit_breaker,
    reset_task_retry_state,
    reopen_quarantine_entry,
    restore_and_requeue_quarantine_entry,
    restore_quarantine_entry,
    restore_failure_artifacts,
    resolve_task_repeated_failures,
    reprioritize_task,
    resume_agent,
    set_task_retry_limit,
    review_task,
)
from maas.supervisor import run_supervisor_once
from maas.services.verification import fetch_verification_runs, run_task_verification


class LifecycleHeartbeatRequest(BaseModel):
    session_id: str
    progress_pct: int
    status_message: str


class StartSessionRequest(BaseModel):
    project_id: str
    agent_id: str
    task_id: str
    provider_type: str
    status_message: str = ""


class ActivityRequest(BaseModel):
    project_id: str
    agent_id: str
    task_id: str = None
    action: str
    category: str
    description: str
    severity: str = "info"


class ArtifactRequest(BaseModel):
    project_id: str
    session_id: str
    task_id: str
    artifact_type: str
    path: str


class EndSessionRequest(BaseModel):
    session_id: str
    outcome: str
    summary: str


class ReviewTaskRequest(BaseModel):
    actor_id: str
    decision: str


class ReprioritizeTaskRequest(BaseModel):
    actor_id: str
    priority: int


class ReassignTaskRequest(BaseModel):
    actor_id: str
    agent_id: str


class TaskRetryLimitRequest(BaseModel):
    actor_id: str
    auto_retry_limit: Optional[int] = None


class AgentActionRequest(BaseModel):
    actor_id: str


class AlertActionRequest(BaseModel):
    actor_id: str


class AssignTaskRequest(BaseModel):
    actor_id: str = "system_allocator"


class AllocateTasksRequest(BaseModel):
    actor_id: str = "system_allocator"
    limit: int = None
    project_id: Optional[str] = None


class SupervisorRunRequest(BaseModel):
    allocate_limit: int = None
    project_id: Optional[str] = None


class OrchestratorRunRequest(BaseModel):
    allocate_limit: int = None
    provider_job_limit: int = 2
    project_id: Optional[str] = None


class EscalationRequestPayload(BaseModel):
    project_id: str
    actor_id: str
    action_type: str
    resource_type: str
    resource_id: str
    reason: str = ""
    payload: dict = {}


class EscalationDecisionPayload(BaseModel):
    actor_id: str
    resolution_note: str = ""


class ProviderRunRequest(BaseModel):
    project_id: str
    agent_id: str
    task_id: str
    artifact_path: Optional[str] = None


class ProviderQueueRequest(BaseModel):
    actor_id: str
    project_id: str
    agent_id: str
    task_id: str
    artifact_path: Optional[str] = None


class ProviderJobProcessRequest(BaseModel):
    actor_id: str


class ProviderJobProcessNextRequest(BaseModel):
    actor_id: str
    project_id: Optional[str] = None
    provider_id: Optional[str] = None


class ProviderWorkerRunRequest(BaseModel):
    worker_id: str
    project_id: Optional[str] = None
    provider_id: Optional[str] = None


class ProviderModeRequest(BaseModel):
    actor_id: str
    mode: str
    project_id: Optional[str] = None


class ProviderSettingsRequest(BaseModel):
    actor_id: str
    settings: dict = {}
    project_id: Optional[str] = None


class ProviderPreflightRequest(BaseModel):
    actor_id: str
    project_id: Optional[str] = None


class RecoveryPolicyRequest(BaseModel):
    actor_id: str
    policy: dict = {}
    project_id: Optional[str] = None


class ProjectCreateRequest(BaseModel):
    actor_id: str = "agent_allocator"
    name: str
    description: str = ""
    project_type: str = "custom"
    mode: str = "auto"
    source_root: Optional[str] = None


class ProjectOnboardingReviewUpdateRequest(BaseModel):
    actor_id: str = "agent_allocator"
    ignored_paths: List[str] = []
    accepted_workflow_labels: Optional[List[str]] = None
    accepted_runbook_labels: Optional[List[str]] = None


class ProjectSchedulerPolicyRequest(BaseModel):
    actor_id: str = "agent_allocator"
    fair_share_weight: int
    max_active_sessions: int


class ProjectQueueCapacityRequest(BaseModel):
    actor_id: str = "agent_allocator"
    queue_mode: str
    max_running_jobs: int


def _parse_limit(value, default):
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="limit must be an integer")
    if parsed <= 0:
        raise HTTPException(status_code=400, detail="limit must be greater than zero")
    return parsed


def _parse_offset(value, default=0):
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="offset must be an integer")
    if parsed < 0:
        raise HTTPException(status_code=400, detail="offset must be zero or greater")
    return parsed


def _selected_project_id(connection, project_id=None):
    if project_id is None:
        return resolve_project_id(connection)
    resolved = resolve_project_id(connection, project_id)
    if resolved is None:
        raise HTTPException(status_code=404, detail="project not found")
    return resolved


def create_app(project_root="."):
    app = FastAPI(title="MAAS", version="0.1.0")
    paths = ProjectPaths(project_root)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health():
        return {"status": "ok", "project_root": paths.root}

    @app.get("/api/projects")
    def projects():
        connection = connect(paths)
        try:
            return {"projects": list_projects(connection)}
        finally:
            connection.close()

    @app.post("/api/projects")
    def projects_create(payload: ProjectCreateRequest):
        connection = connect(paths)
        try:
            return create_project(
                connection,
                paths,
                actor_id=payload.actor_id,
                name=payload.name,
                description=payload.description,
                project_type=payload.project_type,
                mode=payload.mode,
                source_root=payload.source_root,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/projects/{project_id}/actions/archive")
    def projects_archive(project_id: str, payload: AgentActionRequest):
        connection = connect(paths)
        try:
            return archive_project(connection, project_id, payload.actor_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/projects/{project_id}/actions/restore")
    def projects_restore(project_id: str, payload: AgentActionRequest):
        connection = connect(paths)
        try:
            return restore_project(connection, project_id, payload.actor_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/projects/{project_id}/actions/rescan-brownfield")
    def projects_rescan_brownfield(project_id: str, payload: AgentActionRequest):
        connection = connect(paths)
        try:
            return rescan_brownfield_project(connection, paths, project_id, payload.actor_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/projects/{project_id}/actions/update-onboarding-review")
    def projects_update_onboarding_review(project_id: str, payload: ProjectOnboardingReviewUpdateRequest):
        connection = connect(paths)
        try:
            return update_brownfield_onboarding_review(
                connection,
                paths,
                project_id,
                payload.actor_id,
                {
                    "ignored_paths": payload.ignored_paths,
                    "accepted_workflow_labels": payload.accepted_workflow_labels,
                    "accepted_runbook_labels": payload.accepted_runbook_labels,
                },
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/projects/{project_id}/actions/update-scheduler-policy")
    def projects_update_scheduler_policy(project_id: str, payload: ProjectSchedulerPolicyRequest):
        connection = connect(paths)
        try:
            return update_project_scheduler_policy(
                connection,
                project_id,
                payload.actor_id,
                {
                    "fair_share_weight": payload.fair_share_weight,
                    "max_active_sessions": payload.max_active_sessions,
                },
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/projects/{project_id}/actions/update-provider-capacity")
    def projects_update_provider_capacity(project_id: str, payload: ProjectQueueCapacityRequest):
        connection = connect(paths)
        try:
            return update_project_queue_capacity_policy(
                connection,
                project_id=project_id,
                actor_id=payload.actor_id,
                policy={
                    "queue_mode": payload.queue_mode,
                    "max_running_jobs": payload.max_running_jobs,
                },
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/projects/{project_id}/actions/refresh-repo-plan")
    def projects_refresh_repo_plan(project_id: str, payload: AgentActionRequest):
        connection = connect(paths)
        try:
            return refresh_repo_grounded_plan(connection, project_id, payload.actor_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.get("/api/live")
    def live(project_id: str = None):
        connection = connect(paths)
        try:
            return build_live_snapshot(connection, project_id=_selected_project_id(connection, project_id))
        finally:
            connection.close()

    @app.get("/api/live/stream")
    def live_stream(project_id: str = None):
        root = paths.root

        def connection_factory():
            return connect(project_paths(root))

        connection = connect(paths)
        try:
            scoped_project_id = _selected_project_id(connection, project_id)
        finally:
            connection.close()

        return StreamingResponse(
            sse_stream(connection_factory, project_id=scoped_project_id),
            media_type="text/event-stream",
        )

    @app.websocket("/api/live/ws")
    async def live_websocket(websocket: WebSocket):
        root = paths.root

        def connection_factory():
            return connect(project_paths(root))

        connection = connect(paths)
        try:
            scoped_project_id = _selected_project_id(connection, websocket.query_params.get("project_id"))
        except HTTPException:
            await websocket.close(code=1008, reason="project not found")
            return
        finally:
            if connection:
                connection.close()

        await websocket.accept()
        try:
            await websocket_stream(websocket.send_json, connection_factory, project_id=scoped_project_id)
        except WebSocketDisconnect:
            return

    @app.get("/api/board")
    def board(
        project_id: str = None,
        search: str = "",
        agent_id: str = None,
        goal_id: str = None,
        priority_min: int = None,
        blocked_only: bool = False,
        review_only: bool = False,
    ):
        connection = connect(paths)
        try:
            scoped_project_id = _selected_project_id(connection, project_id)
            return fetch_board(
                connection,
                filters={
                    "search": search,
                    "agent_id": agent_id,
                    "goal_id": goal_id,
                    "priority_min": priority_min,
                    "blocked_only": blocked_only,
                    "review_only": review_only,
                },
                project_id=scoped_project_id,
            )
        finally:
            connection.close()

    @app.get("/api/goals")
    def goals(project_id: str = None):
        connection = connect(paths)
        try:
            scoped_project_id = _selected_project_id(connection, project_id)
            rows = connection.execute(
                """
                SELECT goal_id, parent_goal_id, title, description, status, goal_type, priority, created_at
                FROM goals
                WHERE project_id = ?
                ORDER BY priority DESC, created_at ASC
                """,
                (scoped_project_id,),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    @app.get("/api/tasks/ready")
    def tasks_ready(project_id: str = None):
        connection = connect(paths)
        try:
            return {"tasks": resolve_ready_tasks(connection, project_id=_selected_project_id(connection, project_id))}
        finally:
            connection.close()

    @app.get("/api/tasks/{task_id}/capabilities")
    def task_capabilities(task_id: str):
        connection = connect(paths)
        try:
            return {"task_id": task_id, "grants": fetch_task_capabilities(connection, task_id)}
        finally:
            connection.close()

    @app.get("/api/goals/tree")
    def goals_tree(project_id: str = None):
        connection = connect(paths)
        try:
            return fetch_goal_tree(connection, project_id=_selected_project_id(connection, project_id))
        finally:
            connection.close()

    @app.get("/api/overview")
    def overview(project_id: str = None):
        connection = connect(paths)
        try:
            return fetch_overview(connection, project_id=_selected_project_id(connection, project_id))
        finally:
            connection.close()

    @app.get("/api/portfolio")
    def portfolio():
        connection = connect(paths)
        try:
            return fetch_portfolio(connection)
        finally:
            connection.close()

    @app.post("/api/orchestrator/run")
    def orchestrator_run(payload: OrchestratorRunRequest):
        connection = connect(paths)
        try:
            selected_project_id = _selected_project_id(connection, payload.project_id) if payload.project_id else None
            return run_orchestrator_once(
                connection,
                paths,
                allocate_limit=payload.allocate_limit,
                provider_job_limit=payload.provider_job_limit,
                project_id=selected_project_id,
            )
        finally:
            connection.close()

    @app.get("/api/repo/tree")
    def repo_tree(path: str = "", project_id: str = None):
        connection = connect(paths)
        try:
            return fetch_repo_tree(connection, project_id=_selected_project_id(connection, project_id), path=path)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.get("/api/repo/file")
    def repo_file(path: str, project_id: str = None):
        connection = connect(paths)
        try:
            return fetch_repo_file_preview(connection, project_id=_selected_project_id(connection, project_id), path=path)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.get("/api/agents")
    def agents(project_id: str = None):
        connection = connect(paths)
        try:
            return fetch_agent_roster(connection, project_id=_selected_project_id(connection, project_id))
        finally:
            connection.close()

    @app.get("/api/activity")
    def activity(limit=20, project_id: str = None):
        connection = connect(paths)
        try:
            scoped_project_id = _selected_project_id(connection, project_id)
            rows = connection.execute(
                """
                SELECT activity_id, project_id, agent_id, task_id, action, category, description, severity, created_at
                FROM activity_log
                WHERE project_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (scoped_project_id, limit),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    @app.get("/api/alerts")
    def alerts(project_id: str = None):
        connection = connect(paths)
        try:
            return fetch_alerts(connection, project_id=_selected_project_id(connection, project_id))
        finally:
            connection.close()

    @app.get("/api/escalations")
    def escalations(project_id: str = None):
        connection = connect(paths)
        try:
            return fetch_escalations(connection, project_id=_selected_project_id(connection, project_id))
        finally:
            connection.close()

    @app.get("/api/failures")
    def failures(limit=20, project_id: str = None):
        connection = connect(paths)
        try:
            return fetch_failure_log(
                connection,
                limit=int(limit),
                project_id=_selected_project_id(connection, project_id),
            )
        finally:
            connection.close()

    @app.get("/api/verifications")
    def verifications(limit=20, task_id: str = None, project_id: str = None):
        connection = connect(paths)
        try:
            scoped_project_id = _selected_project_id(connection, project_id) if project_id is not None else None
            return {"runs": fetch_verification_runs(connection, project_id=scoped_project_id, task_id=task_id, limit=int(limit))}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.get("/api/tasks/{task_id}/git-workspace")
    def task_git_workspace(task_id: str):
        connection = connect(paths)
        try:
            workspace = fetch_task_git_workspace(connection, task_id)
            if workspace is None:
                raise HTTPException(status_code=404, detail="git workspace not prepared")
            return workspace
        finally:
            connection.close()

    @app.get("/api/artifacts")
    def artifacts(
        limit=100,
        offset=0,
        search: str = "",
        state: str = "all",
        provider_type: str = "all",
        artifact_type: str = "all",
        task_id: str = "",
        session_id: str = "",
        missing_only: bool = False,
        project_id: str = None,
    ):
        parsed_limit = _parse_limit(limit, 100)
        parsed_offset = _parse_offset(offset, 0)
        connection = connect(paths)
        try:
            scoped_project_id = _selected_project_id(connection, project_id)
            return fetch_artifacts(
                connection,
                paths,
                limit=parsed_limit,
                offset=parsed_offset,
                filters={
                    "search": search,
                    "state": state,
                    "provider_type": provider_type,
                    "artifact_type": artifact_type,
                    "task_id": task_id,
                    "session_id": session_id,
                    "missing_only": missing_only,
                },
                project_id=scoped_project_id,
            )
        finally:
            connection.close()

    @app.get("/api/artifacts/export")
    def artifact_export(task_id: str = "", session_id: str = ""):
        connection = connect(paths)
        try:
            try:
                bundle = build_artifact_export_bundle(
                    connection,
                    paths,
                    task_id=task_id or None,
                    session_id=session_id or None,
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()
        if bundle is None:
            raise HTTPException(status_code=404, detail="artifact export scope not found")
        return FileResponse(
            bundle["absolute_path"],
            media_type=bundle["content_type"],
            filename=bundle["file_name"],
        )

    @app.post("/api/tasks/{task_id}/artifacts/actions/purge")
    def task_artifact_purge(task_id: str, payload: AgentActionRequest):
        connection = connect(paths)
        try:
            return purge_task_artifacts(connection, paths, task_id, payload.actor_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/sessions/{session_id}/artifacts/actions/purge")
    def session_artifact_purge(session_id: str, payload: AgentActionRequest):
        connection = connect(paths)
        try:
            return purge_session_artifacts(connection, paths, session_id, payload.actor_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.get("/api/artifacts/{artifact_id}")
    def artifact_detail(artifact_id: str):
        connection = connect(paths)
        try:
            detail = fetch_artifact_detail(connection, paths, artifact_id)
        finally:
            connection.close()
        if detail is None:
            raise HTTPException(status_code=404, detail="artifact not found")
        return detail

    @app.get("/api/artifacts/{artifact_id}/download")
    def artifact_download(artifact_id: str):
        connection = connect(paths)
        try:
            resolved = resolve_artifact_download(connection, paths, artifact_id)
        finally:
            connection.close()
        if resolved is None:
            raise HTTPException(status_code=404, detail="artifact file not found")
        return FileResponse(
            resolved["absolute_path"],
            media_type=resolved["content_type"],
            filename=resolved["file_name"],
        )

    @app.get("/api/artifacts/{artifact_id}/compare/{other_artifact_id}")
    def artifact_compare(artifact_id: str, other_artifact_id: str):
        connection = connect(paths)
        try:
            comparison = fetch_artifact_comparison(connection, paths, artifact_id, other_artifact_id)
        finally:
            connection.close()
        if comparison is None:
            raise HTTPException(status_code=404, detail="artifact not found")
        return comparison

    @app.post("/api/failures/{failure_id}/actions/restore-artifacts")
    def failure_restore_artifacts_action(failure_id: str, payload: AgentActionRequest):
        connection = connect(paths)
        try:
            return restore_failure_artifacts(connection, paths, failure_id, payload.actor_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.get("/api/quarantine")
    def quarantine(limit=20, project_id: str = None):
        connection = connect(paths)
        try:
            return fetch_quarantine_queue(
                connection,
                limit=int(limit),
                project_id=_selected_project_id(connection, project_id),
            )
        finally:
            connection.close()

    @app.post("/api/quarantine/{queue_id}/actions/restore")
    def quarantine_restore_action(queue_id: str, payload: AgentActionRequest):
        connection = connect(paths)
        try:
            return restore_quarantine_entry(connection, paths, queue_id, payload.actor_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/quarantine/{queue_id}/actions/restore-and-requeue")
    def quarantine_restore_and_requeue_action(queue_id: str, payload: AgentActionRequest):
        connection = connect(paths)
        try:
            return restore_and_requeue_quarantine_entry(connection, paths, queue_id, payload.actor_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/quarantine/{queue_id}/actions/dismiss")
    def quarantine_dismiss_action(queue_id: str, payload: AgentActionRequest):
        connection = connect(paths)
        try:
            return dismiss_quarantine_entry(connection, queue_id, payload.actor_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/quarantine/{queue_id}/actions/reopen")
    def quarantine_reopen_action(queue_id: str, payload: AgentActionRequest):
        connection = connect(paths)
        try:
            return reopen_quarantine_entry(connection, queue_id, payload.actor_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.get("/api/providers")
    def providers(project_id: str = None):
        connection = connect(paths)
        try:
            scoped_project_id = _selected_project_id(connection, project_id)
            return provider_runtime_overview(connection=connection, project_id=scoped_project_id)
        finally:
            connection.close()

    @app.get("/api/provider-jobs")
    def provider_jobs(project_id: str = None, provider_id: str = None, status: str = None, limit: str = None):
        connection = connect(paths)
        try:
            scoped_project_id = _selected_project_id(connection, project_id)
            return {
                "jobs": provider_job_queue(
                    connection,
                    project_id=scoped_project_id,
                    provider_id=provider_id,
                    status=status,
                    limit=_parse_limit(limit, 20),
                )
            }
        finally:
            connection.close()

    @app.get("/api/recovery-policy")
    def recovery_policy(project_id: str = None):
        connection = connect(paths)
        try:
            return fetch_project_recovery_overview(
                connection,
                project_id=_selected_project_id(connection, project_id),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/escalations/request")
    def escalation_request_action(payload: EscalationRequestPayload):
        connection = connect(paths)
        try:
            return request_escalation(
                connection,
                project_id=payload.project_id,
                actor_id=payload.actor_id,
                action_type=payload.action_type,
                resource_type=payload.resource_type,
                resource_id=payload.resource_id,
                reason=payload.reason,
                payload=payload.payload,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/escalations/{escalation_id}/actions/approve")
    def escalation_approve_action(escalation_id: str, payload: EscalationDecisionPayload):
        connection = connect(paths)
        try:
            return approve_escalation(connection, escalation_id, payload.actor_id, payload.resolution_note)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/escalations/{escalation_id}/actions/reject")
    def escalation_reject_action(escalation_id: str, payload: EscalationDecisionPayload):
        connection = connect(paths)
        try:
            return reject_escalation(connection, escalation_id, payload.actor_id, payload.resolution_note)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/providers/{provider_id}/actions/run-task")
    def provider_run_task_action(provider_id: str, payload: ProviderRunRequest):
        connection = connect(paths)
        try:
            return run_provider_task(
                connection,
                project_paths=paths,
                project_id=payload.project_id,
                agent_id=payload.agent_id,
                task_id=payload.task_id,
                provider_type=provider_id,
                artifact_path=payload.artifact_path,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/providers/{provider_id}/actions/queue-task")
    def provider_queue_task_action(provider_id: str, payload: ProviderQueueRequest):
        connection = connect(paths)
        try:
            return queue_provider_task(
                connection,
                project_paths=paths,
                provider_id=provider_id,
                actor_id=payload.actor_id,
                project_id=payload.project_id,
                agent_id=payload.agent_id,
                task_id=payload.task_id,
                artifact_path=payload.artifact_path,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/provider-jobs/{job_id}/actions/process")
    def provider_process_job_action(job_id: str, payload: ProviderJobProcessRequest):
        connection = connect(paths)
        try:
            return process_provider_job(
                connection,
                project_paths=paths,
                job_id=job_id,
                actor_id=payload.actor_id,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/provider-jobs/actions/process-next")
    def provider_process_next_job_action(payload: ProviderJobProcessNextRequest):
        connection = connect(paths)
        try:
            return process_next_provider_job(
                connection,
                project_paths=paths,
                actor_id=payload.actor_id,
                project_id=_selected_project_id(connection, payload.project_id) if payload.project_id else None,
                provider_id=payload.provider_id,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/provider-workers/actions/run-once")
    def provider_worker_run_once_action(payload: ProviderWorkerRunRequest):
        connection = connect(paths)
        try:
            return run_provider_worker_once(
                connection,
                project_paths=paths,
                worker_id=payload.worker_id,
                project_id=_selected_project_id(connection, payload.project_id) if payload.project_id else None,
                provider_id=payload.provider_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/providers/{provider_id}/actions/set-mode")
    def provider_set_mode_action(provider_id: str, payload: ProviderModeRequest):
        connection = connect(paths)
        try:
            return set_provider_mode(
                connection,
                provider_id,
                payload.actor_id,
                payload.mode,
                project_id=_selected_project_id(connection, payload.project_id),
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/providers/{provider_id}/actions/set-settings")
    def provider_set_settings_action(provider_id: str, payload: ProviderSettingsRequest):
        connection = connect(paths)
        try:
            return set_provider_settings(
                connection,
                provider_id,
                payload.actor_id,
                payload.settings,
                project_id=_selected_project_id(connection, payload.project_id),
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/providers/{provider_id}/actions/run-preflight")
    def provider_run_preflight_action(provider_id: str, payload: ProviderPreflightRequest):
        connection = connect(paths)
        try:
            return run_provider_preflight(
                connection,
                project_paths=paths,
                provider_id=provider_id,
                actor_id=payload.actor_id,
                project_id=_selected_project_id(connection, payload.project_id),
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/recovery-policy/actions/set")
    def recovery_policy_set_action(payload: RecoveryPolicyRequest):
        connection = connect(paths)
        try:
            return update_project_recovery_policy(
                connection,
                payload.actor_id,
                payload.policy,
                project_id=_selected_project_id(connection, payload.project_id),
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/lifecycle/start")
    def lifecycle_start(payload: StartSessionRequest):
        connection = connect(paths)
        try:
            session_id = start_session(
                connection,
                project_id=payload.project_id,
                agent_id=payload.agent_id,
                task_id=payload.task_id,
                provider_type=payload.provider_type,
                status_message=payload.status_message,
            )
            return {"session_id": session_id}
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/lifecycle/heartbeat")
    def lifecycle_heartbeat(payload: LifecycleHeartbeatRequest):
        connection = connect(paths)
        try:
            heartbeat(connection, payload.session_id, payload.progress_pct, payload.status_message)
            return {"status": "ok"}
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/lifecycle/activity")
    def lifecycle_activity(payload: ActivityRequest):
        connection = connect(paths)
        try:
            log_activity(
                connection,
                project_id=payload.project_id,
                agent_id=payload.agent_id,
                task_id=payload.task_id,
                action=payload.action,
                category=payload.category,
                description=payload.description,
                severity=payload.severity,
            )
            return {"status": "ok"}
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/lifecycle/artifact")
    def lifecycle_artifact(payload: ArtifactRequest):
        connection = connect(paths)
        try:
            artifact_id = produce_artifact(
                connection,
                project_id=payload.project_id,
                session_id=payload.session_id,
                task_id=payload.task_id,
                artifact_type=payload.artifact_type,
                path=payload.path,
            )
            return {"artifact_id": artifact_id}
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/lifecycle/end")
    def lifecycle_end(payload: EndSessionRequest):
        connection = connect(paths)
        try:
            end_session(connection, payload.session_id, payload.outcome, payload.summary, project_paths=paths)
            return {"status": "ok"}
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/tasks/{task_id}/actions/review")
    def task_review_action(task_id: str, payload: ReviewTaskRequest):
        connection = connect(paths)
        try:
            return review_task(connection, task_id, payload.actor_id, payload.decision)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/tasks/{task_id}/actions/run-verification")
    def task_run_verification_action(task_id: str, payload: AgentActionRequest):
        connection = connect(paths)
        try:
            return run_task_verification(connection, paths, task_id, payload.actor_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/tasks/{task_id}/actions/prepare-git-workspace")
    def task_prepare_git_workspace_action(task_id: str, payload: AgentActionRequest):
        connection = connect(paths)
        try:
            return prepare_task_git_workspace(connection, paths, task_id, payload.actor_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/tasks/{task_id}/actions/refresh-git-diff")
    def task_refresh_git_diff_action(task_id: str, payload: AgentActionRequest):
        connection = connect(paths)
        try:
            return capture_task_git_diff(connection, paths, task_id, payload.actor_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/tasks/{task_id}/actions/halt")
    def task_halt_action(task_id: str, payload: AgentActionRequest):
        connection = connect(paths)
        try:
            return halt_task(connection, task_id, payload.actor_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/tasks/{task_id}/actions/recover")
    def task_recover_action(task_id: str, payload: AgentActionRequest):
        connection = connect(paths)
        try:
            return recover_task(connection, task_id, payload.actor_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/tasks/{task_id}/actions/recover-and-requeue")
    def task_recover_and_requeue_action(task_id: str, payload: AgentActionRequest):
        connection = connect(paths)
        try:
            return recover_and_requeue_task(connection, task_id, payload.actor_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/tasks/{task_id}/actions/mark-for-replan")
    def task_mark_for_replan_action(task_id: str, payload: AgentActionRequest):
        connection = connect(paths)
        try:
            return mark_task_for_replan(connection, task_id, payload.actor_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/tasks/{task_id}/actions/finish-replan")
    def task_finish_replan_action(task_id: str, payload: AgentActionRequest):
        connection = connect(paths)
        try:
            return finish_task_replan(connection, task_id, payload.actor_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/tasks/{task_id}/actions/set-retry-limit")
    def task_set_retry_limit_action(task_id: str, payload: TaskRetryLimitRequest):
        connection = connect(paths)
        try:
            return set_task_retry_limit(connection, task_id, payload.actor_id, payload.auto_retry_limit)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/tasks/{task_id}/actions/release-retry-backoff")
    def task_release_retry_backoff_action(task_id: str, payload: AgentActionRequest):
        connection = connect(paths)
        try:
            return release_task_retry_backoff(connection, task_id, payload.actor_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/tasks/{task_id}/actions/reset-retry-state")
    def task_reset_retry_state_action(task_id: str, payload: AgentActionRequest):
        connection = connect(paths)
        try:
            return reset_task_retry_state(connection, task_id, payload.actor_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/tasks/{task_id}/actions/reset-circuit-breaker")
    def task_reset_circuit_breaker_action(task_id: str, payload: AgentActionRequest):
        connection = connect(paths)
        try:
            return reset_task_circuit_breaker(connection, task_id, payload.actor_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/tasks/{task_id}/actions/resolve-repeated-failures")
    def task_resolve_repeated_failures_action(task_id: str, payload: AgentActionRequest):
        connection = connect(paths)
        try:
            return resolve_task_repeated_failures(connection, task_id, payload.actor_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/tasks/actions/refresh-ready")
    def task_refresh_ready_action(project_id: str = None):
        connection = connect(paths)
        try:
            scoped_project_id = _selected_project_id(connection, project_id)
            return {
                "changed": refresh_ready_tasks(connection, project_id=scoped_project_id),
                "tasks": resolve_ready_tasks(connection, project_id=scoped_project_id),
            }
        finally:
            connection.close()

    @app.post("/api/tasks/{task_id}/actions/evaluate")
    def task_evaluate_action(task_id: str):
        connection = connect(paths)
        try:
            return evaluate_task(connection, paths, task_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/tasks/actions/allocate-ready")
    def task_allocate_ready_action(payload: AllocateTasksRequest):
        connection = connect(paths)
        try:
            scoped_project_id = _selected_project_id(connection, payload.project_id)
            return allocate_ready_tasks(
                connection,
                actor_id=payload.actor_id,
                limit=payload.limit,
                project_id=scoped_project_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/tasks/{task_id}/actions/reprioritize")
    def task_reprioritize_action(task_id: str, payload: ReprioritizeTaskRequest):
        connection = connect(paths)
        try:
            return reprioritize_task(connection, task_id, payload.actor_id, payload.priority)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/tasks/{task_id}/actions/reassign")
    def task_reassign_action(task_id: str, payload: ReassignTaskRequest):
        connection = connect(paths)
        try:
            return reassign_task(connection, task_id, payload.actor_id, payload.agent_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/supervisor/run")
    def supervisor_run_action(payload: Optional[SupervisorRunRequest] = None):
        connection = connect(paths)
        try:
            limit = None if payload is None else payload.allocate_limit
            scoped_project_id = None if payload is None else _selected_project_id(connection, payload.project_id)
            return run_supervisor_once(connection, allocate_limit=limit, project_paths=paths, project_id=scoped_project_id)
        finally:
            connection.close()

    @app.post("/api/agents/{agent_id}/actions/assign-next")
    def agent_assign_next_action(agent_id: str, payload: AssignTaskRequest):
        connection = connect(paths)
        try:
            return assign_next_task(connection, agent_id, actor_id=payload.actor_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/agents/{agent_id}/actions/pause")
    def agent_pause_action(agent_id: str, payload: AgentActionRequest):
        connection = connect(paths)
        try:
            return pause_agent(connection, agent_id, payload.actor_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/agents/{agent_id}/actions/resume")
    def agent_resume_action(agent_id: str, payload: AgentActionRequest):
        connection = connect(paths)
        try:
            return resume_agent(connection, agent_id, payload.actor_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/agents/{agent_id}/actions/recover")
    def agent_recover_action(agent_id: str, payload: AgentActionRequest):
        connection = connect(paths)
        try:
            return recover_agent(connection, agent_id, payload.actor_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/alerts/{alert_id}/actions/acknowledge")
    def alert_acknowledge_action(alert_id: str, payload: AlertActionRequest):
        connection = connect(paths)
        try:
            return update_alert_status(connection, alert_id, payload.actor_id, "acknowledged")
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/alerts/{alert_id}/actions/resolve")
    def alert_resolve_action(alert_id: str, payload: AlertActionRequest):
        connection = connect(paths)
        try:
            return update_alert_status(connection, alert_id, payload.actor_id, "resolved")
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    return app
