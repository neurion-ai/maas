"""Project path helpers."""

import os


class ProjectPaths(object):
    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.workspace = os.path.join(self.root, ".maas")
        self.db_path = os.path.join(self.workspace, "state.db")
        self.project_config = os.path.join(self.root, "project.yaml")
        self.artifacts_dir = os.path.join(self.workspace, "artifacts")
        self.logs_dir = os.path.join(self.workspace, "logs")
        self.quarantine_dir = os.path.join(self.workspace, "quarantine")
        self.runtime_dir = os.path.join(self.workspace, "runtime")
        self.understanding_path = os.path.join(self.workspace, "project-understanding.md")
        self.discovery_path = os.path.join(self.workspace, "project-discovery.json")

    def ensure_directories(self):
        for path in (
            self.workspace,
            self.artifacts_dir,
            self.logs_dir,
            self.quarantine_dir,
            self.runtime_dir,
        ):
            os.makedirs(path, exist_ok=True)
