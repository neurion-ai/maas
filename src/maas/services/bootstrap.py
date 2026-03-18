"""Project bootstrap, onboarding discovery, and seed data."""

import json
import os

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.11+ in normal runtime.
    tomllib = None

import yaml

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

WORKFLOW_SIGNAL_LABELS = {
    "python_script": "python script",
    "npm_script": "npm script",
    "make_target": "make target",
    "github_actions": "GitHub Actions workflow",
}

CODEBASE_AREA_LABELS = {
    "source": "source area",
    "tests": "test surface",
    "docs": "docs surface",
    "automation": "automation surface",
    "config": "config surface",
    "mixed": "repo area",
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


def _summarize_detail(value, limit=120):
    if not value:
        return ""
    text = " ".join(str(value).split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


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
    current_target = None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                raw_line = line.rstrip("\n")
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or stripped.startswith("."):
                    continue
                if raw_line.startswith("\t") and current_target is not None and not current_target.get("detail"):
                    current_target["detail"] = _summarize_detail(stripped)
                    continue
                if ":" not in stripped:
                    continue
                target = stripped.split(":", 1)[0].strip()
                if not target or " " in target or "=" in target:
                    continue
                current_target = {"name": target, "detail": ""}
                targets.append(current_target)
    except OSError:
        return []
    return targets[:8]


def _discover_github_actions_workflows(project_root):
    workflows_dir = os.path.join(project_root, ".github", "workflows")
    if not os.path.isdir(workflows_dir):
        return []

    workflows = []
    for filename in sorted(os.listdir(workflows_dir)):
        if not filename.endswith((".yml", ".yaml")):
            continue
        path = os.path.join(workflows_dir, filename)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = yaml.safe_load(handle) or {}
        except (OSError, yaml.YAMLError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}

        workflow_name = payload.get("name") or os.path.splitext(filename)[0]
        trigger_value = payload.get("on")
        if isinstance(trigger_value, dict):
            triggers = sorted(trigger_value.keys())
        elif isinstance(trigger_value, list):
            triggers = [str(item) for item in trigger_value]
        elif trigger_value:
            triggers = [str(trigger_value)]
        else:
            triggers = []
        jobs = sorted((payload.get("jobs") or {}).keys()) if isinstance(payload.get("jobs"), dict) else []
        detail_parts = []
        if triggers:
            detail_parts.append("triggers: {0}".format(", ".join(triggers[:3])))
        if jobs:
            detail_parts.append("jobs: {0}".format(", ".join(jobs[:3])))
        workflows.append(
            {
                "kind": "github_actions",
                "name": workflow_name,
                "path": os.path.join(".github", "workflows", filename),
                "detail": "; ".join(detail_parts),
            }
        )
        if len(workflows) >= 4:
            break
    return workflows


def _top_entries(counts, limit=4):
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return ordered[:limit]


def _classify_codebase_area(name, discovery):
    lowered = (name or "").lower()
    if name in (discovery.get("docs_roots") or []) or lowered in {"docs", "doc"}:
        return "docs"
    if name in (discovery.get("test_roots") or []) or "test" in lowered or lowered == "spec":
        return "tests"
    if lowered in {"scripts", "tools", ".github"}:
        return "automation"
    if lowered in {"config", "configs"}:
        return "config"
    if lowered in {"src", "app", "apps", "api", "server", "client", "web", "lib", "libs", "pkg", "packages", "services"}:
        return "source"
    return "mixed"


def _build_codebase_map(discovery):
    codebase_map = []
    for item in discovery.get("top_level_dirs", []):
        kind = _classify_codebase_area(item["name"], discovery)
        summary_parts = [
            "{language} stack".format(language=item["primary_language"]),
            "{count} files".format(count=item["file_count"]),
        ]
        if kind == "tests":
            summary_parts.append("test entrypoint area")
        elif kind == "docs":
            summary_parts.append("operator-facing docs area")
        elif kind == "automation":
            summary_parts.append("automation and workflow area")
        elif kind == "source":
            summary_parts.append("primary implementation area")
        codebase_map.append(
            {
                "name": item["name"],
                "path": item["name"],
                "kind": kind,
                "primary_language": item["primary_language"],
                "file_count": item["file_count"],
                "summary": ", ".join(summary_parts),
                "sample_files": item.get("sample_files", [])[:3],
            }
        )
        if len(codebase_map) >= 4:
            break

    if not codebase_map and discovery.get("total_files"):
        codebase_map.append(
            {
                "name": "repository_root",
                "path": ".",
                "kind": "mixed",
                "primary_language": discovery.get("primary_language") or "unknown",
                "file_count": discovery.get("total_files") or 0,
                "summary": "root-level repo layout with {count} files".format(
                    count=discovery.get("total_files") or 0
                ),
                "sample_files": discovery.get("sample_files", [])[:3],
            }
        )
    return codebase_map


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
    top_level_sample_files = {}
    discovery["sample_files"] = []
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
            top_level_sample_files.setdefault(top_level_name, [])
            if len(top_level_sample_files[top_level_name]) < 3:
                top_level_sample_files[top_level_name].append(relative_path)
            if len(discovery["sample_files"]) < 6:
                discovery["sample_files"].append(relative_path)

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
        scripts = project_section.get("scripts") or {}
        for script in sorted(scripts.keys())[:8]:
            discovery["workflow_signals"].append(
                {
                    "kind": "python_script",
                    "name": script,
                    "path": "pyproject.toml",
                    "detail": _summarize_detail(scripts.get(script)),
                }
            )
        if project_section.get("requires-python"):
            discovery["workflow_signals"].append(
                {"kind": "python_version", "name": project_section["requires-python"]}
            )

    if os.path.exists(os.path.join(project_root, "package.json")):
        discovery["package_managers"].append("package.json")
        package_json = _load_package_json(os.path.join(project_root, "package.json"))
        scripts = package_json.get("scripts") or {}
        for script in sorted(scripts.keys())[:8]:
            discovery["workflow_signals"].append(
                {
                    "kind": "npm_script",
                    "name": script,
                    "path": "package.json",
                    "detail": _summarize_detail(scripts.get(script)),
                }
            )

    if os.path.exists(os.path.join(project_root, "Cargo.toml")):
        discovery["package_managers"].append("Cargo.toml")
    if os.path.exists(os.path.join(project_root, "go.mod")):
        discovery["package_managers"].append("go.mod")
    if os.path.exists(os.path.join(project_root, "requirements.txt")):
        discovery["package_managers"].append("requirements.txt")
    discovery["workflow_signals"].extend(_discover_github_actions_workflows(project_root))

    makefile_path = os.path.join(project_root, "Makefile")
    if os.path.exists(makefile_path):
        for target in _parse_makefile_targets(makefile_path):
            discovery["workflow_signals"].append(
                {
                    "kind": "make_target",
                    "name": target["name"],
                    "path": "Makefile",
                    "detail": target.get("detail", ""),
                }
            )

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
                "sample_files": top_level_sample_files.get(name, [])[:3],
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
    discovery["codebase_map"] = _build_codebase_map(discovery)
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
        runbook = "\n".join(
            "- {label}{command}{path}{note}".format(
                label=item["label"],
                command=(" | command: `{0}`".format(item["command"]) if item.get("command") else ""),
                path=(" | path: {0}".format(item["path"]) if item.get("path") else ""),
                note=(" | note: {0}".format(item["review_note"]) if item.get("review_note") else ""),
            )
            for item in _build_runbook_commands(discovery)
        ) or "- none detected"
        codebase_map = "\n".join(
            "- {name} ({kind}, {language}, {count} files): {summary}{samples}".format(
                name=item["name"],
                kind=CODEBASE_AREA_LABELS.get(item["kind"], item["kind"]),
                language=item["primary_language"],
                count=item["file_count"],
                summary=item["summary"],
                samples=(
                    " | sample files: {0}".format(", ".join(item.get("sample_files", [])[:3]))
                    if item.get("sample_files")
                    else ""
                ),
            )
            for item in discovery.get("codebase_map", [])
        ) or "- none detected"
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
- Imported runbook:
{runbook}
- Imported codebase map:
{codebase_map}
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
            runbook=runbook,
            codebase_map=codebase_map,
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


def build_discovery_summary(discovery):
    if not discovery:
        return {}
    return {
        "primary_language": discovery["primary_language"],
        "total_files": discovery["total_files"],
        "package_managers": discovery["package_managers"],
        "workflow_labels": [
            "{kind}:{name}".format(kind=item["kind"], name=item["name"])
            for item in discovery["workflow_signals"][:5]
        ],
        "workflow_details": [
            {
                "label": "{kind}:{name}".format(kind=item["kind"], name=item["name"]),
                "path": item.get("path"),
                "detail": item.get("detail") or "",
            }
            for item in discovery["workflow_signals"][:5]
        ],
        "runbook_commands": _build_runbook_commands(discovery),
        "repo_areas": [item["name"] for item in discovery["top_level_dirs"][:4]],
        "codebase_map": [
            {
                "name": item["name"],
                "path": item.get("path") or item["name"],
                "kind": item["kind"],
                "primary_language": item["primary_language"],
                "file_count": item["file_count"],
                "summary": item.get("summary") or "",
                "sample_files": item.get("sample_files", [])[:3],
            }
            for item in discovery.get("codebase_map", [])[:4]
        ],
    }


def _normalize_review_paths(paths):
    normalized = []
    for value in paths or []:
        if not isinstance(value, str):
            continue
        candidate = value.strip().replace("\\", "/")
        if not candidate:
            continue
        normalized_candidate = os.path.normpath(candidate).replace("\\", "/")
        if normalized_candidate in ("", ".") or normalized_candidate.startswith("../"):
            continue
        if normalized_candidate not in normalized:
            normalized.append(normalized_candidate)
    return normalized


def default_onboarding_review_overrides(discovery_summary):
    summary = discovery_summary or {}
    return {
        "ignored_paths": [],
        "accepted_workflow_labels": list(summary.get("workflow_labels") or []),
        "accepted_runbook_labels": [
            item["label"] for item in (summary.get("runbook_commands") or []) if item.get("label")
        ],
    }


def merge_onboarding_review_overrides(discovery_summary, previous_summary=None, current_overrides=None):
    summary = discovery_summary or {}
    previous = previous_summary or {}
    current = current_overrides or {}

    workflow_labels = list(summary.get("workflow_labels") or [])
    previous_workflow_labels = set(previous.get("workflow_labels") or [])
    accepted_workflow_labels = set(current.get("accepted_workflow_labels") or workflow_labels)

    runbook_labels = [item["label"] for item in (summary.get("runbook_commands") or []) if item.get("label")]
    previous_runbook_labels = {
        item["label"] for item in (previous.get("runbook_commands") or []) if item.get("label")
    }
    accepted_runbook_labels = set(current.get("accepted_runbook_labels") or runbook_labels)

    return {
        "ignored_paths": _normalize_review_paths(current.get("ignored_paths") or []),
        "accepted_workflow_labels": [
            label
            for label in workflow_labels
            if label in accepted_workflow_labels or label not in previous_workflow_labels
        ],
        "accepted_runbook_labels": [
            label
            for label in runbook_labels
            if label in accepted_runbook_labels or label not in previous_runbook_labels
        ],
    }


def normalize_onboarding_review_overrides(discovery_summary, overrides=None):
    summary = discovery_summary or {}
    requested = overrides or {}
    defaults = default_onboarding_review_overrides(summary)
    available_workflow_labels = list(summary.get("workflow_labels") or [])
    available_runbook_labels = [item["label"] for item in (summary.get("runbook_commands") or []) if item.get("label")]
    requested_workflow_labels = requested.get("accepted_workflow_labels")
    requested_runbook_labels = requested.get("accepted_runbook_labels")
    return {
        "ignored_paths": _normalize_review_paths(requested.get("ignored_paths", defaults["ignored_paths"])),
        "accepted_workflow_labels": [
            label
            for label in available_workflow_labels
            if requested_workflow_labels is None or label in set(requested_workflow_labels)
        ],
        "accepted_runbook_labels": [
            label
            for label in available_runbook_labels
            if requested_runbook_labels is None or label in set(requested_runbook_labels)
        ],
    }


def _path_matches_ignored(path, ignored_paths):
    if not path:
        return False
    normalized_path = os.path.normpath(path).replace("\\", "/")
    for ignored in ignored_paths:
        if normalized_path == ignored or normalized_path.startswith(ignored + "/"):
            return True
    return False


def apply_onboarding_review_overrides(discovery_summary, review_overrides=None):
    summary = dict(discovery_summary or {})
    if not summary:
        return summary
    normalized_overrides = normalize_onboarding_review_overrides(summary, review_overrides)
    ignored_paths = normalized_overrides["ignored_paths"]
    accepted_workflow_labels = set(normalized_overrides["accepted_workflow_labels"])
    accepted_runbook_labels = set(normalized_overrides["accepted_runbook_labels"])

    workflow_details = [
        item
        for item in (summary.get("workflow_details") or [])
        if item.get("label") in accepted_workflow_labels and not _path_matches_ignored(item.get("path"), ignored_paths)
    ]
    workflow_labels = [item["label"] for item in workflow_details]
    if not workflow_labels:
        workflow_labels = [
            label
            for label in (summary.get("workflow_labels") or [])
            if label in accepted_workflow_labels
        ]

    runbook_commands = []
    for item in summary.get("runbook_commands") or []:
        if item.get("label") not in accepted_runbook_labels:
            continue
        if _path_matches_ignored(item.get("path"), ignored_paths):
            continue
        runbook_commands.append(dict(item))

    codebase_map = []
    for item in summary.get("codebase_map") or []:
        path = item.get("path") or item.get("name")
        if _path_matches_ignored(path, ignored_paths):
            continue
        filtered_item = dict(item)
        filtered_item["sample_files"] = [
            sample for sample in (item.get("sample_files") or []) if not _path_matches_ignored(sample, ignored_paths)
        ]
        codebase_map.append(filtered_item)

    summary["workflow_details"] = workflow_details
    summary["workflow_labels"] = workflow_labels
    summary["runbook_commands"] = runbook_commands
    summary["codebase_map"] = codebase_map
    summary["repo_areas"] = [item["name"] for item in codebase_map]
    summary["review_overrides"] = normalized_overrides
    return summary


def build_greenfield_task_specs():
    return [
        ("planned", "Define project workspace contracts", "agent_researcher", 80, "Design the stable `project.yaml` and `.maas/` workspace contracts.", None, 0),
        ("ready", "Wire the scheduler and board read model", "agent_allocator", 88, "Prepare the task graph and board grouping logic.", None, 0),
        ("in_progress", "Implement FastAPI board endpoint", "agent_builder", 92, "Expose grouped Kanban columns through `/api/board`.", None, 55),
        ("review", "Validate seeded lifecycle semantics", "agent_reviewer", 74, "Review status transitions and acceptance-gate handling.", "awaiting_review", 0),
        ("blocked", "Integrate provider adapters", "agent_builder", 60, "Waiting on runtime adapter contracts and lifecycle wrapper decisions.", None, 0),
        ("done", "Bootstrap migration runner", "agent_allocator", 99, "Migration runner is in place and ready for use.", None, 0),
    ]


def _operator_workflow_signals(discovery):
    operator_signals = []
    seen = set()
    for item in discovery.get("workflow_signals", []):
        if item["kind"] not in WORKFLOW_SIGNAL_LABELS:
            continue
        key = (item["kind"], item["name"])
        if key in seen:
            continue
        seen.add(key)
        operator_signals.append(item)
    return operator_signals[:3]


def _operator_codebase_entries(discovery):
    entries = []
    seen = set()
    for item in discovery.get("codebase_map", []):
        key = item["name"]
        if key in seen:
            continue
        seen.add(key)
        entries.append(item)
    return entries[:2]


def _unique_preserving_order(values):
    ordered = []
    seen = set()
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _source_path_criterion(paths):
    scoped_paths = _unique_preserving_order(paths)
    if not scoped_paths:
        return None
    return {"type": "source_path_exists", "paths": scoped_paths}


def _workflow_validation_command(signal):
    kind = signal.get("kind")
    name = signal.get("name")
    if not name:
        return None
    if kind == "make_target":
        return "make {name}".format(name=name)
    if kind == "npm_script":
        return "npm run {name}".format(name=name)
    return None


def _runbook_entry_for_signal(signal):
    kind = signal.get("kind")
    label = "{kind}:{name}".format(kind=kind, name=signal.get("name"))
    command = _workflow_validation_command(signal)
    entry = {
        "label": label,
        "kind": kind,
        "name": signal.get("name"),
        "path": signal.get("path"),
        "command": command,
        "detail": signal.get("detail") or "",
        "review_note": "",
    }
    if kind == "python_script":
        entry["review_note"] = "Review the imported pyproject entrypoint and map it to a MAAS validation recipe."
    elif kind == "github_actions":
        entry["review_note"] = "Review the imported CI workflow and mirror its checks inside the MAAS runbook."
    elif command:
        entry["review_note"] = "Use this imported command as a first-pass validation recipe."
    else:
        entry["review_note"] = "Review the imported workflow before wider automation."
    return entry


def _build_runbook_commands(discovery):
    entries = []
    seen = set()
    for signal in discovery.get("workflow_signals", []):
        if signal.get("kind") not in WORKFLOW_SIGNAL_LABELS:
            continue
        entry = _runbook_entry_for_signal(signal)
        key = (entry["label"], entry.get("command") or "", entry.get("path") or "")
        if key in seen:
            continue
        seen.add(key)
        entries.append(entry)
    return entries[:8]


def _brownfield_repo_area_paths(item):
    sample_files = item.get("sample_files", [])[:3]
    if sample_files:
        return sample_files
    return [item.get("path") or item["name"]]


def _brownfield_docs_and_tests_paths(discovery):
    scoped_paths = []
    for item in discovery.get("codebase_map", []):
        if item.get("kind") in {"docs", "tests"}:
            scoped_paths.extend(item.get("sample_files", [])[:2] or [item.get("path") or item["name"]])
    if scoped_paths:
        return _unique_preserving_order(scoped_paths)

    for root_name in (discovery.get("docs_roots") or []) + (discovery.get("test_roots") or []):
        sample = next(
            (path for path in discovery.get("sample_files", []) if path == root_name or path.startswith(root_name + os.sep)),
            None,
        )
        scoped_paths.append(sample or root_name)
    return _unique_preserving_order(scoped_paths)


def _runtime_alignment_paths(discovery):
    scoped_paths = []
    for filename in discovery.get("package_managers", []):
        scoped_paths.append(filename)
    for signal in discovery.get("workflow_signals", [])[:3]:
        if signal.get("path"):
            scoped_paths.append(signal["path"])
    if not scoped_paths:
        scoped_paths.extend(discovery.get("sample_files", [])[:3])
    return _unique_preserving_order(scoped_paths)


def _brownfield_task_spec(
    status,
    title,
    agent_id,
    priority,
    description,
    review_state,
    progress_pct,
    scoped_paths=None,
    validation_command=None,
):
    acceptance_criteria = [{"type": "artifact_exists"}]
    path_criterion = _source_path_criterion(scoped_paths or [])
    if path_criterion is not None:
        acceptance_criteria.append(path_criterion)
    if validation_command:
        acceptance_criteria.append(
            {
                "type": "test_passes",
                "command": validation_command,
                "timeout_seconds": 120,
            }
        )
    return {
        "status": status,
        "title": title,
        "agent_id": agent_id,
        "priority": priority,
        "description": description,
        "review_state": review_state,
        "progress_pct": progress_pct,
        "acceptance_criteria": acceptance_criteria,
    }


def build_brownfield_task_specs(discovery):
    top_dirs = ", ".join(item["name"] for item in discovery["top_level_dirs"]) or "the repository root"
    docs = ", ".join(discovery["docs_roots"]) or "README and inline project docs"
    tests = ", ".join(discovery["test_roots"]) or "discovered validation entrypoints"
    primary_language = discovery["primary_language"]
    task_specs = [
        _brownfield_task_spec(
            "review",
            BROWNFIELD_REVIEW_TASK_TITLE,
            "agent_reviewer",
            98,
            "Review the brownfield understanding artifact and confirm the imported operating model before wider automation.",
            "awaiting_review",
            0,
            scoped_paths=["README.md"] if discovery.get("readme_excerpt") else [],
        ),
    ]
    workflow_priority = 94
    for signal in _operator_workflow_signals(discovery):
        task_specs.append(
            _brownfield_task_spec(
                "blocked",
                "Validate imported workflow: {name}".format(name=signal["name"]),
                "agent_researcher",
                workflow_priority,
                "Confirm the imported {kind} `{name}` matches the existing repo workflow and acceptance path from {path}{detail}.".format(
                    kind=WORKFLOW_SIGNAL_LABELS[signal["kind"]],
                    name=signal["name"],
                    path=signal.get("path") or "the existing repository",
                    detail=(" ({0})".format(signal.get("detail")) if signal.get("detail") else ""),
                ),
                BROWNFIELD_PENDING_REVIEW_STATE,
                0,
                scoped_paths=[signal.get("path")] if signal.get("path") else [],
                validation_command=_workflow_validation_command(signal),
            )
        )
        workflow_priority -= 2

    repo_area_priority = 88
    for item in _operator_codebase_entries(discovery):
        kind_label = CODEBASE_AREA_LABELS.get(item["kind"], "repo area")
        task_specs.append(
            _brownfield_task_spec(
                "blocked",
                "Map imported {kind}: {name}".format(kind=kind_label, name=item["name"]),
                "agent_allocator",
                repo_area_priority,
                "Turn the imported {kind} `{name}` into an operator-visible ownership/workflow area using the discovered {language} stack and {count} files. Start from {samples}.".format(
                    kind=kind_label,
                    name=item["name"],
                    language=item["primary_language"],
                    count=item["file_count"],
                    samples=", ".join(item.get("sample_files", [])[:3]) or item["path"],
                ),
                BROWNFIELD_PENDING_REVIEW_STATE,
                0,
                scoped_paths=_brownfield_repo_area_paths(item),
            )
        )
        repo_area_priority -= 2

    if discovery.get("docs_roots") or discovery.get("test_roots"):
        task_specs.append(
            _brownfield_task_spec(
                "blocked",
                "Import discovered documentation and test conventions",
                "agent_researcher",
                82,
                "Translate the discovered docs ({docs}) and tests ({tests}) into explicit operator-reviewed workflows.".format(
                    docs=docs,
                    tests=tests,
                ),
                BROWNFIELD_PENDING_REVIEW_STATE,
                0,
                scoped_paths=_brownfield_docs_and_tests_paths(discovery),
            )
        )

    task_specs.append(
        _brownfield_task_spec(
            "blocked",
            "Align runtime and provider settings with existing tooling",
            "agent_builder",
            84,
            "Compare MAAS runtime expectations against the discovered {primary_language} stack and project tooling.".format(
                primary_language=primary_language
            ),
            BROWNFIELD_PENDING_REVIEW_STATE,
            0,
            scoped_paths=_runtime_alignment_paths(discovery),
        )
    )

    if len(task_specs) == 1:
        task_specs.extend(
            [
                _brownfield_task_spec(
                    "blocked",
                    "Validate imported workflow entrypoints",
                    "agent_researcher",
                    92,
                    "Confirm the imported repo workflow surfaces before wider automation starts.",
                    BROWNFIELD_PENDING_REVIEW_STATE,
                    0,
                    scoped_paths=discovery.get("sample_files", [])[:2],
                ),
                _brownfield_task_spec(
                    "blocked",
                    "Map imported repository areas",
                    "agent_allocator",
                    88,
                    "Turn the imported repository structure ({top_dirs}) into operator-visible work areas.".format(
                        top_dirs=top_dirs
                    ),
                    BROWNFIELD_PENDING_REVIEW_STATE,
                    0,
                    scoped_paths=discovery.get("sample_files", [])[:3],
                ),
            ]
        )
    return task_specs


def _normalize_task_spec(task_spec):
    if isinstance(task_spec, dict):
        normalized = dict(task_spec)
        normalized.setdefault("acceptance_criteria", [{"type": "artifact_exists"}])
        return normalized

    status, title, agent_id, priority, description, review_state, progress_pct = task_spec
    return {
        "status": status,
        "title": title,
        "agent_id": agent_id,
        "priority": priority,
        "description": description,
        "review_state": review_state,
        "progress_pct": progress_pct,
        "acceptance_criteria": [{"type": "artifact_exists"}],
    }


def seed_project(
    connection,
    config,
    mode="greenfield",
    discovery=None,
    source_root=None,
    stable_agent_ids=False,
    seed_runtime_demo=True,
):
    project_id = generate_id("proj")
    project = config["project"]
    project_source_root = source_root or project.get("source_root") or ""
    connection.execute(
        """
        INSERT INTO projects (project_id, name, description, project_type, config_json, state, source_root)
        VALUES (?, ?, ?, ?, ?, 'active', ?)
        """,
        (
            project_id,
            project["name"],
            project["description"],
            project["type"],
            json.dumps(config),
            project_source_root,
        ),
    )

    agents = []
    agent_ids = {}
    for role in config["agent_roles"]:
        default_agent_id = "agent_{role}".format(role=role["role"])
        agent_id = default_agent_id if stable_agent_ids else generate_id("agent")
        agent_ids[default_agent_id] = agent_id
        agent_ids[role["role"]] = agent_id
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
    for raw_task_spec in task_specs:
        task_spec = _normalize_task_spec(raw_task_spec)
        status = task_spec["status"]
        title = task_spec["title"]
        agent_id = task_spec["agent_id"]
        priority = task_spec["priority"]
        description = task_spec["description"]
        review_state = task_spec["review_state"]
        progress_pct = task_spec["progress_pct"]
        acceptance_criteria = task_spec.get("acceptance_criteria") or [{"type": "artifact_exists"}]
        task_id = generate_id("task")
        task_ids.append(task_id)
        assigned_agent_id = agent_ids.get(agent_id, agent_id)
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
                assigned_agent_id,
                json.dumps(acceptance_criteria),
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
                assigned_agent_id,
                json.dumps(acceptance_criteria),
                progress_pct,
                review_state,
                None,
            ),
            )

        if assigned_agent_id and status in ("planned", "ready", "assigned", "in_progress", "blocked"):
            grant_task_capabilities(
                connection,
                project_id,
                task_id,
                assigned_agent_id,
                TASK_EXECUTION_CAPABILITIES,
                granted_by="system_bootstrap",
            )

    if mode == "greenfield" and seed_runtime_demo:
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
            (generate_id("sess"), project_id, agent_ids["agent_builder"], task_ids[2]),
        )
        connection.execute(
            """
            UPDATE agents
            SET status = 'running', current_task_id = ?, last_heartbeat_at = CURRENT_TIMESTAMP
            WHERE agent_id = ?
            """,
            (task_ids[2], agent_ids["agent_builder"]),
        )

        connection.execute(
            """
            INSERT INTO activity_log (
                activity_id, project_id, agent_id, task_id, action, category, description, severity
            ) VALUES (?, ?, ?, ?, 'task_started', 'runtime', 'Builder picked up board endpoint work.', 'info')
            """,
            (generate_id("act"), project_id, agent_ids["agent_builder"], task_ids[2]),
        )
        connection.execute(
            """
            INSERT INTO alerts (
                alert_id, project_id, severity, title, description, status
            ) VALUES (?, ?, 'warning', 'Broader provider integrations pending', 'Simulated adapters and explicit local CLI modes are available, but broader provider coverage is still pending.', 'open')
            """,
            (generate_id("alert"), project_id),
        )
    elif mode == "greenfield":
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
        discovery_summary=build_discovery_summary(discovery),
        source_root=paths.root,
    )
    if resolved_mode == "brownfield":
        onboarding = dict(config.get("onboarding") or {})
        onboarding["review_overrides"] = default_onboarding_review_overrides(onboarding.get("discovery_summary") or {})
        config["onboarding"] = onboarding
    save_project_config(paths.project_config, config)
    with open(paths.understanding_path, "w", encoding="utf-8") as handle:
        handle.write(build_understanding_markdown(config, mode=resolved_mode, discovery=discovery))
    if discovery:
        with open(paths.discovery_path, "w", encoding="utf-8") as handle:
            json.dump(discovery, handle, indent=2, sort_keys=True)

    run_migrations(project_root, paths)
    connection = connect(paths)
    project_id = seed_project(
        connection,
        config,
        mode=resolved_mode,
        discovery=discovery,
        source_root=paths.root,
        stable_agent_ids=True,
        seed_runtime_demo=True,
    )
    connection.close()
    return {"paths": paths, "config": config, "project_id": project_id, "mode": resolved_mode, "discovery": discovery}
