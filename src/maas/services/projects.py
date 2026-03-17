"""Project listing and scope helpers."""


def list_projects(connection):
    rows = connection.execute(
        """
        SELECT
            projects.project_id,
            projects.name,
            projects.description,
            projects.project_type,
            projects.created_at,
            (
                SELECT COUNT(*)
                FROM tasks
                WHERE tasks.project_id = projects.project_id
            ) AS task_count,
            (
                SELECT COUNT(*)
                FROM agents
                WHERE agents.project_id = projects.project_id
            ) AS agent_count,
            (
                SELECT COUNT(*)
                FROM alerts
                WHERE alerts.project_id = projects.project_id
                  AND alerts.status = 'open'
            ) AS open_alert_count
        FROM projects
        ORDER BY projects.created_at ASC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def resolve_project(connection, project_id=None):
    if project_id:
        row = connection.execute(
            """
            SELECT project_id, name, description, project_type, config_json, created_at
            FROM projects
            WHERE project_id = ?
            """,
            (project_id,),
        ).fetchone()
    else:
        row = connection.execute(
            """
            SELECT project_id, name, description, project_type, config_json, created_at
            FROM projects
            ORDER BY created_at ASC
            LIMIT 1
            """
        ).fetchone()
    return row


def resolve_project_id(connection, project_id=None):
    row = resolve_project(connection, project_id)
    return row["project_id"] if row is not None else None
