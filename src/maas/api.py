"""FastAPI application for MAAS."""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from maas.db import connect
from maas.paths import ProjectPaths
from maas.providers import list_providers
from maas.services.board import fetch_board
from maas.services.lifecycle import end_session, heartbeat, log_activity, produce_artifact, start_session
from maas.services.steering import pause_agent, reassign_task, reprioritize_task, resume_agent, review_task


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

    @app.get("/api/agents")
    def agents():
        connection = connect(paths)
        try:
            rows = connection.execute(
                """
                SELECT agent_id, role, display_name, status, current_task_id, last_heartbeat_at
                FROM agents
                ORDER BY display_name ASC
                """
            ).fetchall()
            return [dict(row) for row in rows]
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
            rows = connection.execute(
                """
                SELECT alert_id, severity, title, description, status, created_at
                FROM alerts
                ORDER BY created_at DESC
                """
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            connection.close()

    @app.get("/api/providers")
    def providers():
        return {"providers": list_providers()}

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
        finally:
            connection.close()

    @app.post("/api/lifecycle/heartbeat")
    def lifecycle_heartbeat(payload: LifecycleHeartbeatRequest):
        connection = connect(paths)
        try:
            heartbeat(connection, payload.session_id, payload.progress_pct, payload.status_message)
            return {"status": "ok"}
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
        finally:
            connection.close()

    @app.post("/api/lifecycle/end")
    def lifecycle_end(payload: EndSessionRequest):
        connection = connect(paths)
        try:
            end_session(connection, payload.session_id, payload.outcome, payload.summary)
            return {"status": "ok"}
        finally:
            connection.close()

    @app.post("/api/tasks/{task_id}/actions/review")
    def task_review_action(task_id: str, payload: ReviewTaskRequest):
        connection = connect(paths)
        try:
            return review_task(connection, task_id, payload.actor_id, payload.decision)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/tasks/{task_id}/actions/reprioritize")
    def task_reprioritize_action(task_id: str, payload: ReprioritizeTaskRequest):
        connection = connect(paths)
        try:
            return reprioritize_task(connection, task_id, payload.actor_id, payload.priority)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/tasks/{task_id}/actions/reassign")
    def task_reassign_action(task_id: str, payload: ReassignTaskRequest):
        connection = connect(paths)
        try:
            return reassign_task(connection, task_id, payload.actor_id, payload.agent_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/agents/{agent_id}/actions/pause")
    def agent_pause_action(agent_id: str, payload: AgentActionRequest):
        connection = connect(paths)
        try:
            return pause_agent(connection, agent_id, payload.actor_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    @app.post("/api/agents/{agent_id}/actions/resume")
    def agent_resume_action(agent_id: str, payload: AgentActionRequest):
        connection = connect(paths)
        try:
            return resume_agent(connection, agent_id, payload.actor_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        finally:
            connection.close()

    return app
