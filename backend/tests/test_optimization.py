import pytest
from shapely.geometry import shape

from app.engines import energy, optimizer, partition, storage
from app.engines.irrigation import timetable_day

FIELD = {"type": "Polygon", "coordinates": [[[10.0800, 35.6700], [10.0830, 35.6702], [10.0835, 35.6680],
                                             [10.0812, 35.6672], [10.0798, 35.6685], [10.0800, 35.6700]]]}


def _opts():
    months = [f"2027-{m:02d}" for m in range(3, 8)]
    return [optimizer.CropOption("tomato", 60000, 1.0, {m: 1500 for m in months}, 0.2),
            optimizer.CropOption("wheat", 2000, 1.0, {m: 300 for m in months}, 0.9)]


def test_water_constraint_limits_thirsty_crop():
    rich = optimizer.optimize(_opts(), 10, {f"{m:02d}": 1e9 for m in range(1, 13)})
    poor = optimizer.optimize(_opts(), 10, {f"{m:02d}": 3000 for m in range(1, 13)})
    assert rich.status == "optimal"
    assert poor.areas_ha.get("tomato", 0) <= rich.areas_ha.get("tomato", 0) + 1e-6
    for used in poor.water_use_m3.values():
        assert used <= 3000 + 1e-3
    assert any(b.startswith("water_") for b in poor.binding)


def test_locked_area_is_respected():
    opts = _opts()
    opts[0].locked_ha = 3.0
    r = optimizer.optimize(opts, 10, {f"{m:02d}": 1e9 for m in range(1, 13)})
    assert r.areas_ha["tomato"] >= 3.0 - 1e-6


def test_partition_exact_areas_and_water_ordering():
    A = partition.area_m2(FIELD)
    targets = {"tomato": 0.3 * A, "wheat": 0.4 * A}
    res = partition.partition(FIELD, targets, {"tomato": 6000, "wheat": 2500}, [partition.Source(1, 10.0801, 35.669)])
    by = {}
    for p in res["parcels"]:
        g = shape(p["geometry"])
        assert g.is_valid and not g.is_empty
        by.setdefault(p["crop"], []).append(p)
    for c, t in targets.items():   # within 15 % of target once 2 m internal paths are removed
        got = sum(p["area_m2"] for p in by[c])
        assert 0.85 * t < got <= t * 1.001

    def mean(c):
        return sum(p["pipe_length_m"] * p["area_m2"] for p in by[c]) / sum(p["area_m2"] for p in by[c])
    assert mean("tomato") < mean("wheat")          # water-hungry crop closer to the borehole
    polys = [partition.to_utm(shape(p["geometry"])) for p in res["parcels"]]
    for i in range(len(polys)):
        for j in range(i + 1, len(polys)):
            assert polys[i].intersection(polys[j]).area < 1.0


def test_cp_sat_timetable_no_overlap_and_prefers_solar():
    ev = [{"date": "2027-06-01", "parcel": f"P{i}", "crop": "tomato", "volume_m3": 20, "duration_min": 60,
           "source_index": 0, "energy_kwh": 5, "pump_kw": 5} for i in range(4)]
    pv = [0] * 7 + [6] * 10 + [0] * 7   # PV between 07:00 and 17:00
    out = timetable_day(ev, pv, "drip")
    starts = sorted(int(e["start"][:2]) * 60 + int(e["start"][3:]) for e in out)
    for a, b in zip(starts, starts[1:]):
        assert b - a >= 60
    assert all(e["solar_share"] == 1.0 for e in out)


def test_energy_reserve_and_export_cap():
    from tests.conftest import _pv_profile
    pol = energy.EnergyPolicy()
    d = energy.design([600] * 12, [0.5] * 12, 0, 0.5, _pv_profile(), pol)
    ex = d["simulation"]["export"]
    assert ex["within_cap_kwh"] <= 0.30 * d["simulation"]["annual"]["pv"] + 1
    assert ex["hypothesis_note"] == "hypothesis_not_authorised"
    assert d["simulation"]["annual"]["to_reserve"] > 0
    assert d["autonomy_hours"] == pytest.approx(pol.autonomy_hours, rel=0.01)


def test_cold_room_physics():
    r = storage.cold_room("potato", 50, [16, 17, 20, 23, 28, 33, 36, 36, 31, 26, 21, 17])
    assert r["volume_m3"] == pytest.approx(50000 / 350, rel=1e-3)
    july, jan = r["monthly"][6], r["monthly"][0]
    assert july["load_kw"] > jan["load_kw"] > 0 and july["cop"] < jan["cop"]
    assert storage.cold_room("wheat", 50, [20] * 12)["required"] is False


def test_contribution_is_capped_and_a_proposal():
    c = storage.contribution({"wheat": 500}, {"wheat": 1_000_000}, {"wheat": 300_000}, 0.9, 0.5, 1.0, 0.10)
    assert c["status"] == "proposal_requires_validation"
    assert c["items"]["wheat"]["proposed_pct"] <= 10.0
