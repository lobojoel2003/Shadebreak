import pytest

from crews.models import Assignment, Experience, WorkDay
from crews.services.buddies import pair_buddies

from .conftest import PHOENIX_DAY

pytestmark = pytest.mark.django_db


@pytest.fixture
def workday(site):
    return WorkDay.objects.create(
        site=site, date=PHOENIX_DAY, start_time=site.shift_start, end_time=site.shift_end
    )


def assign(workday, worker, **kwargs):
    return Assignment.objects.create(workday=workday, worker=worker, **kwargs)


def test_new_workers_pair_with_experienced(workday, make_worker):
    vets = [assign(workday, make_worker(f"Vet {i}")) for i in range(2)]
    rookies = [assign(workday, make_worker(f"New {i}"), first_week=True) for i in range(2)]
    pair_buddies(vets + rookies)
    for rookie in rookies:
        partner = next(a for a in vets if a.worker_id == rookie.buddy_id)
        assert partner.buddy_id == rookie.worker_id


def test_standing_buddies_are_kept(workday, make_worker):
    a, b, c = make_worker("A"), make_worker("B"), make_worker("C")
    a.buddy = b
    a.save()
    rows = [assign(workday, w) for w in (a, b, c)]
    pair_buddies(rows)
    assert rows[0].buddy_id == b.pk and rows[1].buddy_id == a.pk
    assert rows[2].buddy_id in (a.pk, b.pk)  # odd one out is watched by someone


def test_manual_choice_wins_and_absent_are_skipped(workday, make_worker):
    a, b, c, d = (make_worker(n) for n in "ABCD")
    rows = [
        assign(workday, a, buddy=c, buddy_manual=True),
        assign(workday, b),
        assign(workday, c),
        assign(workday, d, status=Assignment.Status.ABSENT),
    ]
    pair_buddies(rows)
    assert rows[0].buddy_id == c.pk and rows[0].buddy_manual
    assert rows[3].buddy_id is None
    assert rows[1].buddy_id is not None


def test_manual_buddy_who_is_absent_is_replaced(workday, make_worker):
    a, b, c = make_worker("A"), make_worker("B"), make_worker("C")
    rows = [
        assign(workday, a, buddy=c, buddy_manual=True),
        assign(workday, b),
        assign(workday, c, status="absent"),
    ]
    pair_buddies(rows)
    assert rows[0].buddy_id == b.pk and not rows[0].buddy_manual


def test_single_worker_has_no_buddy(workday, make_worker):
    rows = [assign(workday, make_worker("Solo", experience=Experience.NEW), first_week=True)]
    pair_buddies(rows)
    assert rows[0].buddy_id is None
