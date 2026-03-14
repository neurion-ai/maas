"""Helpers for stable human-readable IDs without extra dependencies."""

from datetime import datetime
from uuid import uuid4


def generate_id(prefix):
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    return "{prefix}_{timestamp}_{suffix}".format(
        prefix=prefix,
        timestamp=timestamp,
        suffix=uuid4().hex[:8],
    )

