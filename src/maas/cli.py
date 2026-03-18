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
from maas.services.failure_memory import fetch_failure_log, fetch_quarantine_queue
from maas.services.git_workspaces import capture_task_git_diff, fetch_task_git_workspace, prepare_task_git_workspace
from maas.services.provider_runtime import (
    process_next_provider_job,
    process_provider_job,
    provider_job_queue,
    queue_provider_task,
    run_provider_task,
)
from maas.services.provider_workers import run_provider_worker_once
from maas.services.projects import (
    archive_project,
    create_project,
    list_projects,
    rescan_brownfield_project,
    restore_project,
    update_brownfield_onboarding_review,
)
from maas.services.recovery_policy import fetch_project_recovery_overview, update_project_recovery_policy
from maas.services.lifecycle import end_session, heartbeat, log_activity, produce_artifact, start_session
from maas.services.orchestrator import run_orchestrator_once
from maas.services.repo_plan import refresh_repo_grounded_plan
from maas.services.scheduler import allocate_ready_tasks, assign_next_task, evaluate_task, refresh_ready_tasks, resolve_ready_tasks
from maas.services.scheduler_policy import update_project_scheduler_policy
from maas.services.steering import (
    dismiss_quarantine_entry,
    finish_task_replan,
    mark_task_for_replan,
    reopen_quarantine_entry,
    recover_agent,
    recover_and_requeue_task,
    recover_task,
    release_task_retry_backoff,
    reset_task_retry_state,
    reset_task_circuit_breaker,
    resolve_task_repeated_failures,
    set_task_retry_limit,
    restore_and_requeue_quarantine_entry,
    restore_quarantine_entry,
    restore_failure_artifacts,
)
from maas.supervisor import run_supervisor_once
from maas.services.verification import fetch_verification_runs, run_task_verification


