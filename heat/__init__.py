"""Heat-stress science used by Shadebreak.

This package is plain Python with no Django imports, so every rule that
decides a break, a risk level or a reduced shift can be unit-tested on its own
and read in one place:

* :mod:`heat.units` - unit conversions.
* :mod:`heat.solar` - sun position and an estimate of sunlight on the ground.
* :mod:`heat.indices` - NWS heat index and wet bulb globe temperature (WBGT).
* :mod:`heat.risk` - risk levels and the ACGIH work/rest limits.
* :mod:`heat.acclimatization` - the NIOSH day-by-day ramp for new workers.
* :mod:`heat.schedule` - turns hourly conditions into breaks and check-ins.
"""
