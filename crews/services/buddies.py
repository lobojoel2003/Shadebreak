"""Pair workers so everyone has someone watching them.

Order of preference:

1. A pairing the crew lead set by hand for the day.
2. The standing buddy on the worker's profile, if both are on site.
3. New or acclimatizing workers paired with experienced ones. When there
   are more new workers than free experienced ones, an experienced worker
   watches more than one (one-way), rather than two new workers watching
   each other.
4. Everyone else, two by two. An odd worker out is watched by someone
   experienced (a one-way pairing), so no one is left alone.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from ..models import Assignment


def pair_buddies(assignments: Sequence[Assignment]) -> None:
    present = [a for a in assignments if a.present]
    by_worker = {a.worker_id: a for a in present}

    for a in present:
        keep = a.buddy_manual and a.buddy_id in by_worker and a.buddy_id != a.worker_id
        if not keep:
            a.buddy_id = None
            a.buddy_manual = False

    for a in present:
        standing = a.worker.buddy_id
        if a.buddy_id or standing not in by_worker or standing == a.worker_id:
            continue
        partner = by_worker[standing]
        if partner.buddy_id in (None, a.worker_id):
            a.buddy_id = partner.worker_id
            partner.buddy_id = a.worker_id

    unpaired = [a for a in present if not a.buddy_id]
    vulnerable = [a for a in unpaired if a.needs_extra_care]
    seasoned = [a for a in unpaired if not a.needs_extra_care]

    def pair(first: Assignment, second: Assignment) -> None:
        first.buddy_id = second.worker_id
        second.buddy_id = first.worker_id

    while vulnerable and seasoned:
        pair(vulnerable.pop(0), seasoned.pop(0))

    experienced = [a for a in present if not a.needs_extra_care]
    if vulnerable and experienced:
        load = Counter(a.buddy_id for a in present if a.buddy_id)
        for a in vulnerable:
            helper = min(experienced, key=lambda e: (load[e.worker_id], e.worker.name))
            a.buddy_id = helper.worker_id
            load[helper.worker_id] += 1
        vulnerable = []

    rest = vulnerable + seasoned
    while len(rest) >= 2:
        pair(rest.pop(0), rest.pop(0))
    if rest:
        lone = rest[0]
        others = [a for a in present if a.worker_id != lone.worker_id]
        others.sort(key=lambda a: a.needs_extra_care)  # experienced first
        if others:
            lone.buddy_id = others[0].worker_id
