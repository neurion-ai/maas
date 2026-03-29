"""Shared helpers for MAAS API tests."""

from contextlib import contextmanager

from fastapi.testclient import TestClient

from maas.api import create_app
from maas.paths import ProjectPaths
from maas.services.autopilot import stop_all_autopilots


@contextmanager
def api_client(project_root=".", **kwargs):
    """Create a closeable API client without entering FastAPI lifespan hooks."""

    client = TestClient(create_app(project_root, enable_lifespan_autopilot=False), **kwargs)
    try:
        yield client
    finally:
        client.close()
        stop_all_autopilots(ProjectPaths(project_root))
