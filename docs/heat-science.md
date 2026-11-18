# How Shadebreak decides

Every rule that changes a worker's day lives in the `heat/` package, which is
plain Python with no Django imports and its own tests. This page explains each
step and where it comes from.

> Shadebreak is a planning aid. It does not replace a qualified safety
> professional, medical advice, or the OSHA and state rules that apply to you.

## 1. Forecast

For each job site Shadebreak calls the free National Weather Service API:

1. `GET /points/{lat},{lon}` once, to find the forecast office grid square and
   the site's time zone (cached on the site).
2. `GET /gridpoints/{office}/{x},{y}` every hour, for the raw hourly grids:
   temperature, dew point, relative humidity, wind speed, sky cover and
   chance of rain. Values come with ISO 8601 intervals
   (`2026-07-15T18:00:00+00:00/PT3H`), which are expanded to one value per hour.

If the forecast office publishes its own WBGT grid for an hour, a full-sun site
uses it. Missing sky cover is treated as clear sky and missing wind as light
air, both on the cautious side. Source: `nws/client.py`.

## 2. Sunlight

WBGT depends heavily on sun, which the forecast does not give directly.
Shadebreak estimates it for the middle of each hour (`heat/solar.py`):

| Step | Model |
| --- | --- |
| Sun position | NOAA "General Solar Position Calculations" (Spencer 1971 series) |
| Clear-sky sunlight | Haurwitz (1945): `1098 · cos z · exp(−0.059 / cos z)` W/m² |
| Clouds | Kasten & Czeplak (1980): `× (1 − 0.75 · N^3.4)`, N = sky cover |
| Direct vs. diffuse | Erbs, Klein & Duffie (1982) correlation |

## 3. Heat index and WBGT

* **Heat index** follows the NWS algorithm: Steadman's simple formula below
  80 °F, otherwise the Rothfusz regression with the NWS low- and high-humidity
  adjustments (`heat/indices.py`). Tests check it against the NWS chart.
* **WBGT** uses the Liljegren et al. (2008) energy-balance model as implemented
  and validated in ECMWF's open source [`thermofeel`](https://github.com/ecmwf/thermofeel)
  (`calculate_wbgt_liljegren`). Inputs: temperature, humidity, station
  pressure (from elevation), 10 m wind, sunlight and the direct-beam fraction.
  If the solver does not converge (rare), the ACSM/BoM screening approximation
  is used for that hour.
* **Exposure:** a *mostly shaded* site uses WBGT with no sunlight, a *partly
  shaded* site the average of sun and shade, and *full sun* the full value.
  The dashboard also shows shade WBGT, what a resting worker feels.

WBGT counts sun and wind, so on a clear, still afternoon it can read well
above what the heat index suggests. The CDC/NIOSH note that heat index can
read up to 15 °F low in full sun.

## 4. Risk levels

Each hour gets the higher of two ratings (`heat/risk.py`):

| Level | Heat index | WBGT | Where the line comes from |
| --- | --- | --- | --- |
| Low | below 80 °F | below 80 °F | |
| Caution | 80–89 °F | 80–84.9 °F | 2024 proposed OSHA rule "initial heat trigger"; NWS "caution" |
| High | 90–102 °F | 85–87.9 °F | 2024 proposed OSHA rule "high heat trigger"; NWS "extreme caution" |
| Very high | 103–114 °F | 88–89.9 °F | NWS "danger" |
| Extreme | 115 °F and up | 90 °F and up | OSHA-NIOSH Heat Safety Tool "very high to extreme" |

The WBGT categories match those used in NWS WBGT forecasts. The OSHA heat
rule was *proposed* in 2024; check its current status, and any state heat
rule that applies to you (for example California, Washington, Oregon,
Colorado or Maryland), before relying on it.

## 5. Breaks

Each shift is cut into one-hour blocks from its start. For each block
(`heat/schedule.py`):

1. **Below Caution:** no fixed breaks. Water and shade must still be close, and
   anyone may rest at any time.
