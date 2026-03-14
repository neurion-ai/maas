"""SQLite utilities and migration runner."""

import os
import sqlite3

from maas.paths import ProjectPaths


def connect(paths):
    connection = sqlite3.connect(paths.db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA busy_timeout=5000")
    return connection


def migration_dir(project_root):
    del project_root
    package_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(package_root, "migrations")


def ensure_meta_tables(connection):
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.commit()


def applied_versions(connection):
    ensure_meta_tables(connection)
    rows = connection.execute("SELECT version FROM schema_migrations").fetchall()
    return {row["version"] for row in rows}


def run_migrations(project_root, paths):
    paths.ensure_directories()
    connection = connect(paths)
    ensure_meta_tables(connection)
    already_applied = applied_versions(connection)
    migrations_path = migration_dir(project_root)
    applied = []
    for filename in sorted(os.listdir(migrations_path)):
        if not filename.endswith(".sql") or filename in already_applied:
            continue
        full_path = os.path.join(migrations_path, filename)
        with open(full_path, "r", encoding="utf-8") as handle:
            connection.executescript(handle.read())
        connection.execute(
            "INSERT INTO schema_migrations (version) VALUES (?)",
            (filename,),
        )
        connection.commit()
        applied.append(filename)
    connection.close()
    return applied


def project_paths(project_root):
    return ProjectPaths(project_root)
