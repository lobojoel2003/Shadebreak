"""Release helper: bump the version, extract notes, verify a tag.

    python scripts/release.py bump 1.1.0      # set __version__, date the changelog
    python scripts/release.py notes 1.1.0     # print that version's changelog section
    python scripts/release.py check-tag v1.1.0

Versions follow Semantic Versioning (https://semver.org). The changelog
follows Keep a Changelog (https://keepachangelog.com).
"""

from __future__ import annotations

import datetime as dt
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INIT = ROOT / "shadebreak" / "__init__.py"
CHANGELOG = ROOT / "CHANGELOG.md"
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$")
REPO = "https://github.com/lobojoel2003/shadebreak"


def current_version() -> str:
    match = re.search(r'^__version__ = "([^"]+)"', INIT.read_text(), re.MULTILINE)
    if not match:
        sys.exit("Could not find __version__ in shadebreak/__init__.py")
    return match.group(1)


def notes(version: str) -> str:
    text = CHANGELOG.read_text()
    pattern = rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|^\[[^\]]+\]: |\Z)"
    match = re.search(pattern, text, re.MULTILINE | re.DOTALL)
    if not match:
        sys.exit(f"CHANGELOG.md has no section for {version}")
    return match.group(1).strip() + "\n"


def bump(version: str) -> None:
    if not SEMVER.match(version):
        sys.exit(f"{version!r} is not a semantic version like 1.2.3")
    previous = current_version()
    INIT.write_text(INIT.read_text().replace(f'__version__ = "{previous}"', f'__version__ = "{version}"'))
    today = dt.date.today().isoformat()
    text = CHANGELOG.read_text()
    if "## [Unreleased]" not in text:
        sys.exit("CHANGELOG.md needs an '## [Unreleased]' section")
    text = text.replace("## [Unreleased]", f"## [Unreleased]\n\n## [{version}] - {today}", 1)
    text = re.sub(
        r"^\[Unreleased\]: .*$",
        f"[Unreleased]: {REPO}/compare/v{version}...HEAD\n"
        f"[{version}]: {REPO}/compare/v{previous}...v{version}",
        text,
        count=1,
        flags=re.MULTILINE,
    )
    CHANGELOG.write_text(text)
    print(f"Bumped {previous} -> {version}. Review CHANGELOG.md, commit, then tag v{version}.")


def check_tag(tag: str) -> None:
    version = current_version()
    if tag.removeprefix("refs/tags/") != f"v{version}":
        sys.exit(f"Tag {tag} does not match shadebreak.__version__ ({version}).")
    notes(version)  # the changelog must describe the release
    print(f"Tag {tag} matches version {version}.")


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] not in {"bump", "notes", "check-tag"}:
        sys.exit(__doc__)
    command, value = sys.argv[1], sys.argv[2]
    if command == "bump":
        bump(value)
    elif command == "notes":
        sys.stdout.write(notes(value))
    else:
        check_tag(value)


if __name__ == "__main__":
    main()
