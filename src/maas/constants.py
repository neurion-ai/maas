TASK_STATUSES = (
    "planned",
    "ready",
    "assigned",
    "in_progress",
    "review",
    "blocked",
    "done",
    "cancelled",
)

BOARD_COLUMNS = (
    ("planned", "Planned"),
    ("ready", "Ready"),
    ("assigned", "Assigned"),
    ("in_progress", "In Progress"),
    ("review", "Review"),
    ("blocked", "Blocked"),
    ("done", "Done"),
    ("cancelled", "Cancelled"),
)

GOAL_STATUSES = (
    "proposed",
    "approved",
    "active",
    "blocked",
    "completed",
    "failed",
    "abandoned",
)

SESSION_STATUSES = ("active", "completed", "failed", "timed_out", "cancelled")
AGENT_STATUSES = ("idle", "running", "paused", "error", "disabled")
ALERT_SEVERITIES = ("info", "warning", "critical")
DEPENDENCY_TYPES = ("blocks", "informs", "conflicts")
HEARTBEAT_STALE_SECONDS = 90