def build_parser():
    parser = argparse.ArgumentParser(prog="maas")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init")
    init_parser.add_argument("--project-root", default=".")
    init_parser.add_argument("--name")
    init_parser.add_argument("--description")
    init_parser.add_argument("--type", default="custom")
    init_parser.add_argument("--mode", choices=("auto", "greenfield", "brownfield"), default="auto")

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
    supervisor_parser.add_argument("--project-id")

    orchestrator_parser = subparsers.add_parser("orchestrator")
    orchestrator_parser.add_argument("--project-root", default=".")
    orchestrator_parser.add_argument("--once", action="store_true")
    orchestrator_parser.add_argument("--allocate-limit", type=int)
    orchestrator_parser.add_argument("--provider-job-limit", type=int, default=2)
    orchestrator_parser.add_argument("--project-id")
    orchestrator_parser.add_argument("--interval-seconds", type=int, default=15)

    board_parser = subparsers.add_parser("board")
    board_parser.add_argument("--project-root", default=".")

    project_parser = subparsers.add_parser("project")
    project_subparsers = project_parser.add_subparsers(dest="project_command", required=True)

    project_list_parser = project_subparsers.add_parser("list")
    project_list_parser.add_argument("--project-root", default=".")

    project_create_parser = project_subparsers.add_parser("create")
    project_create_parser.add_argument("--project-root", default=".")
    project_create_parser.add_argument("--actor-id", default="agent_allocator")
    project_create_parser.add_argument("--name", required=True)
    project_create_parser.add_argument("--description", default="")
    project_create_parser.add_argument("--type", default="custom")
    project_create_parser.add_argument("--mode", choices=("auto", "greenfield", "brownfield"), default="auto")
    project_create_parser.add_argument("--source-root")

    project_archive_parser = project_subparsers.add_parser("archive")
    project_archive_parser.add_argument("--project-root", default=".")
    project_archive_parser.add_argument("--project-id", required=True)
    project_archive_parser.add_argument("--actor-id", required=True)

    project_restore_parser = project_subparsers.add_parser("restore")
    project_restore_parser.add_argument("--project-root", default=".")
    project_restore_parser.add_argument("--project-id", required=True)
    project_restore_parser.add_argument("--actor-id", required=True)

    project_rescan_parser = project_subparsers.add_parser("rescan-brownfield")
    project_rescan_parser.add_argument("--project-root", default=".")
    project_rescan_parser.add_argument("--project-id", required=True)
    project_rescan_parser.add_argument("--actor-id", default="agent_allocator")

    project_update_review_parser = project_subparsers.add_parser("update-onboarding-review")
    project_update_review_parser.add_argument("--project-root", default=".")
    project_update_review_parser.add_argument("--project-id", required=True)
    project_update_review_parser.add_argument("--actor-id", default="agent_allocator")
    project_update_review_parser.add_argument("--ignored-path", action="append", default=[])
    project_update_review_parser.add_argument("--accept-workflow-label", action="append")
    project_update_review_parser.add_argument("--accept-runbook-label", action="append")

    project_scheduler_policy_parser = project_subparsers.add_parser("set-scheduler-policy")
    project_scheduler_policy_parser.add_argument("--project-root", default=".")
    project_scheduler_policy_parser.add_argument("--project-id", required=True)
    project_scheduler_policy_parser.add_argument("--actor-id", default="agent_allocator")
    project_scheduler_policy_parser.add_argument("--fair-share-weight", type=int, required=True)
    project_scheduler_policy_parser.add_argument("--max-active-sessions", type=int, required=True)

    project_refresh_repo_plan_parser = project_subparsers.add_parser("refresh-repo-plan")
    project_refresh_repo_plan_parser.add_argument("--project-root", default=".")
    project_refresh_repo_plan_parser.add_argument("--project-id", required=True)
    project_refresh_repo_plan_parser.add_argument("--actor-id", default="agent_allocator")

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

    task_recover_and_requeue_parser = task_subparsers.add_parser("recover-and-requeue")
    task_recover_and_requeue_parser.add_argument("--project-root", default=".")
    task_recover_and_requeue_parser.add_argument("--task-id", required=True)
    task_recover_and_requeue_parser.add_argument("--actor-id", required=True)

    task_resolve_repeated_failures_parser = task_subparsers.add_parser("resolve-repeated-failures")
    task_resolve_repeated_failures_parser.add_argument("--project-root", default=".")
    task_resolve_repeated_failures_parser.add_argument("--task-id", required=True)
    task_resolve_repeated_failures_parser.add_argument("--actor-id", required=True)

    task_retry_limit_parser = task_subparsers.add_parser("set-retry-limit")
    task_retry_limit_parser.add_argument("--project-root", default=".")
    task_retry_limit_parser.add_argument("--task-id", required=True)
    task_retry_limit_parser.add_argument("--actor-id", required=True)
    task_retry_limit_group = task_retry_limit_parser.add_mutually_exclusive_group(required=True)
    task_retry_limit_group.add_argument("--limit", type=int)
    task_retry_limit_group.add_argument("--clear", action="store_true")

    task_release_retry_backoff_parser = task_subparsers.add_parser("release-retry-backoff")
    task_release_retry_backoff_parser.add_argument("--project-root", default=".")
    task_release_retry_backoff_parser.add_argument("--task-id", required=True)
    task_release_retry_backoff_parser.add_argument("--actor-id", required=True)

    task_reset_retry_state_parser = task_subparsers.add_parser("reset-retry-state")
    task_reset_retry_state_parser.add_argument("--project-root", default=".")
    task_reset_retry_state_parser.add_argument("--task-id", required=True)
    task_reset_retry_state_parser.add_argument("--actor-id", required=True)

    task_reset_circuit_breaker_parser = task_subparsers.add_parser("reset-circuit-breaker")
    task_reset_circuit_breaker_parser.add_argument("--project-root", default=".")
    task_reset_circuit_breaker_parser.add_argument("--task-id", required=True)
    task_reset_circuit_breaker_parser.add_argument("--actor-id", required=True)

    task_mark_for_replan_parser = task_subparsers.add_parser("mark-for-replan")
    task_mark_for_replan_parser.add_argument("--project-root", default=".")
    task_mark_for_replan_parser.add_argument("--task-id", required=True)
    task_mark_for_replan_parser.add_argument("--actor-id", required=True)

    task_finish_replan_parser = task_subparsers.add_parser("finish-replan")
    task_finish_replan_parser.add_argument("--project-root", default=".")
    task_finish_replan_parser.add_argument("--task-id", required=True)
    task_finish_replan_parser.add_argument("--actor-id", required=True)

    task_allocate_parser = task_subparsers.add_parser("allocate")
    task_allocate_parser.add_argument("--project-root", default=".")
    task_allocate_parser.add_argument("--agent-id")
    task_allocate_parser.add_argument("--actor-id", default="system_allocator")
    task_allocate_parser.add_argument("--limit", type=int)

    task_verify_parser = task_subparsers.add_parser("run-verification")
    task_verify_parser.add_argument("--project-root", default=".")
    task_verify_parser.add_argument("--task-id", required=True)
    task_verify_parser.add_argument("--actor-id", required=True)

    task_prepare_git_workspace_parser = task_subparsers.add_parser("prepare-git-workspace")
    task_prepare_git_workspace_parser.add_argument("--project-root", default=".")
    task_prepare_git_workspace_parser.add_argument("--task-id", required=True)
    task_prepare_git_workspace_parser.add_argument("--actor-id", required=True)

    task_refresh_git_diff_parser = task_subparsers.add_parser("refresh-git-diff")
    task_refresh_git_diff_parser.add_argument("--project-root", default=".")
    task_refresh_git_diff_parser.add_argument("--task-id", required=True)
    task_refresh_git_diff_parser.add_argument("--actor-id", required=True)

    verification_parser = subparsers.add_parser("verification")
    verification_subparsers = verification_parser.add_subparsers(dest="verification_command", required=True)

    verification_list_parser = verification_subparsers.add_parser("list")
    verification_list_parser.add_argument("--project-root", default=".")
    verification_list_parser.add_argument("--project-id")
    verification_list_parser.add_argument("--task-id")
    verification_list_parser.add_argument("--limit", type=int, default=20)

    failure_parser = subparsers.add_parser("failure")
    failure_subparsers = failure_parser.add_subparsers(dest="failure_command", required=True)

    failure_list_parser = failure_subparsers.add_parser("list")
    failure_list_parser.add_argument("--project-root", default=".")
    failure_list_parser.add_argument("--limit", type=int, default=20)

    failure_restore_parser = failure_subparsers.add_parser("restore-artifacts")
    failure_restore_parser.add_argument("--project-root", default=".")
    failure_restore_parser.add_argument("--failure-id", required=True)
    failure_restore_parser.add_argument("--actor-id", required=True)

    quarantine_parser = subparsers.add_parser("quarantine")
    quarantine_subparsers = quarantine_parser.add_subparsers(dest="quarantine_command", required=True)

    quarantine_list_parser = quarantine_subparsers.add_parser("list")
    quarantine_list_parser.add_argument("--project-root", default=".")
    quarantine_list_parser.add_argument("--limit", type=int, default=20)

    quarantine_restore_parser = quarantine_subparsers.add_parser("restore")
    quarantine_restore_parser.add_argument("--project-root", default=".")
    quarantine_restore_parser.add_argument("--queue-id", required=True)
    quarantine_restore_parser.add_argument("--actor-id", required=True)

    quarantine_restore_and_requeue_parser = quarantine_subparsers.add_parser("restore-and-requeue")
    quarantine_restore_and_requeue_parser.add_argument("--project-root", default=".")
    quarantine_restore_and_requeue_parser.add_argument("--queue-id", required=True)
    quarantine_restore_and_requeue_parser.add_argument("--actor-id", required=True)

    quarantine_dismiss_parser = quarantine_subparsers.add_parser("dismiss")
    quarantine_dismiss_parser.add_argument("--project-root", default=".")
    quarantine_dismiss_parser.add_argument("--queue-id", required=True)
    quarantine_dismiss_parser.add_argument("--actor-id", required=True)

    quarantine_reopen_parser = quarantine_subparsers.add_parser("reopen")
    quarantine_reopen_parser.add_argument("--project-root", default=".")
    quarantine_reopen_parser.add_argument("--queue-id", required=True)
    quarantine_reopen_parser.add_argument("--actor-id", required=True)

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

    provider_job_parser = subparsers.add_parser("provider-job")
    provider_job_subparsers = provider_job_parser.add_subparsers(dest="provider_job_command", required=True)

    provider_job_list_parser = provider_job_subparsers.add_parser("list")
    provider_job_list_parser.add_argument("--project-root", default=".")
    provider_job_list_parser.add_argument("--project-id")
    provider_job_list_parser.add_argument("--provider-id")
    provider_job_list_parser.add_argument("--status")
    provider_job_list_parser.add_argument("--limit", type=int, default=20)

    provider_job_queue_parser = provider_job_subparsers.add_parser("queue")
    provider_job_queue_parser.add_argument("--project-root", default=".")
    provider_job_queue_parser.add_argument("--project-id", required=True)
    provider_job_queue_parser.add_argument("--provider-id", required=True)
    provider_job_queue_parser.add_argument("--task-id", required=True)
    provider_job_queue_parser.add_argument("--agent-id", required=True)
    provider_job_queue_parser.add_argument("--actor-id", default="agent_allocator")
    provider_job_queue_parser.add_argument("--artifact-path")

    provider_job_process_parser = provider_job_subparsers.add_parser("process")
    provider_job_process_parser.add_argument("--project-root", default=".")
    provider_job_process_parser.add_argument("--job-id", required=True)
    provider_job_process_parser.add_argument("--actor-id", default="agent_allocator")

    provider_job_process_next_parser = provider_job_subparsers.add_parser("process-next")
    provider_job_process_next_parser.add_argument("--project-root", default=".")
    provider_job_process_next_parser.add_argument("--project-id")
    provider_job_process_next_parser.add_argument("--provider-id")
    provider_job_process_next_parser.add_argument("--actor-id", default="agent_allocator")

    provider_worker_parser = subparsers.add_parser("provider-worker")
    provider_worker_parser.add_argument("--project-root", default=".")
    provider_worker_parser.add_argument("--worker-id", required=True)
    provider_worker_parser.add_argument("--project-id")
    provider_worker_parser.add_argument("--provider-id")
    provider_worker_parser.add_argument("--once", action="store_true")
    provider_worker_parser.add_argument("--interval-seconds", type=int, default=5)

    recovery_parser = subparsers.add_parser("recovery")
    recovery_subparsers = recovery_parser.add_subparsers(dest="recovery_command", required=True)

    recovery_show_parser = recovery_subparsers.add_parser("show")
    recovery_show_parser.add_argument("--project-root", default=".")

    recovery_set_parser = recovery_subparsers.add_parser("set")
    recovery_set_parser.add_argument("--project-root", default=".")
    recovery_set_parser.add_argument("--actor-id", required=True)
    recovery_set_parser.add_argument("--policy-json", default="{}")

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
        mode=args.mode,
    )
    print(
        json.dumps(
            {
                "project_id": result["project_id"],
                "mode": result["mode"],
                "project_yaml": result["paths"].project_config,
                "db_path": result["paths"].db_path,
                "understanding_path": result["paths"].understanding_path,
                "discovery_path": result["paths"].discovery_path if result["discovery"] else None,
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
            findings = run_supervisor_once(
                connection,
                allocate_limit=args.allocate_limit,
                project_paths=paths,
                project_id=args.project_id,
            )
            print(json.dumps(findings, indent=2))
        finally:
            connection.close()
        if args.once:
            break
        time.sleep(15)


def command_orchestrator(args):
    paths = project_paths(args.project_root)
    while True:
        connection = connect(paths)
        try:
            findings = run_orchestrator_once(
                connection,
                paths,
                allocate_limit=args.allocate_limit,
                provider_job_limit=args.provider_job_limit,
                project_id=args.project_id,
            )
            print(json.dumps(findings, indent=2))
        finally:
            connection.close()
        if args.once:
            break
        time.sleep(args.interval_seconds)


def command_provider_worker(args):
    paths = project_paths(args.project_root)
    while True:
        connection = connect(paths)
        try:
            findings = run_provider_worker_once(
                connection,
                paths,
                worker_id=args.worker_id,
                project_id=args.project_id,
                provider_id=args.provider_id,
            )
            print(json.dumps(findings, indent=2))
        finally:
            connection.close()
        if args.once:
            break
        time.sleep(args.interval_seconds)


def command_board(args):
    paths = project_paths(args.project_root)
    connection = connect(paths)
    try:
        print(json.dumps(fetch_board(connection), indent=2))
    finally:
        connection.close()


def command_project(args):
    paths = project_paths(args.project_root)
    connection = connect(paths)
    try:
        if args.project_command == "list":
            print(json.dumps({"projects": list_projects(connection)}, indent=2))
        elif args.project_command == "create":
            print(
                json.dumps(
                    create_project(
                        connection,
                        paths,
                        actor_id=args.actor_id,
                        name=args.name,
                        description=args.description,
                        project_type=args.type,
                        mode=args.mode,
                        source_root=args.source_root,
                    ),
                    indent=2,
                )
            )
        elif args.project_command == "archive":
            print(json.dumps(archive_project(connection, args.project_id, args.actor_id), indent=2))
        elif args.project_command == "restore":
            print(json.dumps(restore_project(connection, args.project_id, args.actor_id), indent=2))
        elif args.project_command == "rescan-brownfield":
            print(json.dumps(rescan_brownfield_project(connection, paths, args.project_id, args.actor_id), indent=2))
        elif args.project_command == "update-onboarding-review":
            print(
                json.dumps(
                    update_brownfield_onboarding_review(
                        connection,
                        paths,
                        args.project_id,
                        args.actor_id,
                        {
                            "ignored_paths": args.ignored_path,
                            "accepted_workflow_labels": args.accept_workflow_label,
                            "accepted_runbook_labels": args.accept_runbook_label,
                        },
                    ),
                    indent=2,
                )
            )
        elif args.project_command == "set-scheduler-policy":
            print(
                json.dumps(
                    update_project_scheduler_policy(
                        connection,
                        args.project_id,
                        args.actor_id,
                        {
                            "fair_share_weight": args.fair_share_weight,
                            "max_active_sessions": args.max_active_sessions,
                        },
                    ),
                    indent=2,
                )
            )
        elif args.project_command == "refresh-repo-plan":
            print(
                json.dumps(
                    refresh_repo_grounded_plan(
                        connection,
                        args.project_id,
                        args.actor_id,
                    ),
                    indent=2,
                )
            )
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
        elif args.task_command == "recover-and-requeue":
            print(json.dumps(recover_and_requeue_task(connection, args.task_id, args.actor_id), indent=2))
        elif args.task_command == "resolve-repeated-failures":
            print(json.dumps(resolve_task_repeated_failures(connection, args.task_id, args.actor_id), indent=2))
        elif args.task_command == "set-retry-limit":
            print(
                json.dumps(
                    set_task_retry_limit(
                        connection,
                        args.task_id,
                        args.actor_id,
                        None if args.clear else args.limit,
                    ),
                    indent=2,
                )
            )
        elif args.task_command == "release-retry-backoff":
            print(json.dumps(release_task_retry_backoff(connection, args.task_id, args.actor_id), indent=2))
        elif args.task_command == "reset-retry-state":
            print(json.dumps(reset_task_retry_state(connection, args.task_id, args.actor_id), indent=2))
        elif args.task_command == "reset-circuit-breaker":
            print(json.dumps(reset_task_circuit_breaker(connection, args.task_id, args.actor_id), indent=2))
        elif args.task_command == "mark-for-replan":
            print(json.dumps(mark_task_for_replan(connection, args.task_id, args.actor_id), indent=2))
        elif args.task_command == "finish-replan":
            print(json.dumps(finish_task_replan(connection, args.task_id, args.actor_id), indent=2))
        elif args.task_command == "allocate":
            if args.agent_id:
                print(json.dumps(assign_next_task(connection, args.agent_id, actor_id=args.actor_id), indent=2))
            else:
                print(json.dumps(allocate_ready_tasks(connection, actor_id=args.actor_id, limit=args.limit), indent=2))
        elif args.task_command == "run-verification":
            print(json.dumps(run_task_verification(connection, paths, args.task_id, args.actor_id), indent=2))
        elif args.task_command == "prepare-git-workspace":
            print(json.dumps(prepare_task_git_workspace(connection, paths, args.task_id, args.actor_id), indent=2))
        elif args.task_command == "refresh-git-diff":
            print(json.dumps(capture_task_git_diff(connection, paths, args.task_id, args.actor_id), indent=2))
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
        elif args.failure_command == "restore-artifacts":
            print(json.dumps(restore_failure_artifacts(connection, paths, args.failure_id, args.actor_id), indent=2))
    finally:
        connection.close()


def command_verification(args):
    paths = project_paths(args.project_root)
    connection = connect(paths)
    try:
        if args.verification_command == "list":
            print(
                json.dumps(
                    {"runs": fetch_verification_runs(connection, project_id=args.project_id, task_id=args.task_id, limit=args.limit)},
                    indent=2,
                )
            )
    finally:
        connection.close()


def command_quarantine(args):
    paths = project_paths(args.project_root)
    connection = connect(paths)
    try:
        if args.quarantine_command == "list":
            print(json.dumps(fetch_quarantine_queue(connection, limit=args.limit), indent=2))
        elif args.quarantine_command == "restore":
            print(json.dumps(restore_quarantine_entry(connection, paths, args.queue_id, args.actor_id), indent=2))
        elif args.quarantine_command == "restore-and-requeue":
            print(json.dumps(restore_and_requeue_quarantine_entry(connection, paths, args.queue_id, args.actor_id), indent=2))
        elif args.quarantine_command == "dismiss":
            print(json.dumps(dismiss_quarantine_entry(connection, args.queue_id, args.actor_id), indent=2))
        elif args.quarantine_command == "reopen":
            print(json.dumps(reopen_quarantine_entry(connection, args.queue_id, args.actor_id), indent=2))
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
                    "execution": result["execution"],
                },
                indent=2,
            )
        )
    finally:
        connection.close()


