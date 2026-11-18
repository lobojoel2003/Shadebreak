import importlib.util
import re
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from django.template import Context, Template
from django.test import RequestFactory

import shadebreak

ROOT = Path(__file__).resolve().parent.parent


def load_release(tmp_path):
    """Import scripts/release.py pointed at copies of the version and changelog."""
    (tmp_path / "shadebreak").mkdir()
    shutil.copy(ROOT / "shadebreak" / "__init__.py", tmp_path / "shadebreak" / "__init__.py")
    shutil.copy(ROOT / "CHANGELOG.md", tmp_path / "CHANGELOG.md")
    spec = importlib.util.spec_from_file_location("release_under_test", ROOT / "scripts" / "release.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = tmp_path
    module.INIT = tmp_path / "shadebreak" / "__init__.py"
    module.CHANGELOG = tmp_path / "CHANGELOG.md"
    return module


def test_version_is_semver_and_in_changelog():
    assert re.fullmatch(r"\d+\.\d+\.\d+", shadebreak.__version__)
    changelog = (ROOT / "CHANGELOG.md").read_text()
    assert f"## [{shadebreak.__version__}]" in changelog
    assert "## [Unreleased]" in changelog


def test_release_notes_and_tag_check(tmp_path, capsys):
    release = load_release(tmp_path)
    notes = release.notes(shadebreak.__version__)
    assert "### Added" in notes and "[Unreleased]:" not in notes
    release.check_tag(f"v{shadebreak.__version__}")
    release.check_tag(f"refs/tags/v{shadebreak.__version__}")
    with pytest.raises(SystemExit):
        release.check_tag("v0.0.1")
    with pytest.raises(SystemExit):
        release.notes("9.9.9")


def test_release_bump(tmp_path):
    release = load_release(tmp_path)
    with pytest.raises(SystemExit):
        release.bump("1.2")
    release.bump("1.1.0")
    assert release.current_version() == "1.1.0"
    text = release.CHANGELOG.read_text()
    assert "## [Unreleased]\n\n## [1.1.0] - " in text
    assert "[1.1.0]: https://github.com/lobojoel2003/shadebreak/compare/v1.0.0...v1.1.0" in text
    assert release.notes("1.1.0") == "\n"  # nothing recorded yet for the new version


def test_release_cli(tmp_path, monkeypatch, capsys):
    release = load_release(tmp_path)
    monkeypatch.setattr(sys, "argv", ["release.py", "notes", shadebreak.__version__])
    release.main()
    assert "Morning screen" in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["release.py"])
    with pytest.raises(SystemExit):
        release.main()


def render(template: str, **context) -> str:
    return Template("{% load shadebreak %}" + template).render(Context(context))


class Site:
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("America/Phoenix")


def test_template_tags():
    site = Site()
    start = datetime(2026, 7, 15, 13, 15, tzinfo=UTC)  # 6:15 AM in Phoenix
    end = datetime(2026, 7, 15, 13, 30, tzinfo=UTC)
    noon = datetime(2026, 7, 15, 19, 30, tzinfo=UTC)
    assert render("{% time_range a b s %}", a=start, b=end, s=site) == "6:15–6:30 AM"
    assert render("{% time_range a b s %}", a=start, b=noon, s=site) == "6:15 AM–12:30 PM"
    assert render("{{ t|hour_number:s }}{{ t|meridiem:s }}", t=noon, s=site) == "12PM"
    assert render("{{ c|f }}|{{ none|f }}", c=30, none=None) == "86|"
    assert render("{{ r|risk_slug }}|{{ r|risk_label }}|{{ n|risk_slug }}", r=3, n=None) == "very-high|Very high|unknown"
    assert render("{{ p|phone }}", p="+16025550142") == "(602) 555-0142"
    assert render("{{ t|local }}", t=None) == ""
    assert render("{{ b|minutes_between:a }}", a=start, b=end) == "15"


def test_query_tag_keeps_other_parameters():
    request = RequestFactory().get("/messages/", {"kind": "break", "page": "2"})
    assert render("{% query page='' status='failed' %}", request=request) == "?kind=break&amp;status=failed"
