"""Safe source-repository browsing for brownfield projects."""

import os

from maas.services.bootstrap import IGNORED_DISCOVERY_DIRS
from maas.services.projects import resolve_project


REPO_PREVIEW_MAX_BYTES = 32 * 1024
REPO_TREE_MAX_ENTRIES = 200
IGNORED_REPO_FILE_NAMES = {"project.yaml"}
TEXT_PREVIEW_EXTENSIONS = {
    ".c",
    ".cc",
    ".cpp",
    ".css",
    ".go",
    ".h",
    ".hpp",
    ".html",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".py",
    ".rb",
    ".rs",
    ".sh",
    ".sql",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}


def _project_source_root(connection, project_id=None):
    project = resolve_project(connection, project_id)
    if project is None:
        raise ValueError("project not found")
    source_root = os.path.abspath(project["source_root"] or "")
    if not source_root or not os.path.isdir(source_root):
        raise ValueError("project source root is unavailable")
    return source_root


def _resolve_repo_path(source_root, relative_path=""):
    requested = (relative_path or "").strip()
    normalized = os.path.normpath(requested or ".")
    if normalized == ".":
        full_path = source_root
        relative = ""
    else:
        if os.path.isabs(normalized):
            raise ValueError("path must be relative to the project source root")
        full_path = os.path.abspath(os.path.join(source_root, normalized))
        relative = normalized
    if os.path.commonpath([source_root, full_path]) != source_root:
        raise ValueError("path escapes the project source root")
    return full_path, relative


def _previewable_extension(path):
    return os.path.splitext(path)[1].lower() in TEXT_PREVIEW_EXTENSIONS


def fetch_repo_tree(connection, project_id=None, path=""):
    source_root = _project_source_root(connection, project_id=project_id)
    full_path, relative_path = _resolve_repo_path(source_root, path)
    if not os.path.exists(full_path):
        raise FileNotFoundError(relative_path or ".")
    if not os.path.isdir(full_path):
        raise ValueError("path is not a directory")

    entries = []
    for name in sorted(os.listdir(full_path)):
        if name in IGNORED_DISCOVERY_DIRS or name in IGNORED_REPO_FILE_NAMES or name == ".DS_Store":
            continue
        child_full_path = os.path.join(full_path, name)
        child_relative_path = os.path.relpath(child_full_path, source_root)
        if os.path.isdir(child_full_path):
            entries.append(
                {
                    "name": name,
                    "path": child_relative_path,
                    "kind": "directory",
                    "size": None,
                    "extension": None,
                    "previewable": False,
                }
            )
        elif os.path.isfile(child_full_path):
            entries.append(
                {
                    "name": name,
                    "path": child_relative_path,
                    "kind": "file",
                    "size": os.path.getsize(child_full_path),
                    "extension": os.path.splitext(name)[1].lower() or None,
                    "previewable": _previewable_extension(child_full_path),
                }
            )
        if len(entries) >= REPO_TREE_MAX_ENTRIES:
            break

    entries.sort(key=lambda item: (item["kind"] != "directory", item["name"].lower()))
    return {
        "path": relative_path,
        "parent_path": os.path.dirname(relative_path) if relative_path else None,
        "source_root": source_root,
        "entries": entries,
    }


def fetch_repo_file_preview(connection, project_id=None, path=""):
    source_root = _project_source_root(connection, project_id=project_id)
    full_path, relative_path = _resolve_repo_path(source_root, path)
    if not os.path.exists(full_path):
        raise FileNotFoundError(relative_path or path or ".")
    if not os.path.isfile(full_path):
        raise ValueError("path is not a regular file")

    size = os.path.getsize(full_path)
    extension = os.path.splitext(full_path)[1].lower() or None
    previewable = _previewable_extension(full_path)
    response = {
        "path": relative_path,
        "name": os.path.basename(full_path),
        "parent_path": os.path.dirname(relative_path) if relative_path else None,
        "size": size,
        "extension": extension,
        "previewable": previewable,
        "content_kind": "binary",
        "content": None,
        "truncated": False,
    }
    if not previewable:
        return response

    with open(full_path, "rb") as handle:
        raw = handle.read(REPO_PREVIEW_MAX_BYTES + 1)
    response["truncated"] = len(raw) > REPO_PREVIEW_MAX_BYTES
    raw = raw[:REPO_PREVIEW_MAX_BYTES]
    if b"\x00" in raw:
        return response

    response["content"] = raw.decode("utf-8", errors="replace")
    response["content_kind"] = "json" if extension == ".json" else "text"
    return response
