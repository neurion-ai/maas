"""Shared helpers for MAAS API tests."""

from contextlib import contextmanager

from fastapi.testclient import TestClient

from maas.api import create_app


@contextmanager
def api_client(project_root=".", **kwargs):
    """Create a closeable API client without entering FastAPI lifespan hooks."""

    client = TestClient(create_app(project_root, enable_lifespan_autopilot=False), **kwargs)
    try:
        yield client
    finally:
        client.close()
