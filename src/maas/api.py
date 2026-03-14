"""FastAPI application for MAAS."""

from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from maas.db import connect, project_paths
from maas.paths import ProjectPaths
from maas.services.alerts import fetch_alerts, update_alert_status
from maas.services.board import fetch_board
from maas.services.dashboard import fetch_agent_roster, fetch_goal_tree, fetch_overview
from maas.services.escalations import approve_escalation, fetch_escalations, reject_escalation, request_escalation
from maas.services.failure_memory import fetch_failure_log
from maas.services.lifecycle import end_session, heartbeat, log_activity, produce_artifact, start_session
from maas.services.live import build_live_snapshot, sse_stream
from maas.services.provider_runtime import list_provider_runtime_status, run_provider_task
from maas.services.scheduler import allocate_ready_tasks, assign_next_task, evaluate_task, refresh_ready_tasks, resolve_ready_tasks
from maas.services.security import fetch_task_capabilities
from maas.services.steering import (
    recover_and_requeue_task,
    halt_task,
    pause_agent,
    reassign_task,
    recover_agent,
    recover_task,
    resolve_task_repeated_failures,
    reprioritize_task,
    resume_agent,
    review_task,
)
from maas.supervisor import run_supervisor_once


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


class AgentActionRequest(BaseModel):
    actor_id: str


class AlertActionRequest(BaseModel):
    actor_id: str


class AssignTaskRequest(BaseModel):
    actor_id: str = "system_allocator"


class AllocateTasksRequest(BaseModel):
    actor_id: str = "system_allocator"
    limit: int = None


class SupervisorRunRequest(BaseModel):
    allocate_limit: int = None


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

    @app.get("/api/live")
    def live():
        connection = connect(paths)
        try:
            return build_live_snapshot(connection)
        finally:
            connection.close()

    @app.get("/api/live/stream")
    def live_stream():
        root = paths.root

        def connection_factory():
            return connect(project_paths(root))

        return StreamingResponse(sse_stream(connection_factory), media_type="text/event-stream")

    @app.get("/api/board")
    def board(
        search: str = "",
        agent_id: str = None,
        goal_id: str = None,
        priority_min: int = None,
        blocked_only: bool = False,
        review_only: bool = False,
    ):
        connection = connect(paths)
        try:
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
            )
        finally:
            connection.close()

    @app.get("/api/goals")
    def goals():
        connection = connect(paths)
        try:
            rows = connection.execute(
                """
                SELECT goal_id, parent_goal_id, title, description, status, goal_type, priority, created_at
                FROM goals
                ORDER BY priority DESC, created_at ASC
                """
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    @app.get("/api/tasks/ready")
    def tasks_ready():
        connection = connect(paths)
        try:
            return {"tasks": resolve_ready_tasks(connection)}
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
    def goals_tree():
        connection = connect(paths)
        try:
            return fetch_goal_tree(connection)
        finally:
            connection.close()

    @app.get("/api/overview")
    def overview():
        connection = connect(paths)
        try:
            return fetch_overview(connection)
        finally:
            connection.close()

    @app.get("/api/agents")
    def agents():
        connection = connect(paths)
        try:
            return fetch_agent_roster(connection)
        finally:
            connection.close()

    @app.get("/api/activity")
    def activity(limit=20):
        connection = connect(paths)
        try:
            rows = connection.execute(
                """
                SELECT activity_id, agent_id, task_id, action, category, description, severity, created_at
                FROM activity_log
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    @app.get("/api/alerts")
    def alerts():
        connection = connect(paths)
        try:
            return fetch_alerts(connection)
        finally:
            connection.close()

    @app.get("/api/escalations")
    def escalations():
        connection = connect(paths)
        try:
            return fetch_escalations(connection)
        finally:
            connection.close()

    @app.get("/api/failures")
    def failures(limit=20):
        connection = connect(paths)
        try:
            return fetch_failure_log(connection, limit=int(limit))
        finally:
            connection.close()

    @app.get("/api/providers")
    def providers():
        return {"providers": list_provider_runtime_status()}

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
            end_session(connection, payload.session_id, payload.outcome, payload.summary)
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
    def task_refresh_ready_action():
        connection = connect(paths)
        try:
            return {"changed": refresh_ready_tasks(connection), "tasks": resolve_ready_tasks(connection)}
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
            return allocate_ready_tasks(connection, actor_id=payload.actor_id, limit=payload.limit)
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
            return run_supervisor_once(connection, allocate_limit=limit)
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
