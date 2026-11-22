from datetime import date

import pytest

from app.engines import fao56, hydraulics
from app.engines.suitability import evaluate, leaching_requirement
from app.knowledge.crops import CROPS
from tests.conftest import TEST_CLIMATE


def test_et0_fao56_example_18():
    # FAO-56 Example 18 (Uccle, 6 July): ET0 = 3.9 mm/day; ea = 1.409 kPa -> RHmean equivalent 70.56 %
    et0 = fao56.et0_penman_monteith(21.5, 12.3, 70.56, 2.078, 22.07, 50.8, 100, 187)
    assert et0 == pytest.approx(3.9, abs=0.15)


def test_saxton_rawls_loam():
    fc, wp = fao56.saxton_rawls(0.40, 0.20, 2.5)
    assert 0.24 < fc < 0.33 and 0.10 < wp < 0.16


@pytest.mark.parametrize("sand,clay,tex", [(0.92, 0.03, "sand"), (0.40, 0.20, "loam"), (0.20, 0.60, "clay"),
                                           (0.65, 0.10, "sandy_loam")])
def test_texture(sand, clay, tex):
    assert fao56.usda_texture(sand, clay) == tex


def test_kc_curve_shape():
    c = CROPS["tomato"]
    li, ld, lm, ll = c.stages
    assert fao56.kc_on_day(c, 0) == c.kc[0]
    assert fao56.kc_on_day(c, li + ld + 1) == c.kc[1]
    mid = fao56.kc_on_day(c, li + ld // 2)
    assert c.kc[0] < mid < c.kc[1]
    assert fao56.kc_on_day(c, sum(c.stages) + 5) == c.kc[2]


def test_effective_rain():
    assert fao56.effective_rain_monthly(50) == pytest.approx(20)
    assert fao56.effective_rain_monthly(100) == pytest.approx(55)
    assert fao56.effective_rain_monthly(5) == 0


def test_crop_water_plan_summer_vs_winter():
    tomato = fao56.crop_water_plan(CROPS["tomato"], date(2027, 3, 15), TEST_CLIMATE)
    wheat = fao56.crop_water_plan(CROPS["wheat"], date(2026, 11, 15), TEST_CLIMATE)
    assert tomato.net_irrigation_mm > wheat.net_irrigation_mm > 0
    assert sum(tomato.monthly_net_mm.values()) == pytest.approx(tomato.net_irrigation_mm, rel=0.01)


def test_hazen_williams_monotonic_and_power():
    d = hydraulics.select_diameter(20)
    assert hydraulics.friction_loss_m(200, 20, d) > hydraulics.friction_loss_m(100, 20, d) > 0
    pp = hydraulics.pumping_point(20, 150, 40, 2, 10, 0.5)
    assert pp.power_kw == pytest.approx(9.81 * 20 / 3600 * pp.total_head_m / 0.5, rel=1e-3)   # P = rho g Q H / eta
    assert pp.specific_energy_kwh_m3 == pytest.approx(pp.power_kw / 20, rel=1e-3)


def test_salinity_reduces_yield_and_date_palm_needs_heat():
    s = evaluate(CROPS["onion"], TEST_CLIMATE, {}, water_ec=3.0)
    assert s.relative_yield < 1 and "salinity" in s.reasons
    cool = TEST_CLIMATE.__class__(TEST_CLIMATE.et0_mm_day, TEST_CLIMATE.rain_mm,
                                  [t - 6 for t in TEST_CLIMATE.tmax_c], TEST_CLIMATE.tmin_c, "x")
    s = evaluate(CROPS["date_palm"], cool, {}, None, allow_new_orchards=True)
    assert not s.suitable and "summer_not_hot_enough" in s.reasons


def test_leaching_requirement():
    assert leaching_requirement(None, CROPS["tomato"], "drip") == 0
    lr = leaching_requirement(2.0, CROPS["tomato"], "sprinkler")
    assert lr == pytest.approx(2.0 / (5 * 2.5 - 2.0), rel=1e-6)
