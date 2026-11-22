"""Automatic production cost per crop (engines/costs.py): no manual entry by the farmer."""
import pytest

from app.engines import costs
from app.engines.policy import DEFAULTS
from app.knowledge.costs import COEF

PRICES = {k: DEFAULTS[f"costs.{k}"]["value"] for k in costs.PRICE_KEYS}
QUAL = {k: DEFAULTS[f"costs.{k}"]["quality"] for k in costs.PRICE_KEYS}


def _cost(code, y=3.0, water=0.0, kwh_m3=None, tariff=None, net=0.0, rainfed=False, official=None):
    return costs.crop_cost_ha(code, y, water, kwh_m3, tariff, net, PRICES, QUAL, rainfed, official)


def test_every_crop_of_the_catalogue_has_coefficients():
    from app.knowledge.crops import CROPS
    assert set(CROPS) <= set(COEF)


def test_labour_fertiliser_and_energy_follow_the_farm():
    b = _cost("tomato", y=60.0, water=6000, kwh_m3=0.5, tariff=0.25)
    it = b["items"]
    c = COEF["tomato"]
    assert it["labour"]["qty"] == pytest.approx(c.labour_base_days + c.harvest_days_per_t * 60)
    assert it["labour"]["tnd"] == pytest.approx(it["labour"]["qty"] * 21.336, rel=1e-3)   # SMAG 2026
    assert it["labour"]["quality"] == "official"
    assert it["energy"]["qty"] == pytest.approx(6000 * 0.5) and it["energy"]["tnd"] == pytest.approx(750)
    assert it["energy"]["quality"] == "measured"
    # fertilisers sized on the nutrients exported by the expected yield
    assert b["nutrients_kg_ha"]["P2O5"] == pytest.approx(c.p2o5_per_t * 60)
    assert it["dap"]["qty"] * 1000 * 0.46 == pytest.approx(c.p2o5_per_t * 60, rel=0.01)
    assert b["total_tnd_ha"] == pytest.approx(sum(x["tnd"] for x in it.values()), abs=1)
    # a better yield costs more labour and fertiliser
    assert _cost("tomato", y=80.0, water=6000, kwh_m3=0.5, tariff=0.25)["total_tnd_ha"] > b["total_tnd_ha"]


def test_rainfed_legume_needs_no_nitrogen_no_pumping_no_drip():
    b = _cost("chickpea", y=1.2, rainfed=True)
    assert "ammonitrate" not in b["items"] and "energy" not in b["items"] and "drip" not in b["items"]
    assert b["nutrients_kg_ha"]["N"] == 0 and b["items"]["dap"]["qty"] > 0


def test_network_water_and_missing_tariff_and_ministry_reference():
    b = _cost("onion", y=30.0, water=5000, kwh_m3=0.6, tariff=None, net=0.5)
    assert b["items"]["water"]["qty"] == pytest.approx(2500) and b["items"]["water"]["tnd"] == pytest.approx(275)
    assert b["items"]["energy"]["qty"] == pytest.approx(2500 * 0.6) and b["items"]["energy"]["tnd"] is None
    assert "grid_tariff" in b["missing"] and b["total_tnd_ha"] > 0
    ref = _cost("onion", official=9000)
    assert ref["total_tnd_ha"] == 9000 and ref["quality"] == "official"
