"""CLI entrypoint for MAAS."""

import argparse
import json
import time

import uvicorn

from maas.api import create_app
from maas.db import connect, project_paths, run_migrations
from maas.services.board import fetch_board
from maas.services.bootstrap import bootstrap_project
from maas.services.escalations import approve_escalation, fetch_escalations, reject_escalation, request_escalation
from maas.services.failure_memory import fetch_failure_log
from maas.services.provider_runtime import run_provider_task
from maas.services.lifecycle import end_session, heartbeat, log_activity, produce_artifact, start_session
from maas.services.scheduler import allocate_ready_tasks, assign_next_task, evaluate_task, refresh_ready_tasks, resolve_ready_tasks
from maas.services.steering import recover_agent, recover_task
from maas.supervisor import run_supervisor_once


def build_parser():
    parser = argparse.ArgumentParser(prog="maas")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init")
    init_parser.add_argument("--project-root", default=".")
    init_parser.add_argument("--name")
    init_parser.add_argument("--description")
    init_parser.add_argument("--type", default="custom")

    db_parser = subparsers.add_parser("db")
    db_subparsers = db_parser.add_subparsers(dest="db_command", required=True)
    migrate_parser = db_subparsers.add_parser("migrate")
    migrate_parser.add_argument("--project-root", default=".")

    api_parser = subparsers.add_parser("api")
    api_parser.add_argument("--project-root", default=".")
    api_parser.add_argument("--host", default="127.0.0.1")
    api_parser.add_argument("--port", type=int, default=8000)

    supervisor_parser = subparsers.add_parser("supervisor")
    supervisor_parser.add_argument("--project-root", default=".")
    supervisor_parser.add_argument("--once", action="store_true")
    supervisor_parser.add_argument("--allocate-limit", type=int)

    board_parser = subparsers.add_parser("board")
    board_parser.add_argument("--project-root", default=".")

    agent_parser = subparsers.add_parser("agent")
    agent_subparsers = agent_parser.add_subparsers(dest="agent_command", required=True)

    agent_recover_parser = agent_subparsers.add_parser("recover")
    agent_recover_parser.add_argument("--project-root", default=".")
    agent_recover_parser.add_argument("--agent-id", required=True)
    agent_recover_parser.add_argument("--actor-id", required=True)

    task_parser = subparsers.add_parser("task")
    task_subparsers = task_parser.add_subparsers(dest="task_command", required=True)

    task_ready_parser = task_subparsers.add_parser("ready")
    task_ready_parser.add_argument("--project-root", default=".")
    task_ready_parser.add_argument("--refresh", action="store_true")

    task_evaluate_parser = task_subparsers.add_parser("evaluate")
    task_evaluate_parser.add_argument("--project-root", default=".")
    task_evaluate_parser.add_argument("--task-id", required=True)

    task_recover_parser = task_subparsers.add_parser("recover")
    task_recover_parser.add_argument("--project-root", default=".")
    task_recover_parser.add_argument("--task-id", required=True)
    task_recover_parser.add_argument("--actor-id", required=True)

    task_allocate_parser = task_subparsers.add_parser("allocate")
    task_allocate_parser.add_argument("--project-root", default=".")
    task_allocate_parser.add_argument("--agent-id")
    task_allocate_parser.add_argument("--actor-id", default="system_allocator")
    task_allocate_parser.add_argument("--limit", type=int)

    failure_parser = subparsers.add_parser("failure")
    failure_subparsers = failure_parser.add_subparsers(dest="failure_command", required=True)

    failure_list_parser = failure_subparsers.add_parser("list")
    failure_list_parser.add_argument("--project-root", default=".")
    failure_list_parser.add_argument("--limit", type=int, default=20)

    escalation_parser = subparsers.add_parser("escalation")
    escalation_subparsers = escalation_parser.add_subparsers(dest="escalation_command", required=True)

    escalation_list_parser = escalation_subparsers.add_parser("list")
    escalation_list_parser.add_argument("--project-root", default=".")

    escalation_request_parser = escalation_subparsers.add_parser("request")
    escalation_request_parser.add_argument("--project-root", default=".")
    escalation_request_parser.add_argument("--project-id", required=True)
    escalation_request_parser.add_argument("--actor-id", required=True)
    escalation_request_parser.add_argument("--action-type", required=True)
    escalation_request_parser.add_argument("--resource-type", required=True)
    escalation_request_parser.add_argument("--resource-id", required=True)
    escalation_request_parser.add_argument("--reason", default="")
    escalation_request_parser.add_argument("--payload-json", default="{}")

    escalation_approve_parser = escalation_subparsers.add_parser("approve")
    escalation_approve_parser.add_argument("--project-root", default=".")
    escalation_approve_parser.add_argument("--escalation-id", required=True)
    escalation_approve_parser.add_argument("--actor-id", required=True)
    escalation_approve_parser.add_argument("--resolution-note", default="")

    escalation_reject_parser = escalation_subparsers.add_parser("reject")
    escalation_reject_parser.add_argument("--project-root", default=".")
    escalation_reject_parser.add_argument("--escalation-id", required=True)
    escalation_reject_parser.add_argument("--actor-id", required=True)
    escalation_reject_parser.add_argument("--resolution-note", default="")

    worker_parser = subparsers.add_parser("worker")
    worker_parser.add_argument("--project-root", default=".")
    worker_parser.add_argument("--project-id", required=True)
    worker_parser.add_argument("--agent-id", required=True)
    worker_parser.add_argument("--task-id", required=True)
    worker_parser.add_argument("--provider-type", default="python_script")
    worker_parser.add_argument("--artifact-path", default=".maas/artifacts/example.txt")

    lifecycle_parser = subparsers.add_parser("lifecycle")
    lifecycle_subparsers = lifecycle_parser.add_subparsers(dest="lifecycle_command", required=True)

    start_parser = lifecycle_subparsers.add_parser("start")
    start_parser.add_argument("--project-root", default=".")
    start_parser.add_argument("--project-id", required=True)
    start_parser.add_argument("--agent-id", required=True)
    start_parser.add_argument("--task-id", required=True)
    start_parser.add_argument("--provider-type", default="python_script")
    start_parser.add_argument("--status-message", default="")

    heartbeat_parser = lifecycle_subparsers.add_parser("heartbeat")
    heartbeat_parser.add_argument("--project-root", default=".")
    heartbeat_parser.add_argument("--session-id", required=True)
    heartbeat_parser.add_argument("--progress-pct", type=int, required=True)
    heartbeat_parser.add_argument("--status-message", default="")

    activity_parser = lifecycle_subparsers.add_parser("activity")
    activity_parser.add_argument("--project-root", default=".")
    activity_parser.add_argument("--project-id", required=True)
    activity_parser.add_argument("--agent-id", required=True)
    activity_parser.add_argument("--task-id")
    activity_parser.add_argument("--action", required=True)
    activity_parser.add_argument("--category", required=True)
    activity_parser.add_argument("--description", required=True)
    activity_parser.add_argument("--severity", default="info")

    artifact_parser = lifecycle_subparsers.add_parser("artifact")
    artifact_parser.add_argument("--project-root", default=".")
    artifact_parser.add_argument("--project-id", required=True)
    artifact_parser.add_argument("--session-id", required=True)
    artifact_parser.add_argument("--task-id", required=True)
    artifact_parser.add_argument("--artifact-type", required=True)
    artifact_parser.add_argument("--path", required=True)

    end_parser = lifecycle_subparsers.add_parser("end")
    end_parser.add_argument("--project-root", default=".")
    end_parser.add_argument("--session-id", required=True)
    end_parser.add_argument("--outcome", required=True)
    end_parser.add_argument("--summary", default="")

    return parser


