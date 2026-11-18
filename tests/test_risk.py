import pytest

from heat.risk import (
    CLOTHING_ADJUSTMENT_C,
    STOP_WORK,
    Clothing,
    Risk,
    Workload,
    hourly_risk,
    lighter,
    rest_minutes_per_hour,
    risk_from_heat_index,
    risk_from_wbgt_c,
)
from heat.units import f_to_c


@pytest.mark.parametrize(
    ("hi", "level"),
    [
        (79.9, Risk.LOW),
        (80, Risk.CAUTION),
        (89.9, Risk.CAUTION),
        (90, Risk.HIGH),
        (103, Risk.VERY_HIGH),
        (115, Risk.EXTREME),
    ],
)
def test_heat_index_levels(hi, level):
    assert risk_from_heat_index(hi) == level


@pytest.mark.parametrize(
    ("wbgt_f", "level"),
    [(79.9, Risk.LOW), (80, Risk.CAUTION), (85, Risk.HIGH), (88, Risk.VERY_HIGH), (90, Risk.EXTREME)],
)
def test_wbgt_levels(wbgt_f, level):
    assert risk_from_wbgt_c(f_to_c(wbgt_f)) == level


def test_hourly_risk_takes_the_higher_scale():
    assert hourly_risk(85, f_to_c(91)) == Risk.EXTREME
    assert hourly_risk(104, f_to_c(75)) == Risk.VERY_HIGH
    assert Risk.VERY_HIGH.slug == "very-high"


@pytest.mark.parametrize(
    ("wbgt", "workload", "acclimatized", "expected"),
    [
        (27.0, Workload.MODERATE, True, 0),
        (28.5, Workload.MODERATE, True, 15),
        (29.5, Workload.MODERATE, True, 30),
        (31.0, Workload.MODERATE, True, 45),
        (32.0, Workload.MODERATE, True, STOP_WORK),
        (26.0, Workload.HEAVY, True, 0),  # under the continuous heavy TLV from the ACGIH equation
        (27.0, Workload.HEAVY, True, 15),
        (26.0, Workload.HEAVY, False, 45),
        (30.0, Workload.HEAVY, True, 45),
        (24.5, Workload.MODERATE, False, 0),
        (25.5, Workload.MODERATE, False, 15),
        (28.5, Workload.MODERATE, False, 45),
        (29.5, Workload.MODERATE, False, STOP_WORK),
        (24.0, Workload.VERY_HEAVY, False, 30),
        (31.0, Workload.LIGHT, True, 0),
        (33.0, Workload.LIGHT, True, STOP_WORK),
    ],
)
def test_acgih_work_rest_table(wbgt, workload, acclimatized, expected):
    assert rest_minutes_per_hour(wbgt, workload, acclimatized) == expected


def test_clothing_adjustment_is_added():
    assert CLOTHING_ADJUSTMENT_C[Clothing.DOUBLE_LAYER] == 3
    assert rest_minutes_per_hour(27.0, "moderate", True) == 0
    assert rest_minutes_per_hour(27.0, "moderate", True, CLOTHING_ADJUSTMENT_C[Clothing.DOUBLE_LAYER]) == 30
    assert (
        rest_minutes_per_hour(27.0, "moderate", True, CLOTHING_ADJUSTMENT_C[Clothing.VAPOR_BARRIER])
        == STOP_WORK
    )


def test_unacclimatized_limit_is_never_looser():
    for workload in Workload:
        for tenth in range(200, 340):
            wbgt = tenth / 10
            assert rest_minutes_per_hour(wbgt, workload, False) >= rest_minutes_per_hour(wbgt, workload, True)


def test_acgih_equations_fill_the_blank_cells():
    from heat.risk import continuous_action_limit_c, continuous_tlv_c

    assert continuous_tlv_c(Workload.HEAVY) == 26.6
    assert continuous_action_limit_c(Workload.HEAVY) == 23.0
    assert continuous_tlv_c(Workload.VERY_HEAVY) == 25.5
    # The equations reproduce the printed values for light and moderate work.
    assert abs(continuous_tlv_c(Workload.MODERATE) - 28.0) <= 0.2
    assert abs(continuous_action_limit_c(Workload.LIGHT) - 28.0) <= 0.2


def test_clothing_raises_the_risk_level():
    assert hourly_risk(79, 26.0) == Risk.LOW
    assert hourly_risk(79, 26.0, clothing_adjustment_c=3) == Risk.CAUTION  # 29 C = 84.2 F
    assert hourly_risk(79, 26.0, clothing_adjustment_c=11) == Risk.EXTREME


def test_lighter_workload():
    assert lighter(Workload.HEAVY) == Workload.MODERATE
    assert lighter("light") is None
