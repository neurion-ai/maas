"""Native system dialog helpers for the local control room."""

from __future__ import annotations

import os
import platform
import subprocess


def pick_directory_via_native_dialog() -> dict:
    """Open a native folder picker and return the selected absolute path."""

    if platform.system() != "Darwin":
        raise RuntimeError("Native folder picking is currently supported only on macOS.")

    result = subprocess.run(
        [
            "osascript",
            "-e",
            'POSIX path of (choose folder with prompt "Select a repository to import into MAAS")',
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        if "-128" in stderr:
            return {"cancelled": True, "path": None}
        raise RuntimeError(stderr or "Folder picker failed.")
    selected_path = (result.stdout or "").strip()
    if not selected_path:
        return {"cancelled": True, "path": None}
    return {"cancelled": False, "path": os.path.abspath(selected_path)}