def command_init(args):
    result = bootstrap_project(
        project_root=args.project_root,
        name=args.name,
        description=args.description,
        project_type=args.type,
    )
    print(
        json.dumps(
            {
                "project_id": result["project_id"],
                "project_yaml": result["paths"].project_config,
                "db_path": result["paths"].db_path,
                "understanding_path": result["paths"].understanding_path,
            },
            indent=2,
        )
    )


def command_db_migrate(args):
    paths = project_paths(args.project_root)
    applied = run_migrations(args.project_root, paths)
    print(json.dumps({"applied": applied}, indent=2))


def command_api(args):
    app = create_app(project_root=args.project_root)
    uvicorn.run(app, host=args.host, port=args.port)


def command_supervisor(args):
    paths = project_paths(args.project_root)
    while True:
        connection = connect(paths)
        try:
            findings = run_supervisor_once(connection, allocate_limit=args.allocate_limit)
            print(json.dumps(findings, indent=2))
        finally:
            connection.close()
        if args.once:
            break
        time.sleep(15)


def command_board(args):
    paths = project_paths(args.project_root)
    connection = connect(paths)
    try:
        print(json.dumps(fetch_board(connection), indent=2))
    finally:
        connection.close()


def command_task(args):
    paths = project_paths(args.project_root)
    connection = connect(paths)
    try:
        if args.task_command == "ready":
            changed = refresh_ready_tasks(connection) if args.refresh else []
            print(json.dumps({"changed": changed, "tasks": resolve_ready_tasks(connection)}, indent=2))
        elif args.task_command == "evaluate":
            print(json.dumps(evaluate_task(connection, paths, args.task_id), indent=2))
        elif args.task_command == "recover":
            print(json.dumps(recover_task(connection, args.task_id, args.actor_id), indent=2))
        elif args.task_command == "allocate":
            if args.agent_id:
                print(json.dumps(assign_next_task(connection, args.agent_id, actor_id=args.actor_id), indent=2))
            else:
                print(json.dumps(allocate_ready_tasks(connection, actor_id=args.actor_id, limit=args.limit), indent=2))
    finally:
        connection.close()


