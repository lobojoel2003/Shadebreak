import pytest

from crews.models import Experience
from crews.plan import render_plan_html, render_plan_pdf
from crews.services.planning import ensure_workday, plan_workday

from .conftest import PHOENIX_DAY

pytestmark = pytest.mark.django_db


@pytest.fixture
def planned_day(site, hot_day, make_worker):
    make_worker("Vera Veteran")
    make_worker("Rico Rookie", experience=Experience.NEW, start_date=PHOENIX_DAY)
    workday, _ = ensure_workday(site, PHOENIX_DAY)
    plan_workday(workday)
    return workday


def test_plan_html_has_every_section(crew, planned_day):
    html = render_plan_html(crew, PHOENIX_DAY, "en")
    for text in [
        "Heat illness prevention plan",
        "How we rate heat and what we do",
        "Desert Park",
        "Rest breaks",
        "Rico Rookie",
        "Ramp day 1 of 5",
        "A gradual start for new and returning workers",
        "Heat stroke: a medical emergency",
        "Sign-off",
        "Call 911 now.",
    ]:
        assert text in html, text


def test_plan_pdf_renders(crew, planned_day):
    pdf = render_plan_pdf(crew, PHOENIX_DAY, "en")
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 10_000


def test_plan_view_pdf_html_and_spanish(logged_in, planned_day):
    response = logged_in.get(f"/plan.pdf?date={PHOENIX_DAY.isoformat()}")
    assert response["Content-Type"] == "application/pdf"
    assert "inline" in response["Content-Disposition"]
    download = logged_in.get(f"/plan.pdf?date={PHOENIX_DAY.isoformat()}&download=1&lang=es")
    assert "attachment" in download["Content-Disposition"] and "-es.pdf" in download["Content-Disposition"]
    html = logged_in.get(f"/plan.pdf?date={PHOENIX_DAY.isoformat()}&format=html&lang=es").content.decode()
    assert "Plan de prevención de enfermedades por calor" in html
    assert logged_in.get("/plan.pdf?lang=xx&format=html").status_code == 200
    assert logged_in.get("/plan/").status_code == 200


def test_plan_for_day_without_work(crew):
    html = render_plan_html(crew, PHOENIX_DAY, "en")
    assert "No sites are scheduled to work on this day." in html