def command_provider_job(args):
    paths = project_paths(args.project_root)
    connection = connect(paths)
    try:
        if args.provider_job_command == "list":
            print(
                json.dumps(
                    provider_job_queue(
                        connection,
                        project_id=args.project_id,
                        provider_id=args.provider_id,
                        status=args.status,
                        limit=args.limit,
                    ),
                    indent=2,
                )
            )
        elif args.provider_job_command == "queue":
            print(
                json.dumps(
                    queue_provider_task(
                        connection,
                        project_paths=paths,
                        provider_id=args.provider_id,
                        actor_id=args.actor_id,
                        project_id=args.project_id,
                        agent_id=args.agent_id,
                        task_id=args.task_id,
                        artifact_path=args.artifact_path,
                    ),
                    indent=2,
                )
            )
        elif args.provider_job_command == "process":
            print(
                json.dumps(
                    process_provider_job(
                        connection,
                        project_paths=paths,
                        job_id=args.job_id,
                        actor_id=args.actor_id,
                    ),
                    indent=2,
                )
            )
        elif args.provider_job_command == "process-next":
            print(
                json.dumps(
                    process_next_provider_job(
                        connection,
                        project_paths=paths,
                        actor_id=args.actor_id,
                        project_id=args.project_id,
                        provider_id=args.provider_id,
                    ),
                    indent=2,
                )
            )
    finally:
        connection.close()


