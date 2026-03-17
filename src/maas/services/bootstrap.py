"""Project bootstrap, onboarding discovery, and seed data."""

import json
import os

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.11+ in normal runtime.
    tomllib = None

from maas.config import build_default_project_config, save_project_config
from maas.db import connect, run_migrations
from maas.ids import generate_id
from maas.paths import ProjectPaths
from maas.services.security import TASK_EXECUTION_CAPABILITIES, grant_task_capabilities


IGNORED_DISCOVERY_DIRS = {
    ".git",
    ".maas",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    ".next",
    ".turbo",
}

IGNORED_MODE_NAMES = {
    ".git",
    ".maas",
    ".gitignore",
    "project.yaml",
    "LICENSE",
    "LICENSE.txt",
    "LICENSE.md",
}

KNOWN_BROWNFIELD_HIDDEN_PATHS = {
    ".github",
    ".claude",
    ".vscode",
}

BROWNFIELD_REVIEW_TASK_TITLE = "Review imported project understanding"
BROWNFIELD_PENDING_REVIEW_STATE = "awaiting_onboarding_approval"

LANGUAGE_EXTENSIONS = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".rb": "ruby",
    ".c": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".sh": "shell",
    ".sql": "sql",
}

NOTABLE_PATHS = {
    "README.md": "readme",
    "README.rst": "readme",
    "pyproject.toml": "python_project",
    "requirements.txt": "python_project",
    "package.json": "node_project",
    "Cargo.toml": "rust_project",
    "go.mod": "go_project",
    "Makefile": "makefile",
    "docker-compose.yml": "docker_compose",
    "Dockerfile": "dockerfile",
    "AGENTS.md": "agent_instructions",
    "CLAUDE.md": "claude_instructions",
    ".github/workflows": "github_actions",
}


def default_project_name(project_root):
    return os.path.basename(os.path.abspath(project_root)) or "maas-project"


def detect_bootstrap_mode(project_root):
    try:
        names = os.listdir(project_root)
    except FileNotFoundError:
        return "greenfield"
    meaningful = [
        name
        for name in names
        if name not in IGNORED_MODE_NAMES
        and (not name.startswith(".") or name in KNOWN_BROWNFIELD_HIDDEN_PATHS)
    ]
    return "brownfield" if meaningful else "greenfield"


def _read_text_excerpt(path, max_lines=6):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = [line.strip() for line in handle.readlines()]
    except (OSError, UnicodeDecodeError):
        return ""
    meaningful = [line for line in lines if line][:max_lines]
    return "\n".join(meaningful)


