"""Project path helpers."""

import os


class ProjectPaths(object):
    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.workspace = os.path.join(self.root, ".maas")
        self.db_path = os.path.join(self.workspace, "state.db")
        self.project_config = os.path.join(self.root, "project.yaml")
        self.projects_dir = os.path.join(self.workspace, "projects")
        self.artifacts_dir = os.path.join(self.workspace, "artifacts")
        self.logs_dir = os.path.join(self.workspace, "logs")
        self.quarantine_dir = os.path.join(self.workspace, "quarantine")
        self.runtime_dir = os.path.join(self.workspace, "runtime")
        self.understanding_path = os.path.join(self.workspace, "project-understanding.md")
        self.discovery_path = os.path.join(self.workspace, "project-discovery.json")

    def ensure_directories(self):
        for path in (
            self.workspace,
            self.projects_dir,
            self.artifacts_dir,
            self.logs_dir,
            self.quarantine_dir,
            self.runtime_dir,
        ):
            os.makedirs(path, exist_ok=True)

    def project_workspace(self, project_id):
        return os.path.join(self.projects_dir, project_id)

    def project_understanding_path(self, project_id):
        return os.path.join(self.project_workspace(project_id), "project-understanding.md")

    def project_discovery_path(self, project_id):
        return os.path.join(self.project_workspace(project_id), "project-discovery.json")

    def project_runtime_dir(self, project_id):
        return os.path.join(self.project_workspace(project_id), "runtime")

    def project_runtime_tmp_dir(self, project_id):
        return os.path.join(self.project_runtime_dir(project_id), "tmp")

    def ensure_project_workspace(self, project_id):
        os.makedirs(self.project_workspace(project_id), exist_ok=True)
        os.makedirs(self.project_runtime_dir(project_id), exist_ok=True)
