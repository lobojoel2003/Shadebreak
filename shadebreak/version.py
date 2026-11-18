"""Version and build information.

The semantic version lives in ``shadebreak.__version__``. CI stamps each
build with a build number (the commit count on main), the commit and the
build date through environment variables baked into the Docker image.
"""

from __future__ import annotations

import os
from functools import lru_cache

from . import __version__


@lru_cache(maxsize=1)
def build_info() -> dict[str, str]:
    commit = os.environ.get("SHADEBREAK_GIT_SHA", "").strip()
    return {
        "version": __version__,
        "build": os.environ.get("SHADEBREAK_BUILD_NUMBER", "").strip() or "dev",
        "commit": commit[:7],
        "date": os.environ.get("SHADEBREAK_BUILD_DATE", "").strip(),
    }


def version_string() -> str:
    info = build_info()
    parts = [f"v{info['version']}", f"build {info['build']}"]
    if info["commit"]:
        parts.append(info["commit"])
    return " · ".join(parts)