def _load_package_json(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def _load_pyproject(path):
    if tomllib is not None:
        try:
            with open(path, "rb") as handle:
                return tomllib.load(handle)
        except (OSError, tomllib.TOMLDecodeError):
            return {}

    parsed = {}
    current_section = []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("[") and line.endswith("]"):
                    section_name = line[1:-1].strip()
                    current_section = [part.strip() for part in section_name.split(".") if part.strip()]
                    cursor = parsed
                    for part in current_section:
                        cursor = cursor.setdefault(part, {})
                    continue
                if "=" not in line or not current_section:
                    continue
                key, value = [part.strip() for part in line.split("=", 1)]
                value = value.strip("\"'")
                cursor = parsed
                for part in current_section:
                    cursor = cursor.setdefault(part, {})
                cursor[key] = value
    except OSError:
        return {}
    return parsed


def _parse_makefile_targets(path):
    targets = []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or stripped.startswith("."):
                    continue
                if ":" not in stripped:
                    continue
                target = stripped.split(":", 1)[0].strip()
                if not target or " " in target or "=" in target:
                    continue
                targets.append(target)
    except OSError:
        return []
    return targets[:8]


def _top_entries(counts, limit=4):
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return ordered[:limit]


def discover_brownfield_project(project_root):
    project_root = os.path.abspath(project_root)
    discovery = {
        "mode": "brownfield",
        "root": project_root,
        "total_files": 0,
        "total_dirs": 0,
        "primary_language": "unknown",
        "language_counts": {},
        "top_level_dirs": [],
        "package_managers": [],
        "docs_roots": [],
        "test_roots": [],
        "workflow_signals": [],
        "notable_files": [],
        "readme_excerpt": "",
        "scripts": [],
    }

    top_level_counts = {}
    top_level_languages = {}
    for current_root, dirnames, filenames in os.walk(project_root):
        relative_root = os.path.relpath(current_root, project_root)
        dirnames[:] = [name for name in dirnames if name not in IGNORED_DISCOVERY_DIRS]
        if relative_root == ".":
            discovery["docs_roots"] = sorted(name for name in dirnames if name.lower() in {"docs", "doc"})
            discovery["test_roots"] = sorted(name for name in dirnames if "test" in name.lower() or name.lower() == "spec")
        else:
            discovery["total_dirs"] += 1

        for filename in filenames:
            if filename in {".DS_Store"}:
                continue
            full_path = os.path.join(current_root, filename)
            relative_path = os.path.relpath(full_path, project_root)
            discovery["total_files"] += 1
            ext = os.path.splitext(filename)[1].lower()
            language = LANGUAGE_EXTENSIONS.get(ext)
            if language:
                discovery["language_counts"][language] = discovery["language_counts"].get(language, 0) + 1
                top_level_name = relative_path.split(os.sep, 1)[0]
                top_level_languages.setdefault(top_level_name, {})
                top_level_languages[top_level_name][language] = top_level_languages[top_level_name].get(language, 0) + 1

            top_level_name = relative_path.split(os.sep, 1)[0]
            top_level_counts[top_level_name] = top_level_counts.get(top_level_name, 0) + 1

    if discovery["language_counts"]:
        discovery["primary_language"] = max(
            discovery["language_counts"].items(),
            key=lambda item: (item[1], item[0]),
        )[0]

    for path, indicator in NOTABLE_PATHS.items():
        if os.path.exists(os.path.join(project_root, path)):
            discovery["notable_files"].append({"path": path, "indicator": indicator})

    if os.path.exists(os.path.join(project_root, "pyproject.toml")):
        discovery["package_managers"].append("pyproject.toml")
        pyproject = _load_pyproject(os.path.join(project_root, "pyproject.toml"))
        project_section = pyproject.get("project", {})
        scripts = sorted((project_section.get("scripts") or {}).keys())[:8]
        for script in scripts:
            discovery["workflow_signals"].append({"kind": "python_script", "name": script})
        if project_section.get("requires-python"):
            discovery["workflow_signals"].append(
                {"kind": "python_version", "name": project_section["requires-python"]}
            )

    if os.path.exists(os.path.join(project_root, "package.json")):
        discovery["package_managers"].append("package.json")
        package_json = _load_package_json(os.path.join(project_root, "package.json"))
        scripts = sorted((package_json.get("scripts") or {}).keys())[:8]
        for script in scripts:
            discovery["workflow_signals"].append({"kind": "npm_script", "name": script})

    if os.path.exists(os.path.join(project_root, "Cargo.toml")):
        discovery["package_managers"].append("Cargo.toml")
    if os.path.exists(os.path.join(project_root, "go.mod")):
        discovery["package_managers"].append("go.mod")
    if os.path.exists(os.path.join(project_root, "requirements.txt")):
        discovery["package_managers"].append("requirements.txt")

    makefile_path = os.path.join(project_root, "Makefile")
    if os.path.exists(makefile_path):
        for target in _parse_makefile_targets(makefile_path):
            discovery["workflow_signals"].append({"kind": "make_target", "name": target})

    readme_path = None
    for candidate in ("README.md", "README.rst"):
        candidate_path = os.path.join(project_root, candidate)
        if os.path.exists(candidate_path):
            readme_path = candidate_path
            break
    if readme_path:
        discovery["readme_excerpt"] = _read_text_excerpt(readme_path)

    top_level_dirs = []
    for name, count in sorted(top_level_counts.items(), key=lambda item: (-item[1], item[0])):
        if not os.path.isdir(os.path.join(project_root, name)):
            continue
        top_level_dirs.append(
            {
                "name": name,
                "file_count": count,
                "primary_language": max(
                    top_level_languages.get(name, {"mixed": 0}).items(),
                    key=lambda item: item[1],
                )[0],
            }
        )
        if len(top_level_dirs) >= 4:
            break
    discovery["top_level_dirs"] = top_level_dirs

    seen_signals = set()
    unique_signals = []
    for signal in discovery["workflow_signals"]:
        key = (signal["kind"], signal["name"])
        if key in seen_signals:
            continue
        seen_signals.add(key)
        unique_signals.append(signal)
    discovery["workflow_signals"] = unique_signals[:10]
    discovery["scripts"] = [signal["name"] for signal in discovery["workflow_signals"] if signal["kind"] in {"make_target", "npm_script", "python_script"}][:6]
    return discovery


def build_understanding_markdown(config, mode="greenfield", discovery=None):
    project = config["project"]
    if mode == "brownfield" and discovery is not None:
        package_managers = ", ".join(discovery["package_managers"]) or "none detected"
        top_dirs = ", ".join(
            "{name} ({language}, {count} files)".format(
                name=item["name"],
                language=item["primary_language"],
                count=item["file_count"],
            )
            for item in discovery["top_level_dirs"]
        ) or "none detected"
        workflows = ", ".join(
            "{kind}:{name}".format(kind=item["kind"], name=item["name"])
            for item in discovery["workflow_signals"]
        ) or "none detected"
        docs = ", ".join(discovery["docs_roots"]) or "none detected"
        tests = ", ".join(discovery["test_roots"]) or "none detected"
        readme_excerpt = discovery["readme_excerpt"] or "No README excerpt available."
        return """# Project Understanding

## Summary

- Name: {name}
- Type: {project_type}
- Description: {description}
- Operating Model: board-first overlay on an existing repository
- Onboarding Mode: brownfield

## Observed Repository Shape

- Primary Language: {primary_language}
- Package Managers: {package_managers}
- Files Scanned: {total_files}
- Directories Scanned: {total_dirs}
- High-Signal Top-Level Directories: {top_dirs}
- Documentation Roots: {docs}
- Test Roots: {tests}

## Workflow Signals

- Detected commands and automation: {workflows}
- Initial README excerpt:

{readme_excerpt}

## Initial Brownfield Assumptions

- Existing project structure should remain intact; MAAS operates as an overlay.
- Imported backlog starts with review, workflow validation, and runtime alignment instead of synthetic feature work.
- Human review of this understanding artifact is required before autonomous operation expands.

## Initial Plan Templates

- Brownfield Discovery
- Existing Workflow Integration
- Bug Fix
""".format(
            name=project["name"],
            project_type=project["type"],
            description=project["description"],
            primary_language=discovery["primary_language"],
            package_managers=package_managers,
            total_files=discovery["total_files"],
            total_dirs=discovery["total_dirs"],
            top_dirs=top_dirs,
            docs=docs,
            tests=tests,
            workflows=workflows,
            readme_excerpt=readme_excerpt,
        )
    return """# Project Understanding

## Summary

- Name: {name}
- Type: {project_type}
- Description: {description}
- Operating Model: board-first multi-agent execution

## Initial Assumptions

- This project is being bootstrapped in greenfield mode.
- The Kanban board is the primary human operating surface.
- Goals remain available as a separate hierarchy, but daily work flows through tasks.
- Initial agent roles are allocator, researcher, builder, and reviewer.

## Initial Plan Templates

- Research Investigation
- Feature Development
- Bug Fix
""".format(
        name=project["name"],
        project_type=project["type"],
        description=project["description"],
    )


def build_greenfield_task_specs():
    return [
        ("planned", "Define project workspace contracts", "agent_researcher", 80, "Design the stable `project.yaml` and `.maas/` workspace contracts.", None, 0),
        ("ready", "Wire the scheduler and board read model", "agent_allocator", 88, "Prepare the task graph and board grouping logic.", None, 0),
        ("in_progress", "Implement FastAPI board endpoint", "agent_builder", 92, "Expose grouped Kanban columns through `/api/board`.", None, 55),
        ("review", "Validate seeded lifecycle semantics", "agent_reviewer", 74, "Review status transitions and acceptance-gate handling.", "awaiting_review", 0),
        ("blocked", "Integrate provider adapters", "agent_builder", 60, "Waiting on runtime adapter contracts and lifecycle wrapper decisions.", None, 0),
        ("done", "Bootstrap migration runner", "agent_allocator", 99, "Migration runner is in place and ready for use.", None, 0),
    ]


def build_brownfield_task_specs(discovery):
    workflow_text = ", ".join(discovery["scripts"]) or "manual repo command review"
    top_dirs = ", ".join(item["name"] for item in discovery["top_level_dirs"]) or "the repository root"
    docs = ", ".join(discovery["docs_roots"]) or "README and inline project docs"
    tests = ", ".join(discovery["test_roots"]) or "discovered validation entrypoints"
    primary_language = discovery["primary_language"]
    return [
        (
            "review",
            BROWNFIELD_REVIEW_TASK_TITLE,
            "agent_reviewer",
            98,
            "Review the brownfield understanding artifact and confirm the imported operating model before wider automation.",
            "awaiting_review",
            0,
        ),
        (
            "blocked",
            "Validate discovered workflow entrypoints",
            "agent_researcher",
            92,
            "Confirm the discovered commands and automation paths: {workflow_text}.".format(workflow_text=workflow_text),
            BROWNFIELD_PENDING_REVIEW_STATE,
            0,
        ),
        (
            "blocked",
            "Map high-signal repository areas into MAAS ownership",
            "agent_allocator",
            88,
            "Turn the highest-signal directories into operator-visible work areas: {top_dirs}.".format(top_dirs=top_dirs),
            BROWNFIELD_PENDING_REVIEW_STATE,
            0,
        ),
        (
            "blocked",
            "Align runtime and provider settings with existing tooling",
            "agent_builder",
            84,
            "Compare MAAS runtime expectations against the discovered {primary_language} stack and project tooling.".format(
                primary_language=primary_language
            ),
            BROWNFIELD_PENDING_REVIEW_STATE,
            0,
        ),
        (
            "blocked",
            "Import documentation and test conventions into the working backlog",
            "agent_researcher",
            80,
            "Translate the discovered docs ({docs}) and tests ({tests}) into explicit operator-reviewed workflows.".format(
                docs=docs,
                tests=tests,
            ),
            BROWNFIELD_PENDING_REVIEW_STATE,
            0,
        ),
    ]


def seed_project(connection, config, mode="greenfield", discovery=None):
    project_id = generate_id("proj")
    project = config["project"]
    connection.execute(
        """
        INSERT INTO projects (project_id, name, description, project_type, config_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            project_id,
            project["name"],
            project["description"],
            project["type"],
            json.dumps(config),
        ),
    )

    agents = []
    for role in config["agent_roles"]:
        agent_id = "agent_{role}".format(role=role["role"])
        agents.append((agent_id, role["role"], role["description"]))
        connection.execute(
            """
            INSERT INTO agents (agent_id, project_id, role, display_name, status, permissions_json)
            VALUES (?, ?, ?, ?, 'idle', ?)
            """,
            (agent_id, project_id, role["role"], role["role"].replace("_", " ").title(), json.dumps(role["permissions"])),
        )

    if mode == "brownfield":
        goal_specs = [
            ("Strategic", "Adopt MAAS as an overlay for the existing repository", "active", 95),
            ("Tactical", "Review imported repo understanding and align workflows", "active", 90),
        ]
        task_specs = build_brownfield_task_specs(discovery or {})
    else:
        goal_specs = [
            ("Strategic", "Launch the first usable MAAS workspace", "active", 95),
            ("Tactical", "Stand up board-first orchestration services", "active", 90),
        ]
        task_specs = build_greenfield_task_specs()

    goal_ids = []
    parent_goal_id = None
    for title_prefix, title, status, priority in goal_specs:
        goal_id = generate_id("goal")
        goal_ids.append(goal_id)
        connection.execute(
            """
            INSERT INTO goals (
                goal_id, project_id, parent_goal_id, title, description, status,
                goal_type, priority, acceptance_criteria_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                goal_id,
                project_id,
                parent_goal_id,
                title,
                "{0} goal for the initial MAAS bootstrap.".format(title_prefix),
                status,
                title_prefix.lower(),
                priority,
                json.dumps([{"type": "artifact_exists"}, {"type": "human_review"}]),
            ),
        )
        parent_goal_id = goal_id

    task_ids = []
    for status, title, agent_id, priority, description, review_state, progress_pct in task_specs:
        task_id = generate_id("task")
        task_ids.append(task_id)
        heartbeat = "CURRENT_TIMESTAMP" if status == "in_progress" else None
        connection.execute(
            """
            INSERT INTO tasks (
                task_id, project_id, goal_id, title, description, status,
                priority, assigned_agent_id, acceptance_criteria_json,
                progress_pct, review_state, last_heartbeat_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, {heartbeat})
            """.format(heartbeat=heartbeat or "?"),
            (
                task_id,
                project_id,
                goal_ids[-1],
                title,
                description,
                status,
                priority,
                agent_id,
                json.dumps([{"type": "artifact_exists"}]),
                progress_pct,
                review_state,
            )
            if heartbeat
            else (
                task_id,
                project_id,
                goal_ids[-1],
                title,
                description,
                status,
                priority,
                agent_id,
                json.dumps([{"type": "artifact_exists"}]),
                progress_pct,
                review_state,
                None,
            ),
            )

        if agent_id and status in ("planned", "ready", "assigned", "in_progress", "blocked"):
            grant_task_capabilities(
                connection,
                project_id,
                task_id,
                agent_id,
                TASK_EXECUTION_CAPABILITIES,
                granted_by="system_bootstrap",
            )

    if mode == "greenfield":
        connection.execute(
            """
            INSERT INTO task_dependencies (dependency_id, project_id, source_task_id, target_task_id, dependency_type)
            VALUES (?, ?, ?, ?, 'blocks')
            """,
            (generate_id("dep"), project_id, task_ids[1], task_ids[2]),
        )

        connection.execute(
            """
            INSERT INTO sessions (
                session_id, project_id, agent_id, task_id, status, provider_type, progress_pct, status_message
            ) VALUES (?, ?, ?, ?, 'active', 'python_script', 55, 'Implementing board endpoint')
            """,
            (generate_id("sess"), project_id, "agent_builder", task_ids[2]),
        )
        connection.execute(
            """
            UPDATE agents
            SET status = 'running', current_task_id = ?, last_heartbeat_at = CURRENT_TIMESTAMP
            WHERE agent_id = ?
            """,
            (task_ids[2], "agent_builder"),
        )

        connection.execute(
            """
            INSERT INTO activity_log (
                activity_id, project_id, agent_id, task_id, action, category, description, severity
            ) VALUES (?, ?, ?, ?, 'task_started', 'runtime', 'Builder picked up board endpoint work.', 'info')
            """,
            (generate_id("act"), project_id, "agent_builder", task_ids[2]),
        )
        connection.execute(
            """
            INSERT INTO alerts (
                alert_id, project_id, severity, title, description, status
            ) VALUES (?, ?, 'warning', 'Broader provider integrations pending', 'Simulated adapters and explicit local CLI modes are available, but broader provider coverage is still pending.', 'open')
            """,
            (generate_id("alert"), project_id),
        )
    else:
        connection.execute(
            """
            INSERT INTO activity_log (
                activity_id, project_id, action, category, description, severity
            ) VALUES (?, ?, 'brownfield_onboarding_imported', 'bootstrap', ?, 'info')
            """,
            (
                generate_id("act"),
                project_id,
                "Imported repo understanding for {language} project with {count} scanned files.".format(
                    language=(discovery or {}).get("primary_language", "unknown"),
                    count=(discovery or {}).get("total_files", 0),
                ),
            ),
        )
        connection.execute(
            """
            INSERT INTO alerts (
                alert_id, project_id, severity, title, description, status
            ) VALUES (?, ?, 'info', 'Brownfield onboarding review pending', ?, 'open')
            """,
            (
                generate_id("alert"),
                project_id,
                "Review the imported understanding artifact and repo-derived backlog before expanding automation.",
            ),
        )
    connection.commit()
    return project_id


def bootstrap_project(project_root, name=None, description=None, project_type=None, mode="auto"):
    paths = ProjectPaths(project_root)
    paths.ensure_directories()
    resolved_mode = detect_bootstrap_mode(project_root) if mode == "auto" else mode
    discovery = discover_brownfield_project(project_root) if resolved_mode == "brownfield" else None
    config = build_default_project_config(
        name=name or default_project_name(project_root),
        description=description or "Board-first MAAS workspace",
        project_type=project_type or "custom",
        onboarding_mode=resolved_mode,
        discovery_summary={
            "primary_language": discovery["primary_language"],
            "total_files": discovery["total_files"],
            "package_managers": discovery["package_managers"],
        }
        if discovery
        else None,
    )
    save_project_config(paths.project_config, config)
    with open(paths.understanding_path, "w", encoding="utf-8") as handle:
        handle.write(build_understanding_markdown(config, mode=resolved_mode, discovery=discovery))
    if discovery:
        with open(paths.discovery_path, "w", encoding="utf-8") as handle:
            json.dump(discovery, handle, indent=2, sort_keys=True)

    run_migrations(project_root, paths)
    connection = connect(paths)
    project_id = seed_project(connection, config, mode=resolved_mode, discovery=discovery)
    connection.close()
    return {"paths": paths, "config": config, "project_id": project_id, "mode": resolved_mode, "discovery": discovery}