def command_recovery(args):
    paths = project_paths(args.project_root)
    connection = connect(paths)
    try:
        if args.recovery_command == "show":
            print(json.dumps(fetch_project_recovery_overview(connection), indent=2))
        elif args.recovery_command == "set":
            print(
                json.dumps(
                    update_project_recovery_policy(
                        connection,
                        args.actor_id,
                        json.loads(args.policy_json),
                    ),
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
            end_session(connection, args.session_id, args.outcome, args.summary, project_paths=paths)
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
    elif args.command == "orchestrator":
        command_orchestrator(args)
    elif args.command == "board":
        command_board(args)
    elif args.command == "project":
        command_project(args)
    elif args.command == "agent":
        command_agent(args)
    elif args.command == "task":
        command_task(args)
    elif args.command == "failure":
        command_failure(args)
    elif args.command == "verification":
        command_verification(args)
    elif args.command == "quarantine":
        command_quarantine(args)
    elif args.command == "escalation":
        command_escalation(args)
    elif args.command == "worker":
        command_worker(args)
    elif args.command == "provider-job":
        command_provider_job(args)
    elif args.command == "provider-worker":
        command_provider_worker(args)
    elif args.command == "recovery":
        command_recovery(args)
    elif args.command == "lifecycle":
        command_lifecycle(args)


if __name__ == "__main__":
    main()