def command_agent(args):
    paths = project_paths(args.project_root)
    connection = connect(paths)
    try:
        if args.agent_command == "recover":
            print(json.dumps(recover_agent(connection, args.agent_id, args.actor_id), indent=2))
    finally:
        connection.close()


def command_failure(args):
    paths = project_paths(args.project_root)
    connection = connect(paths)
    try:
        if args.failure_command == "list":
            print(json.dumps(fetch_failure_log(connection, limit=args.limit), indent=2))
    finally:
        connection.close()


def command_escalation(args):
    paths = project_paths(args.project_root)
    connection = connect(paths)
    try:
        if args.escalation_command == "list":
            print(json.dumps(fetch_escalations(connection), indent=2))
        elif args.escalation_command == "request":
            print(
                json.dumps(
                    request_escalation(
                        connection,
                        project_id=args.project_id,
                        actor_id=args.actor_id,
                        action_type=args.action_type,
                        resource_type=args.resource_type,
                        resource_id=args.resource_id,
                        reason=args.reason,
                        payload=json.loads(args.payload_json),
                    ),
                    indent=2,
                )
            )
        elif args.escalation_command == "approve":
            print(json.dumps(approve_escalation(connection, args.escalation_id, args.actor_id, args.resolution_note), indent=2))
        elif args.escalation_command == "reject":
            print(json.dumps(reject_escalation(connection, args.escalation_id, args.actor_id, args.resolution_note), indent=2))
    finally:
        connection.close()


def command_worker(args):
    paths = project_paths(args.project_root)
    connection = connect(paths)
    try:
        result = run_provider_task(
            connection,
            project_paths=paths,
            project_id=args.project_id,
            agent_id=args.agent_id,
            task_id=args.task_id,
            provider_type=args.provider_type,
            artifact_path=args.artifact_path,
        )
        print(
            json.dumps(
                {
                    "session_id": result["session_id"],
                    "artifact_id": result["artifact_id"],
                    "artifact_path": result["artifact_path"],
                    "provider": result["provider"],
                },
                indent=2,
            )
        )
    finally:
        connection.close()


def command_lifecycle(args):
    paths = project_paths(args.project_root)
    connection = connect(paths)
    try:
        if args.lifecycle_command == "start":
            session_id = start_session(
                connection,
                project_id=args.project_id,
                agent_id=args.agent_id,
                task_id=args.task_id,
                provider_type=args.provider_type,
                status_message=args.status_message,
            )
            print(json.dumps({"session_id": session_id}, indent=2))
        elif args.lifecycle_command == "heartbeat":
            heartbeat(connection, args.session_id, args.progress_pct, args.status_message)
            print(json.dumps({"status": "ok"}, indent=2))
        elif args.lifecycle_command == "activity":
            log_activity(
                connection,
                project_id=args.project_id,
                agent_id=args.agent_id,
                task_id=args.task_id,
                action=args.action,
                category=args.category,
                description=args.description,
                severity=args.severity,
            )
            print(json.dumps({"status": "ok"}, indent=2))
        elif args.lifecycle_command == "artifact":
            artifact_id = produce_artifact(
                connection,
                project_id=args.project_id,
                session_id=args.session_id,
                task_id=args.task_id,
                artifact_type=args.artifact_type,
                path=args.path,
            )
            print(json.dumps({"artifact_id": artifact_id}, indent=2))
        elif args.lifecycle_command == "end":
            end_session(connection, args.session_id, args.outcome, args.summary)
            print(json.dumps({"status": "ok"}, indent=2))
    finally:
        connection.close()


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "init":
        command_init(args)
    elif args.command == "db":
        if args.db_command == "migrate":
            command_db_migrate(args)
    elif args.command == "api":
        command_api(args)
    elif args.command == "supervisor":
        command_supervisor(args)
    elif args.command == "board":
        command_board(args)
    elif args.command == "agent":
        command_agent(args)
    elif args.command == "task":
        command_task(args)
    elif args.command == "failure":
        command_failure(args)
    elif args.command == "escalation":
        command_escalation(args)
    elif args.command == "worker":
        command_worker(args)
    elif args.command == "lifecycle":
        command_lifecycle(args)


if __name__ == "__main__":
    main()