2. **WBGT at Caution or above** (WBGT plus the clothing adjustment ≥ 80 °F):
   the ACGIH screening table sets the rest per hour for the site's workload.
   Acclimatized workers use the **TLV**; workers still acclimatizing use the
   stricter **Action Limit**. This is the table reproduced in the OSHA
   Technical Manual, Section III, Chapter 4 (°C WBGT):

   | Work per hour | Light | Moderate | Heavy | Very heavy |
   | --- | --- | --- | --- | --- |
   | **TLV** 75–100% | 31.0 | 28.0 | – | – |
   | 50–75% | 31.0 | 29.0 | 27.5 | – |
   | 25–50% | 32.0 | 30.0 | 29.0 | 28.0 |
   | 0–25% | 32.5 | 31.5 | 30.5 | 30.0 |
   | **Action Limit** 75–100% | 28.0 | 25.0 | – | – |
   | 50–75% | 28.5 | 26.0 | 24.0 | – |
   | 25–50% | 29.5 | 27.0 | 25.5 | 24.5 |
   | 0–25% | 30.0 | 29.0 | 28.0 | 27.0 |

   The resulting rest is 0, 15, 30 or 45 minutes at the end of each hour. A dash
   means ACGIH gives no value for that much work, so at least the next row
   applies. Clothing adjustment values: double-layer woven coveralls +3 °C,
   polyolefin coveralls +1 °C, vapor-barrier suits +11 °C.
3. **At High or above,** nobody works more than two hours without a 15-minute
   rest (the 2024 proposed rule's high-heat break).
4. **Stop:** if even 45 minutes of rest an hour exceeds the limit, the block is
   marked *stop* for that workload: switch to light tasks in shade or move the
   work to a cooler time.

## 6. A gradual start (acclimatization)

From NIOSH's *Criteria for a Recommended Standard: Occupational Exposure to
Heat and Hot Environments* (2016), Chapter 4 (`heat/acclimatization.py`):

| Worker | Day 1 | Day 2 | Day 3 | Day 4 | Day 5 |
| --- | --- | --- | --- | --- | --- |
| New to hot work | 20% | 40% | 60% | 80% | 100% |
| Experienced, new to the crew, or returning | 50% | 60% | 80% | 100% | |

* Only **heat days** count: past work days whose forecast peak reached Caution.
* Acclimatization fades with time away. After more than
  `SHADEBREAK_ACCLIMATIZATION_GAP_DAYS` (default 7) without a heat day, the
  worker restarts on the returning ramp (or the new-worker ramp if they never
  finished it). This also restarts everyone at the first heat wave of the season.
* The percentage applies to **hot hours only** (Caution and above), floored to
  15 minutes. A new worker can work a cool morning in full, then stops heat
  exposure at the time shown on the dashboard.
* A crew lead can override the percentage for a worker on a given day.
* Anyone in their first seven days on the crew is flagged **First week**, gets
  hourly buddy check-ins from Caution up, and is always paired with an
  experienced worker when possible.

## 7. Buddy check-ins

At **High**, a buddy checks every 2 hours; at **Very high** and above, every
hour; for first-week and acclimatizing workers, every hour from **Caution**
(`plan_checkins`). The buddy gets a text: *reply 1 if OK, 2 if they need help*.
A `2` (or `help`/`ayuda`) alerts the crew lead immediately. No reply within
`SHADEBREAK_CHECKIN_GRACE_MINUTES` (default 15) alerts the crew lead too, and a
late "OK" is passed on.

## 8. Water

The plan and every briefing repeat the NIOSH/OSHA guidance: 1 cup (8 oz) of
cool water every 15–20 minutes, even when not thirsty, with enough water on
site for 1 quart per worker per hour. At High heat and above, workers also get
an hourly water reminder in hours without a scheduled break.

## Sources

* National Weather Service API — https://www.weather.gov/documentation/services-web-api
* NWS heat index equation — https://www.wpc.ncep.noaa.gov/html/heatindex_equation.shtml
* NIOSH Criteria for a Recommended Standard: Occupational Exposure to Heat and Hot Environments (DHHS/NIOSH 2016-106)
* OSHA Technical Manual, Section III, Chapter 4: Heat Stress
* Liljegren, J. C. et al. (2008). Modeling the wet bulb globe temperature using standard meteorological measurements. *J. Occup. Environ. Hyg.* 5(10). doi:10.1080/15459620802310770
* Brimicombe, C. et al. (2022). thermofeel: a Python thermal comfort indices library. *SoftwareX*. https://github.com/ecmwf/thermofeel
* Haurwitz, B. (1945); Kasten, F. & Czeplak, G. (1980); Erbs, D. G., Klein, S. A. & Duffie, J. A. (1982)
* NOAA Global Monitoring Laboratory, General Solar Position Calculations
* KFF Health News on the 2024 proposed federal heat rule — https://kffhealthnews.org/news/article/proposed-federal-heat-labor-rule-outdoor-workers-deaths/
