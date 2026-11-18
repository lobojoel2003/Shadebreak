"""Small, explicit unit conversions."""

from __future__ import annotations


def c_to_f(celsius: float) -> float:
    return celsius * 9.0 / 5.0 + 32.0


def f_to_c(fahrenheit: float) -> float:
    return (fahrenheit - 32.0) * 5.0 / 9.0


def kmh_to_ms(kmh: float) -> float:
    return kmh / 3.6


def mph_to_ms(mph: float) -> float:
    return mph * 0.44704


def knots_to_ms(knots: float) -> float:
    return knots * 0.514444


def ms_to_mph(ms: float) -> float:
    return ms / 0.44704
